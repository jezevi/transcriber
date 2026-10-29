"""Самопроверка: что работает именно на этом компьютере. Запуск: кнопка «Самопроверка» или `TransCheck.exe --selftest`."""
from __future__ import annotations

import platform
import sys
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from . import VERSION, config, rules_ru, spell

OK, FAIL, SKIP = "ok", "fail", "skip"

# (набранное → после «исправить безопасное»), примеры взяты из инструкции
EXAMPLES = [
    ("Привет, Мир! Это тест — ёжик.", "привет мир это тест ежик"),
    ("вышел блядь на бульвар", "вышел блять на бульвар"),
    ("пошел на хуй", "пошел нахуй"),
    ("щас приду, ниче се", "сейчас приду ниче себе"),
    ("сбер ай ди, сбер пэй, гуглплэй, кю ар код", "сбер айди сберпэй гугл плэй кюар код"),
    ("мат капитал и физ лицо", "маткапитал и физлицо"),
    ("позвони в эмтээс по эндэфээл", "позвони в мтс по ндфл"),
    ("отменить подписку на youtube", "отменить подписку на ютуб"),
    ("монитор samsung full hd", "монитор самсунг фулл эйчди"),
    ("компания mc intermark auto каско", "компания мс интермарк авто каско"),
    ("алё это я", "алло это я"),
    ("три тыщ рублей", "три тысяч рублей"),
]
# (набранное → код замечания, которое обязано появиться)
FLAGGED = [
    ("позвони по номеру +7 900 123 45 67", "number"),
    ("я по по по пошел гулять", "stutter"),
    ("я последний раз сидел ха ха ха ну в общем вышел", "laugh"),
    ("номер карты эммммм два три пять", "parasite"),
    ("вышел бл*** на бульвар", "mask"),
    ("закрой глаза give me what I need pull me in", "latin_phrase"),
    ("поставь на repeat", "latin"),
]


@dataclass
class Result:
    name: str
    status: str
    detail: str = ""


def _run(name: str, fn: Callable[[], Optional[Result]], results: List[Result]) -> None:
    try:
        r = fn()
        results.append(r if r is not None else Result(name, OK))
    except Exception as e:
        results.append(Result(name, FAIL, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"))


def run_all(
    directory: str, gui: bool = True, hotkeys_free: bool = True, winapi_mod: Any = None, speller: Any = None, spell_status: str = ""
) -> List[Result]:
    results: List[Result] = []

    def system() -> Result:
        try:
            import tkinter

            tk = f"Tk {tkinter.TkVersion}"
        except ImportError:
            tk = "tkinter не найден"
        frozen = "собранная программа" if getattr(sys, "frozen", False) else "из исходников"
        return Result("Система", OK, f"TransCheck {VERSION} ({frozen}); {platform.system()} {platform.release()}; Python {platform.python_version()}; {tk}")

    def settings() -> Result:
        cfg = config.load_config(directory, create=False)
        config.parse_all_hotkeys(cfg)
        text = config.read_rules_extra(directory)
        rules, problems = rules_ru.parse_extra_rules(text)
        detail = f"config.json в порядке; своих правил: {len(rules)}"
        if problems:
            return Result("Настройки и свои правила", FAIL, detail + "\n" + "\n".join(problems))
        return Result("Настройки и свои правила", OK, detail)

    def examples() -> Result:
        bad = []
        for src, want in EXAMPLES:
            got = rules_ru.fix_all(src)
            if got != want:
                bad.append(f"{src!r}: получено {got!r}, ожидалось {want!r}")
        for src, code in FLAGGED:
            if code not in [i.code for i in rules_ru.analyze(src).issues]:
                bad.append(f"{src!r}: не найдено замечание «{code}»")
        total = len(EXAMPLES) + len(FLAGGED)
        if bad:
            return Result("Правила на примерах из инструкции", FAIL, f"не прошло {len(bad)} из {total}:\n" + "\n".join(bad))
        return Result("Правила на примерах из инструкции", OK, f"прошло {total} из {total}")

    def clipboard() -> Result:
        if winapi_mod is None:
            return Result("Буфер обмена", SKIP, "только в Windows")
        probe = "проверка буфера: Привет, мир!\nвторая строка ёё"
        previous = None
        try:
            previous = winapi_mod.get_clipboard_text()
        except Exception:
            pass
        try:
            before = winapi_mod.clipboard_seq()
            winapi_mod.set_clipboard_text(probe)
            after = winapi_mod.clipboard_seq()
            got = winapi_mod.get_clipboard_text()
        finally:
            if previous is not None:
                try:
                    winapi_mod.set_clipboard_text(previous)
                except Exception:
                    pass
        if after == before:
            return Result("Буфер обмена", FAIL, "после записи номер изменений буфера не изменился: слежение за буфером не сработает")
        if (got or "").replace("\r\n", "\n") != probe:
            return Result("Буфер обмена", FAIL, f"записано и прочитано разное: {got!r}")
        return Result("Буфер обмена", OK, "запись, чтение и слежение за изменениями работают (прежний текст в буфере возвращён)")

    def hotkeys() -> Result:
        if winapi_mod is None:
            return Result("Горячие клавиши", SKIP, "только в Windows")
        if not hotkeys_free:
            return Result("Горячие клавиши", SKIP, "уже зарегистрированы работающей программой")
        import queue

        cfg = config.load_config(directory, create=False)
        t = winapi_mod.start_hotkeys(config.parse_all_hotkeys(cfg), queue.Queue())
        t.stop()
        return Result("Горячие клавиши", OK, "все три свободны и регистрируются")

    def spelling() -> Result:
        if speller is None:
            return Result("Орфография", SKIP, "не проверяется: " + (spell_status or "словаря нет"))
        problems = spell.probe(speller, spell.GOOD_WORDS, spell.BAD_WORDS)
        service = spell.SpellService(speller)
        detail = f"{spell_status}. «козел» принят, «казел» отклонён; варианты для «казел»: {', '.join(service.suggestions('казел')) or 'нет'}"
        if problems:
            return Result("Орфография", FAIL, spell_status + ":\n" + "\n".join(problems))
        return Result("Орфография", OK, detail)

    def window() -> Result:
        if not gui:
            return Result("Окно", SKIP, "проверяется при запуске программы")
        import tkinter as tk

        from . import ui

        root = tk.Tk()
        try:
            root.withdraw()
            w = ui.MainWindow(root)
            w.set_text("Привет, Мир! щас 25")
            n = len(w.analysis.issues)
            fixed = w.fix_safe()
            root.update_idletasks()
        finally:
            root.destroy()
        if n < 3 or fixed != "привет мир сейчас 25":
            return Result("Окно", FAIL, f"замечаний {n}, результат {fixed!r}")
        return Result("Окно", OK, "окно создаётся, подсветка и исправление работают")

    t0 = time.perf_counter()
    for name, fn in (
        ("Система", system), ("Настройки и свои правила", settings), ("Правила на примерах из инструкции", examples),
        ("Буфер обмена", clipboard), ("Горячие клавиши", hotkeys), ("Орфография", spelling), ("Окно", window),
    ):
        _run(name, fn, results)
    results.append(Result("Время", OK, f"{time.perf_counter() - t0:.1f} с"))
    return results


def format_report(results: List[Result]) -> str:
    marks = {OK: "[ ОК ]", FAIL: "[СБОЙ]", SKIP: "[ -- ]"}
    lines = [f"TransCheck {VERSION}: самопроверка", ""]
    for r in results:
        lines.append(f"{marks[r.status]} {r.name}")
        if r.detail:
            lines.extend("        " + ln for ln in r.detail.splitlines())
    failed = [r for r in results if r.status == FAIL]
    lines += ["", f"Итог: {'всё в порядке' if not failed else 'есть сбои: ' + str(len(failed))}"]
    lines.append("Что здесь НЕ проверяется: правила вашего задания, которых нет в инструкции от " + rules_ru.INSTRUCTION_DATE + ".")
    return "\n".join(lines)


def main(args: List[str]) -> int:
    out: Optional[str] = None
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1] if i + 1 < len(args) else None
    winapi_mod: Any = None
    if sys.platform == "win32":
        try:
            from . import winapi as win_module

            winapi_mod = win_module
        except ImportError:
            winapi_mod = None
    results = run_all(
        config.app_dir(), gui="--no-gui" not in args, hotkeys_free=True, winapi_mod=winapi_mod,
        speller=None, spell_status="проверяется кнопкой «Самопроверка» в окне работающей программы",
    )
    report = format_report(results)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
    if "--quiet" not in args:
        try:
            print(report)
        except UnicodeEncodeError:
            print(report.encode("ascii", "replace").decode("ascii"))
    return 1 if any(r.status == FAIL for r in results) else 0
