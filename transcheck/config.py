"""Настройки, путь к папке программы, разбор горячих клавиш."""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Dict, Tuple

from . import VERSION  # noqa: F401  (удобно импортировать версию отсюда)


class TransCheckError(Exception):
    """Ошибка, текст которой показывается пользователю как есть (по-русски)."""


DEFAULT_CONFIG: Dict[str, object] = {
    "hotkey_check": "ctrl+alt+k",  # взять текст из буфера обмена и проверить
    "hotkey_fix": "ctrl+alt+j",  # исправить всё безопасное и скопировать результат в буфер обмена
    "hotkey_quit": "ctrl+alt+q",  # выйти из программы
    "watch_clipboard": True,  # сами подхватывать текст, когда вы что-то копируете
    "topmost": True,  # окно поверх остальных
    "max_chars": 5000,  # длиннее этого текст не подхватывается (защита от случайно скопированной страницы)
}

HOTKEY_FIELDS = ("hotkey_check", "hotkey_fix", "hotkey_quit")
_TYPE_NAMES = {str: "текст", int: "целое число", bool: "true или false"}

RULES_EXTRA_TEMPLATE = (
    "# Свои правила замены. Одна строка — одно правило:  как не надо => как надо\n"
    "# Строки, которые начинаются с «#», программа не читает.\n"
    "# Регистр, «ё» и знаки препинания в правилах не учитываются: писать можно как удобно.\n"
    "# Правила действуют сразу после сохранения файла, перезапускать программу не нужно.\n"
    "# Они сильнее встроенных. Нужны, когда инструкция изменилась, а программа об этом ещё не знает.\n"
    "#\n"
    "# Примеры (уберите «#» в начале строки, чтобы включить):\n"
    "# по тихому => потихому\n"
    "# оч => очень\n"
)


def app_dir() -> str:
    """Папка, где лежат config.json и rules_extra.txt (рядом с .exe или с run.py)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(directory: str, create: bool = True) -> Dict[str, object]:
    cfg: Dict[str, object] = dict(DEFAULT_CONFIG)
    path = os.path.join(directory, "config.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                user = json.load(f)
        except (OSError, ValueError) as e:
            raise TransCheckError(f"Файл config.json не читается: {e}")
        if not isinstance(user, dict):
            raise TransCheckError('config.json: ожидается объект вида { "topmost": true }.')
        for key, value in user.items():
            if key not in DEFAULT_CONFIG:
                continue  # неизвестные поля игнорируем, чтобы старые конфиги не ломались
            expected = type(DEFAULT_CONFIG[key])
            ok = isinstance(value, expected) and not (expected is int and isinstance(value, bool))
            if not ok:
                raise TransCheckError(f"config.json: поле «{key}» должно быть: {_TYPE_NAMES.get(expected, expected.__name__)}.")
            cfg[key] = value
    elif create:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        except OSError:
            pass  # нет прав на запись рядом с программой: работаем со значениями по умолчанию
    if int(cfg["max_chars"]) <= 0:  # type: ignore[call-overload]
        raise TransCheckError("config.json: max_chars должно быть больше нуля.")
    return cfg


def rules_extra_path(directory: str) -> str:
    return os.path.join(directory, "rules_extra.txt")


def ensure_rules_extra(directory: str) -> str:
    """Создаёт rules_extra.txt с пояснением, если файла ещё нет. Возвращает путь."""
    path = rules_extra_path(directory)
    if not os.path.isfile(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(RULES_EXTRA_TEMPLATE)
        except OSError:
            pass
    return path


def read_rules_extra(directory: str) -> str:
    path = rules_extra_path(directory)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except UnicodeDecodeError:
        raise TransCheckError("Файл rules_extra.txt не читается (нужна кодировка UTF-8). В Блокноте: Файл → Сохранить как → Кодировка: UTF-8.")
    except OSError as e:
        raise TransCheckError(f"Файл rules_extra.txt не читается: {e}")


# ── горячие клавиши (разбор строки; регистрация — в winapi.py) ───────────────────────────────────

_MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
_NAMED_KEYS = {"space": 0x20, "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "insert": 0x2D, "home": 0x24, "end": 0x23}


def parse_hotkey(spec: str) -> Tuple[int, int]:
    parts = [p.strip().lower() for p in str(spec).split("+") if p.strip()]
    if len(parts) < 2:
        raise TransCheckError(f"Горячая клавиша «{spec}»: нужна хотя бы одна клавиша-модификатор, например ctrl+alt+k.")
    mods = 0
    for p in parts[:-1]:
        if p not in _MODS:
            raise TransCheckError(f"Горячая клавиша «{spec}»: «{p}» не подходит. Допустимо: ctrl, alt, shift, win.")
        mods |= _MODS[p]
    key = parts[-1]
    if len(key) == 1 and "a" <= key <= "z":
        vk = ord(key.upper())
    elif len(key) == 1 and "0" <= key <= "9":
        vk = ord(key)
    elif re.fullmatch(r"f([1-9]|1[0-2])", key):
        vk = 0x70 + int(key[1:]) - 1
    elif key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
    else:
        raise TransCheckError(
            f"Горячая клавиша «{spec}»: клавиша «{key}» не поддерживается. Используйте латинскую букву, цифру, F1–F12 или "
            "space/enter/esc/tab (раскладка клавиатуры значения не имеет)."
        )
    return mods, vk


def parse_all_hotkeys(cfg: Dict[str, object]) -> Dict[str, Tuple[int, int]]:
    """Разбирает горячие клавиши и проверяет, что они не совпадают."""
    result: Dict[str, Tuple[int, int]] = {}
    seen: Dict[Tuple[int, int], str] = {}
    for name in HOTKEY_FIELDS:
        combo = parse_hotkey(str(cfg[name]))
        if combo in seen:
            raise TransCheckError(f"В config.json одна и та же горячая клавиша у «{seen[combo]}» и «{name}»: {cfg[name]}.")
        seen[combo] = name
        result[name] = combo
    return result
