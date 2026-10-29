"""Проверка орфографии словарём Windows (интерфейс ISpellChecker: тот же словарь, что подчёркивает слова в Блокноте и Edge).

Интернет и свои словари не нужны. Весь обмен с COM собран в этом файле. Любая неудача (не Windows, нет русского словаря, ошибка вызова)
приводит только к тому, что орфография не проверяется, а окно честно об этом пишет.
"""
from __future__ import annotations

import ctypes
import os
import re
import sys
import uuid
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import rules_ru as R
from .rules_ru import WARN, Issue

LANGUAGE = "ru-RU"
WORD_RE = re.compile(r"[А-Яа-яЁё]+(?:[-’'][А-Яа-яЁё]+)*")  # русское слово, в том числе через дефис
MAX_ISSUES = 40  # сколько замечаний об орфографии показывать за раз
MAX_SUGGESTIONS = 5

# ── COM: ISpellCheckerFactory / ISpellChecker (spellcheck.h) ─────────────────────────────────────
CLSID_SPELL_CHECKER_FACTORY = "{7AB36653-1796-484B-BDFA-E74F1DB7C1DC}"
IID_SPELL_CHECKER_FACTORY = "{8E018A9D-2415-4677-BF08-794EA61F94BB}"
CLSCTX_ALL = 0x17
COINIT_APARTMENTTHREADED = 0x2
RPC_E_CHANGED_MODE = 0x80010106
# номера методов в таблице (после трёх методов IUnknown)
M_RELEASE = 2
M_FACTORY_IS_SUPPORTED, M_FACTORY_CREATE = 4, 5
M_CHECK, M_SUGGEST = 4, 5
M_ENUM_NEXT = 3  # IEnumSpellingError::Next(ISpellingError**) и IEnumString::Next(celt, LPOLESTR*, ULONG*)
M_ERR_START, M_ERR_LENGTH, M_ERR_ACTION, M_ERR_REPLACEMENT = 3, 4, 5, 6
ACTION_REPLACE = 2  # CORRECTIVE_ACTION_REPLACE: автозамена (например, только регистр)

_FUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)  # в Windows — stdcall, в других системах (тесты) — обычный вызов
_PVOID = ctypes.POINTER(ctypes.c_void_p)
_PU32 = ctypes.POINTER(ctypes.c_uint32)
_PI32 = ctypes.POINTER(ctypes.c_int32)


class SpellError(Exception):
    """Сбой при обращении к проверке орфографии."""


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    u = uuid.UUID(text)
    g = _GUID()
    g.Data1, g.Data2, g.Data3 = u.time_low, u.time_mid, u.time_hi_version
    for i, b in enumerate(bytes([u.clock_seq_hi_variant, u.clock_seq_low]) + u.node.to_bytes(6, "big")):
        g.Data4[i] = b
    return g


def _hex(hr: int) -> str:
    return f"0x{hr & 0xFFFFFFFF:08X}"


def _call(obj: int, index: int, *args: Tuple[object, object]) -> int:
    """Вызывает метод номер index у COM-объекта obj. args: пары (тип параметра в ctypes, значение). Возвращает HRESULT."""
    if not obj:
        raise SpellError("пустой указатель COM")
    vtable = ctypes.cast(ctypes.c_void_p(obj), _PVOID)[0]
    if not vtable:
        raise SpellError("у COM-объекта нет таблицы методов")
    address = ctypes.cast(ctypes.c_void_p(vtable), _PVOID)[index]
    prototype = _FUNCTYPE(ctypes.c_int32, ctypes.c_void_p, *[a[0] for a in args])  # type: ignore[call-overload,arg-type]
    return int(prototype(address)(ctypes.c_void_p(obj), *[a[1] for a in args]))


def _ok(hr: int, what: str) -> None:
    if hr < 0:
        raise SpellError(f"{what}: код {_hex(hr)}")


def _release(obj: Optional[int]) -> None:
    if obj:
        try:
            _call(obj, M_RELEASE)
        except SpellError:
            pass


def _co_task_mem_free(pointer: int) -> None:  # pragma: no cover  (только Windows)
    ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree(ctypes.c_void_p(pointer))


def _norm(word: str) -> str:
    return word.lower().replace("ё", "е")


class ComSpeller:
    """Обёртка над указателем на ISpellChecker. Все вызовы нужно делать из того потока, который создал объект (главный поток окна)."""

    def __init__(self, checker: int, free: Callable[[int], None] = _co_task_mem_free) -> None:
        self._p = checker
        self._free = free

    def _string(self, pointer: Optional[int]) -> str:
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            self._free(pointer)

    def check(self, text: str) -> List[Tuple[int, int, int, str]]:
        """Список ошибок в тексте: (начало, длина, действие, замена)."""
        enum = ctypes.c_void_p()
        _ok(_call(self._p, M_CHECK, (ctypes.c_wchar_p, text), (_PVOID, ctypes.byref(enum))), "Check")
        found: List[Tuple[int, int, int, str]] = []
        if not enum.value:
            return found
        try:
            while len(found) < 200:
                err = ctypes.c_void_p()
                hr = _call(enum.value, M_ENUM_NEXT, (_PVOID, ctypes.byref(err)))
                if hr != 0 or not err.value:  # S_FALSE — ошибки кончились
                    break
                try:
                    start, length, action, replacement = ctypes.c_uint32(), ctypes.c_uint32(), ctypes.c_int32(), ctypes.c_void_p()
                    _ok(_call(err.value, M_ERR_START, (_PU32, ctypes.byref(start))), "StartIndex")
                    _ok(_call(err.value, M_ERR_LENGTH, (_PU32, ctypes.byref(length))), "Length")
                    _ok(_call(err.value, M_ERR_ACTION, (_PI32, ctypes.byref(action))), "CorrectiveAction")
                    _ok(_call(err.value, M_ERR_REPLACEMENT, (_PVOID, ctypes.byref(replacement))), "Replacement")
                    found.append((start.value, length.value, action.value, self._string(replacement.value)))
                finally:
                    _release(err.value)
        finally:
            _release(enum.value)
        return found

    def suggest(self, word: str, limit: int = 8) -> List[str]:
        enum = ctypes.c_void_p()
        _ok(_call(self._p, M_SUGGEST, (ctypes.c_wchar_p, word), (_PVOID, ctypes.byref(enum))), "Suggest")
        out: List[str] = []
        if not enum.value:
            return out
        try:
            while len(out) < limit:
                item, fetched = ctypes.c_void_p(), ctypes.c_uint32()
                hr = _call(enum.value, M_ENUM_NEXT, (ctypes.c_uint32, 1), (_PVOID, ctypes.byref(item)), (_PU32, ctypes.byref(fetched)))
                if hr != 0 or fetched.value != 1 or not item.value:
                    break
                out.append(self._string(item.value))
        finally:
            _release(enum.value)
        return out

    def is_correct(self, word: str) -> bool:
        """Слово написано верно. Исключения, которые словарь считает «автозаменой» только по регистру, ошибкой не считаются."""
        for _start, _length, action, replacement in self.check(word):
            if action == ACTION_REPLACE and _norm(replacement) == _norm(word):
                continue
            # название с большой буквы, написанное по правилам расшифровки с маленькой: словарь предлагает то же слово
            if any(_norm(s) == _norm(word) for s in self.suggest(word)):
                continue
            return False
        return True


def create_windows_speller(language: str = LANGUAGE) -> Tuple[Optional[ComSpeller], str]:
    """(проверка орфографии, пояснение). Если проверка недоступна, первым значением будет None, а пояснением — причина."""
    if sys.platform != "win32":
        return None, "проверка орфографии работает только в Windows"
    try:  # pragma: no cover  (настоящий COM есть только в Windows)
        ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole32.CoInitializeEx.restype = ctypes.c_int32
        hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        if hr < 0 and (hr & 0xFFFFFFFF) != RPC_E_CHANGED_MODE:  # «уже запущен в другом режиме» нам не мешает
            return None, f"не удалось запустить COM ({_hex(hr)})"
        ole32.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_GUID), _PVOID]
        ole32.CoCreateInstance.restype = ctypes.c_int32
        factory = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(_guid(CLSID_SPELL_CHECKER_FACTORY)), None, CLSCTX_ALL, ctypes.byref(_guid(IID_SPELL_CHECKER_FACTORY)), ctypes.byref(factory)
        )
        if hr < 0 or not factory.value:
            return None, f"в этой Windows нет службы проверки орфографии ({_hex(hr)})"
        supported = ctypes.c_int32()
        _ok(_call(factory.value, M_FACTORY_IS_SUPPORTED, (ctypes.c_wchar_p, language), (_PI32, ctypes.byref(supported))), "IsSupported")
        if not supported.value:
            return None, f"в Windows нет словаря «{language}» (проверьте, что русский язык установлен: Параметры → Время и язык → Язык и регион)"
        checker = ctypes.c_void_p()
        _ok(_call(factory.value, M_FACTORY_CREATE, (ctypes.c_wchar_p, language), (_PVOID, ctypes.byref(checker))), "CreateSpellChecker")
        if not checker.value:
            return None, "Windows не создала проверку орфографии"
        return ComSpeller(checker.value), f"словарь Windows ({language})"
    except Exception as e:
        return None, f"проверка орфографии недоступна: {type(e).__name__}: {e}"


# ── слова, замечания ─────────────────────────────────────────────────────────────────────────────

def yo_variants(word: str, limit: int = 15) -> List[str]:
    """Варианты слова, в которых некоторые «е» заменены на «ё» (по инструкции пишем «е», а словарь знает «ё»)."""
    positions = [i for i, ch in enumerate(word) if ch == "е"]
    if not positions:
        return []
    out: List[str] = []
    if len(positions) <= 4:
        for mask in range(1, 2 ** len(positions)):
            chars = list(word)
            for bit, pos in enumerate(positions):
                if mask >> bit & 1:
                    chars[pos] = "ё"
            out.append("".join(chars))
    else:
        for pos in positions:
            out.append(word[:pos] + "ё" + word[pos + 1 :])
        out.append(word.replace("е", "ё"))
    return out[:limit]


class SpellService:
    """Слова-проверки с запоминанием ответов и правилами расшифровки: «ё» не обязательна, дефисные слова проверяются по частям."""

    def __init__(self, speller: object) -> None:
        self.speller = speller
        self._ok: Dict[str, bool] = {}
        self._suggestions: Dict[str, List[str]] = {}

    def _raw_ok(self, word: str) -> bool:
        return bool(self.speller.is_correct(word))  # type: ignore[attr-defined]

    def is_correct(self, word: str) -> bool:
        low = word.lower()
        if low not in self._ok:
            self._ok[low] = self._check(low)
            if len(self._ok) > 20000:
                self._ok.clear()
        return self._ok[low]

    def _check(self, low: str) -> bool:
        if self._raw_ok(low) or any(self._raw_ok(v) for v in yo_variants(low)):
            return True
        parts = re.split(r"[-’']", low)
        return len(parts) > 1 and all(len(p) < 2 or self.is_correct(p) for p in parts)

    def suggestions(self, word: str) -> List[str]:
        """Варианты замены в том виде, как их надо писать в расшифровке (строчные, без «ё», дефис → пробел)."""
        low = word.lower()
        if low not in self._suggestions:
            try:
                raw = list(self.speller.suggest(low))  # type: ignore[attr-defined]
            except Exception:
                raw = []
            out: List[str] = []
            for candidate in raw:
                fixed = R.fix_all(candidate).strip()
                if not fixed or fixed == _norm(low) or fixed in out or re.search(r"[A-Za-z0-9]", fixed):
                    continue
                out.append(fixed)
                if len(out) >= MAX_SUGGESTIONS:
                    break
            self._suggestions[low] = out
        return self._suggestions[low]


def find_spelling_issues(
    text: str,
    service: SpellService,
    known_words: Optional[Set[str]] = None,
    occupied: Sequence[Tuple[int, int]] = (),
    limit: int = MAX_ISSUES,
) -> List[Issue]:
    """Замечания об орфографии. Слова, которые уже разобраны другими правилами (occupied), и слова из «своих слов» не проверяются."""
    issues: List[Issue] = []
    known = known_words or set()
    for m in WORD_RE.finditer(text):
        start, end = m.span()
        word = m.group()
        if len(word) < 2 or _norm(word) in known:
            continue
        if any(a < end and start < b for a, b in occupied):
            continue
        try:
            if service.is_correct(word):
                continue
            variants = service.suggestions(word)
        except SpellError:
            break  # словарь перестал отвечать: показываем то, что успели
        hint = ("Варианты: " + ", ".join(variants) + ".") if variants else "Вариантов нет."
        message = f"Слова «{word}» нет в словаре Windows: возможно, опечатка. {hint} Если слово верное (имя, название, разговорное слово), нажмите «Слово верное»."
        issues.append(Issue(start, end, WARN, "spell", message, "", variants[0] if variants else None, False))
        if len(issues) >= limit:
            break
    return issues


def probe(speller: object, good: Iterable[str], bad: Iterable[str]) -> List[str]:
    """Проверка на известных словах для самопроверки: список расхождений (пустой — всё как ожидалось)."""
    service = SpellService(speller)
    problems: List[str] = []
    for word in good:
        if not service.is_correct(word):
            problems.append(f"верное слово «{word}» словарь не принял")
    for word in bad:
        if service.is_correct(word):
            problems.append(f"слово с ошибкой «{word}» словарь принял")
    return problems


# слова, по которым проверяем, что словарь вообще можно использовать
GOOD_WORDS = ("привет", "сейчас", "козел", "потому", "хотел", "вчера")
BAD_WORDS = ("казел", "хател", "вчира", "патаму")
GUARD_FILE = "spell_crash.flag"


def create_guarded(directory: str, factory: Callable[[], Tuple[Optional[object], str]] = create_windows_speller) -> Tuple[Optional[object], str]:
    """Создаёт проверку орфографии и сразу пробует её на известных словах.

    Пока идёт попытка, рядом с программой лежит файл spell_crash.flag. Если программа аварийно закрылась прямо во время обращения к
    Windows, файл остаётся, и при следующем запуске орфография не включается: программа не должна падать при каждом запуске.
    """
    flag = os.path.join(directory, GUARD_FILE)
    if os.path.exists(flag):
        return None, f"выключена: прошлая попытка включить её закончилась аварийно (удалите файл {GUARD_FILE} рядом с программой, чтобы попробовать снова)"
    try:
        with open(flag, "w", encoding="utf-8") as f:
            f.write("Если этот файл остался после запуска, прошлая попытка включить проверку орфографии закончилась аварийно.\n")
    except OSError:
        pass  # нет прав на запись рядом с программой: работаем без защиты от повторных сбоев
    try:
        speller, status = factory()
        if speller is None:
            return None, status
        try:
            # проходим и по пути «слово верно», и по пути «ошибка и варианты замены»; отвергнутое верное слово — повод не доверять словарю
            problems = [p for p in probe(speller, GOOD_WORDS, BAD_WORDS) if p.startswith("верное")]
        except SpellError as e:
            return None, f"словарь не отвечает: {e}"
        if problems:
            return None, "словарь работает странно и не используется: " + "; ".join(problems)
        return speller, status
    finally:
        try:
            os.remove(flag)
        except OSError:
            pass
