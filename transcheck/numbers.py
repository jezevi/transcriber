"""Числа словами по-русски. Только именительный падеж: падеж и род в живой речи зависят от соседних слов,
поэтому результат всегда нужно проверить глазами (программа это и говорит)."""
from __future__ import annotations

from typing import List, Optional

_ONES = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_ONES_F = ["ноль", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_TEENS = [
    "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать",
    "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать",
]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
_HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
# (форма для 1, форма для 2–4, форма для 5+, женский род)
_SCALES = [
    ("тысяча", "тысячи", "тысяч", True),
    ("миллион", "миллиона", "миллионов", False),
    ("миллиард", "миллиарда", "миллиардов", False),
]
MAX_NUMBER = 10**12 - 1


def _plural(n: int, one: str, few: str, many: str) -> str:
    if 11 <= n % 100 <= 14:
        return many
    if n % 10 == 1:
        return one
    if 2 <= n % 10 <= 4:
        return few
    return many


def _triplet(n: int, feminine: bool) -> List[str]:
    words: List[str] = []
    h, rest = divmod(n, 100)
    if h:
        words.append(_HUNDREDS[h])
    if 10 <= rest <= 19:
        words.append(_TEENS[rest - 10])
    else:
        t, o = divmod(rest, 10)
        if t:
            words.append(_TENS[t])
        if o:
            words.append((_ONES_F if feminine else _ONES)[o])
    return words


def number_to_words(n: int) -> str:
    """0 → «ноль», 2026 → «две тысячи двадцать шесть». Для n вне 0…999 999 999 999 бросает ValueError."""
    if not 0 <= n <= MAX_NUMBER:
        raise ValueError("число вне допустимого диапазона")
    if n == 0:
        return _ONES[0]
    parts: List[str] = []
    scale = 0
    while n:
        n, chunk = divmod(n, 1000)
        if chunk:
            if scale == 0:
                parts = _triplet(chunk, False) + parts
            else:
                one, few, many, fem = _SCALES[scale - 1]
                parts = _triplet(chunk, fem) + [_plural(chunk, one, few, many)] + parts
        scale += 1
    return " ".join(parts)


def spell_numeric_token(word: str) -> Optional[str]:
    """«45» → «сорок пять», «+7» → «плюс семь», «+» → «плюс», «№» → «номер». Всё остальное (в том числе числа с ведущим
    нулём, десятичные дроби, цифры внутри слов) — None: такое человек должен записать сам."""
    prefix = ""
    rest = word
    if rest.startswith("+"):
        prefix, rest = "плюс", rest[1:]
    elif rest.startswith("№"):
        prefix, rest = "номер", rest[1:]
    if not rest:
        return prefix or None
    if not all("0" <= ch <= "9" for ch in rest):
        return None
    if len(rest) > 12 or (len(rest) > 1 and rest[0] == "0"):
        return None
    words = number_to_words(int(rest))
    return f"{prefix} {words}" if prefix else words
