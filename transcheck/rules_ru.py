"""Проверка русской расшифровки по «Инструкции по транскрибации аудио» (версия от 28.10.2026).

Программа ничего не придумывает за человека: она сверяет набранный им текст с правилами инструкции и
  • сама исправляет только механическое и однозначное (регистр, «ё», знаки, пробелы, двойники букв,
    написания из таблицы-шпаргалки) — такие замечания помечены auto=True;
  • остальное (числа, латиница, смех, заикание, звуки-паразиты, мат со звёздочками) только подсвечивает;
    предложение, если оно есть, применяется лишь по команде человека.

Каждая замена записана в таблицах ниже вместе с номером раздела инструкции.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .numbers import spell_numeric_token

INSTRUCTION_DATE = "28.10.2026"
ERROR, WARN, INFO = "error", "warn", "info"
_LEVEL_RANK = {ERROR: 0, WARN: 1, INFO: 2}
FOREIGN_CHECKBOX = "«В записи присутствуют иностранные слова»"
UNTRANSCRIBABLE_MARK = "«Есть речь, которую невозможно транскрибировать»"


@dataclass(frozen=True)
class Issue:
    start: int  # позиция в исходном тексте (включительно)
    end: int  # позиция в исходном тексте (не включительно)
    level: str  # ERROR — нарушение; WARN — проверьте сами; INFO — напоминание
    code: str  # короткий код правила (для тестов и отладки)
    message: str  # что не так, по-русски
    section: str = ""  # раздел инструкции
    suggestion: Optional[str] = None  # на что заменить фрагмент (None — предложения нет)
    auto: bool = False  # входит в «исправить всё безопасное»


@dataclass(frozen=True)
class Rule:
    """Слова в pattern записаны в нормализованном виде: строчные, «е» вместо «ё», без знаков препинания."""

    pattern: Tuple[str, ...]
    replacement: str
    section: str
    note: str = ""
    foreign: bool = False  # слово иностранное: после замены нужна галочка «иностранные слова»


# ── таблицы правил ───────────────────────────────────────────────────────────────────────────────

def _r(pattern: str, replacement: str, section: str, note: str = "", foreign: bool = False) -> Rule:
    return Rule(tuple(pattern.split()), replacement, section, note, foreign)


LEXICON: List[Rule] = [
    # раздел 2. Аббревиатуры (не по звукам, не склоняются)
    _r("эмтээс", "мтс", "2", "аббревиатура пишется буквами, а не по звукам"),
    _r("эндэфээл", "ндфл", "2", "аббревиатура пишется буквами, а не по звукам"),
    _r("снилса", "снилс", "2", "аббревиатуры не склоняются"),
    _r("кпэшка", "кп", "2", "договор купли-продажи"),
    _r("кпэшку", "кп", "2", "договор купли-продажи"),
    # раздел 4 и шпаргалка. Просторечие и варианты написания
    _r("щас", "сейчас", "4"),
    _r("наверно", "наверное", "4"),
    _r("риэлтор", "риелтор", "4"),
    _r("риелтер", "риелтор", "4"),
    _r("типо", "типа", "4"),
    _r("кешбек", "кэшбэк", "4"),
    _r("кэшбек", "кэшбэк", "4"),
    _r("кешбэк", "кэшбэк", "4"),
    _r("ниче се", "ниче себе", "4"),
    _r("але", "алло", "4"),
    _r("писят", "пятьдесят", "4", "числительные всегда пишем правильно"),
    _r("пидиэф", "пдф", "4", "аббревиатура"),
    _r("хмл", "иксмл", "4"),
    # раздел 10. Иностранные слова кириллицей, число слов как в оригинале
    _r("сбер ай ди", "сбер айди", "10"),
    _r("гуглплэй", "гугл плэй", "10"),
    _r("кю ар код", "кюар код", "10"),
    # раздел 11. Слова с частью «сбер»
    _r("сбер пэй", "сберпэй", "11"),
    _r("сбер бизнес", "сбербизнес", "11"),
    _r("сбер кидс", "сберкидс", "11"),
    _r("сбер купон", "сберкупон", "11"),
    _r("сбер страхование", "сберстрахование", "11"),
    _r("сбер авто", "сберавто", "11"),
    _r("сбер мобайл", "сбермобайл", "11"),
    _r("сбер прайм", "сберпрайм", "11"),
    _r("сбер маркет", "сбермаркет", "11"),
    _r("сбер спасибо", "сберспасибо", "11"),
    _r("сбер онлайн", "сберонлайн", "11"),
    _r("сберконтактмониторинг", "сберконтакт мониторинг", "11"),
    # раздел 15. Мат: один вариант написания, без звёздочек
    _r("блядь", "блять", "15"),
    _r("бляць", "блять", "15"),
    _r("на хуй", "нахуй", "15", "приставки и «не» с матом пишутся слитно"),
    _r("по хуй", "похуй", "15", "приставки и «не» с матом пишутся слитно"),
    _r("ни хуя", "нихуя", "15", "приставки и «не» с матом пишутся слитно"),
    _r("ахуенно", "охуенно", "15"),
    _r("ахуеть", "охуеть", "15"),
    _r("ебанный", "ебаный", "15"),
    # шпаргалка. Иностранное: как пишем кириллицей (после замены нужна галочка «иностранные слова»)
    _r("jpeg", "джипег", "шпаргалка", foreign=True),
    _r("pdf", "пдф", "шпаргалка", "аббревиатура", foreign=True),
    _r("xml", "иксмл", "шпаргалка", foreign=True),
    _r("whatsapp", "ватсап", "шпаргалка", foreign=True),
    _r("html", "аштимл", "шпаргалка", foreign=True),
    _r("usb", "юсб", "шпаргалка", foreign=True),
    _r("paypass", "пэйпасс", "шпаргалка", foreign=True),
    _r("hashtag", "хештег", "шпаргалка", foreign=True),
    _r("excel", "эксель", "шпаргалка", foreign=True),
    _r("enter", "энтер", "шпаргалка", foreign=True),
    _r("nfc", "энэфси", "шпаргалка", foreign=True),
    _r("hdr", "ашдиар", "шпаргалка", foreign=True),
    _r("cvc", "сивиси", "шпаргалка", foreign=True),
    _r("cvv", "сививи", "шпаргалка", foreign=True),
    _r("tele2", "теле два", "шпаргалка", "русское название", foreign=True),
    _r("2gis", "два гис", "шпаргалка", "русское название", foreign=True),
    _r("the", "зе", "иностранные слова", "артикль «the» всегда «зе»", foreign=True),
    # примеры из раздела 10
    _r("youtube", "ютуб", "10", foreign=True),
    _r("samsung", "самсунг", "10", foreign=True),
    _r("minecraft", "майнкрафт", "10", foreign=True),
    _r("full hd", "фулл эйчди", "10", foreign=True),
    _r("apple wallet", "эппл воллет", "10", foreign=True),
    _r("google play", "гугл плэй", "10", foreign=True),
    _r("доме клике", "домклике", "шпаргалка", "окончание склоняем"),
    _r("mc intermark auto", "мс интермарк авто", "10", "название любой длины считается одним словом", foreign=True),
    _r("okay", "окей", "10", foreign=True),
    _r("ok", "окей", "10", foreign=True),
]

# Одно слово по шаблону: (шаблон, замена, раздел, пояснение)
REGEX_RULES: List[Tuple["re.Pattern[str]", str, str, str]] = [
    (re.compile(r"^тыщ(а|и|у|е|ей|ами|ах|ам)?$"), r"тысяч\1", "4", "«тыща» — «тысяча», «тыщ» — «тысяч»"),
    (re.compile(r"^ойе{2,}й$"), "ой ой ой", "7", "«ойеееей» пишем «ой ой ой»"),
]

# Слитное написание составных слов: (первая часть, начало второго слова, раздел)
JOIN_RULES: List[Tuple[str, str, str]] = [
    ("мат", "капитал", "12"),
    ("доп", "соглашени", "12"),
    ("физ", "лиц", "12"),
    ("юр", "лиц", "12"),
    ("кор", "счет", "12"),
    ("юр", "проверк", "12"),
]

# Слова, которые похожи на ошибку, но могут быть верными: только предупреждение, без автозамены
CHECK_WORDS: Dict[str, Tuple[str, str]] = {
    "ток": ("только", "«ток» в значении «только» пишем «только» (шпаргалка). Если это электрический ток — оставьте"),
    "тока": ("только", "«тока» в значении «только» пишем «только» (шпаргалка). Если это электрический ток — оставьте"),
}

# ── символы и их классы ──────────────────────────────────────────────────────────────────────────

HYPHENS = set("-‐‑‒–—―−﹣－")
APOSTROPHES = set("'’ʼ`´‘")  # убираются без пробела: d'ici → dici
KEEP_SYMBOLS = set("+%№$€₽&@#=°§")  # остаются в тексте, чтобы их можно было отметить («пишем словами»)
ZERO_WIDTH = set("​‌‍⁠﻿­‎‏")

# Визуально неотличимые латинские буквы → русские (регистр учитывается до приведения к строчным)
LAT2CYR = {
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
}

_VOWELS = set("аеёиоуыэюя")
# Короткие самостоятельные слова: их повтор перед длинным словом — не обязательно заикание
_SHORT_WORDS = set(
    "в к с у о и а я на по за из от до во со ко об не ни да но же ли бы то ты он мы вы им их ей ее его ну ой ах ох эх уж "
    "как что кто все вот тут там так уже еще где при про без над под для или либо тоже даже это эти тот та те".split()
)
_LAUGH_RE = re.compile(r"^(?:а(?:х[аиеоэ]){2,}х?|ахах|(?:х[аиеоэ])+х?)$")
_PARASITE_RE = re.compile(r"^(?:э+м*|м{2,}|м+э+|хм+|гм+|эм+)$")
_CHANT = {"ла", "ля", "лэ", "пр", "брр", "оу", "эй"}
_CHANT_LONG_RE = re.compile(r"^о{3,}$")


# Короткие названия замечаний для списка в окне
CODE_TITLES = {
    "format": "Регистр, знаки, «ё»",
    "whitespace": "Пробелы",
    "lexicon": "Написание по инструкции",
    "number": "Число или цифры",
    "latin": "Латиница",
    "latin_phrase": "Английская фраза",
    "mask": "Мат со звёздочками",
    "mixed": "Смесь русских и латинских букв",
    "laugh": "Смех",
    "parasite": "Звук-паразит",
    "chant": "Распев",
    "stutter": "Заикание",
    "check_word": "Проверьте слово",
    "other": "Другой алфавит",
    "spell": "Орфография (слова нет в словаре)",
}


def _is_cyr(ch: str) -> bool:
    return "Ѐ" <= ch <= "ԯ"


def _is_lat(ch: str) -> bool:
    return ch.isalpha() and ord(ch) < 0x250


def _classify(ch: str) -> str:
    """letter / digit / keep — символ остаётся; remove — удаляется без пробела; space — заменяется пробелом."""
    if ch in ZERO_WIDTH or ch in APOSTROPHES:
        return "remove"
    if ch.isalpha():
        return "letter"
    cat = unicodedata.category(ch)
    if cat in ("Nd", "No", "Nl"):
        return "digit"
    if ch == "*" or ch in KEEP_SYMBOLS:
        return "keep"
    if cat[0] in "MC":  # знаки ударения и прочие невидимые
        return "remove"
    return "space"  # знаки препинания, дефисы, скобки, кавычки, прочие символы


def _split_token(raw: str) -> Tuple[List[str], Set[str]]:
    """Делит «слово с хвостом знаков» на слова без знаков. Возвращает слова (в исходном регистре) и причины замечаний."""
    reasons: Set[str] = set()
    words: List[str] = []
    cur: List[str] = []
    for ch in unicodedata.normalize("NFC", raw):
        kind = _classify(ch)
        if kind in ("letter", "digit", "keep"):
            cur.append(ch)
            if ch.isupper():
                reasons.add("upper")
            if ch in "ёЁ":
                reasons.add("yo")
            continue
        if kind == "remove":
            if ch in ZERO_WIDTH:
                reasons.add("invisible")
            elif ch in APOSTROPHES:
                reasons.add("apostrophe")
            else:
                reasons.add("stress")
        else:
            reasons.add("hyphen" if ch in HYPHENS else "punct")
            if cur:
                words.append("".join(cur))
                cur = []
    if cur:
        words.append("".join(cur))
    return words, reasons


def _fix_mixed(word: str) -> Tuple[str, bool, bool]:
    """Слово из русских и латинских букв: латинские двойники заменяются русскими. → (слово, изменено, осталась смесь)."""
    if not (any(_is_cyr(c) for c in word) and any(_is_lat(c) for c in word)):
        return word, False, False
    fixed = "".join(LAT2CYR.get(c, c) if _is_lat(c) else c for c in word)
    return fixed, fixed != word, any(_is_lat(c) for c in fixed)


_REASON_TEXT = [
    ("upper", "заглавные буквы"),
    ("punct", "знаки препинания"),
    ("hyphen", "дефис (пишем через пробел)"),
    ("apostrophe", "апостроф"),
    ("yo", "«ё» пишем как «е»"),
    ("stress", "знак ударения"),
    ("invisible", "невидимые символы"),
    ("homoglyph", "латинские буквы внутри русского слова"),
]


def _script(word: str) -> str:
    if "*" in word:
        return "mask"
    cyr = any(_is_cyr(c) for c in word)
    lat = any(_is_lat(c) for c in word)
    digit = any(unicodedata.category(c) in ("Nd", "No", "Nl") for c in word)
    if cyr and lat:
        return "mixed"
    if digit:
        return "num"
    if lat:
        return "lat"
    if cyr:
        return "cyr"
    if any(c.isalpha() for c in word):
        return "other"
    return "sym"


@dataclass
class _Unit:
    word: str  # нормализованное слово
    tok: int  # номер токена (слова между пробелами) в исходном тексте
    first: bool  # первое слово своего токена
    last: bool  # последнее слово своего токена
    mixed: bool = False  # осталась смесь латиницы и кириллицы, которую нельзя исправить автоматически

    @property
    def script(self) -> str:
        return _script(self.word)


@dataclass
class Analysis:
    text: str
    issues: List[Issue]
    extra_rules: Tuple[Rule, ...] = ()

    @property
    def auto_issues(self) -> List[Issue]:
        return [i for i in self.issues if i.auto]

    @property
    def errors(self) -> int:
        return sum(1 for i in self.issues if i.level == ERROR)

    @property
    def warnings(self) -> int:
        return sum(1 for i in self.issues if i.level == WARN)

    @property
    def fixed(self) -> str:
        """Текст после всех безопасных исправлений (повторяется до устойчивого результата)."""
        return fix_all(self.text, self.extra_rules)


# ── замены в тексте ──────────────────────────────────────────────────────────────────────────────

def fix_all(text: str, extra_rules: Sequence[Rule] = (), passes: int = 5) -> str:
    """Применяет все безопасные исправления. Одного прохода может не хватить (после удаления знака между словами
    остаётся лишний пробел), поэтому проход повторяется, пока текст меняется."""
    for _ in range(passes):
        new = apply_auto(text, analyze(text, extra_rules).issues)
        if new == text:
            break
        text = new
    return text


def apply_auto(text: str, issues: Sequence[Issue]) -> str:
    out: List[str] = []
    pos = 0
    for i in sorted((i for i in issues if i.auto and i.suggestion is not None), key=lambda i: (i.start, i.end)):
        if i.start < pos:  # перекрытие: защитный пропуск (по построению их не бывает)
            continue
        out.append(text[pos : i.start])
        out.append(i.suggestion or "")
        pos = i.end
    out.append(text[pos:])
    return "".join(out)


def apply_issue(text: str, issue: Issue) -> str:
    """Применяет предложение одного замечания. Если фрагмент удаляется, вместе с ним уходит и один соседний пробел."""
    if issue.suggestion is None:
        return text
    start, end = issue.start, issue.end
    if issue.suggestion == "":
        m = re.match(r"\s+", text[end:])
        if m:
            end += m.end()
        elif start > 0:
            m2 = re.search(r"\s+$", text[:start])
            if m2:
                start = m2.start()
    return text[:start] + issue.suggestion + text[end:]


# ── разбор текста ────────────────────────────────────────────────────────────────────────────────

def _build_index(rules: Sequence[Rule]) -> Dict[str, List[Rule]]:
    index: Dict[str, List[Rule]] = {}
    for rule in rules:
        index.setdefault(rule.pattern[0], []).append(rule)
    for lst in index.values():
        lst.sort(key=lambda r: -len(r.pattern))  # сначала самые длинные
    return index


_DEFAULT_INDEX = _build_index(LEXICON)


def parse_extra_rules(text: str) -> Tuple[List[Rule], List[str]]:
    """Свои правила из rules_extra.txt: строка «как не надо => как надо». Строки с «#» — комментарии."""
    rules: List[Rule] = []
    problems: List[str] = []
    for no, line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("+"):  # «+ слово» — это «свои слова», их читает parse_known_words
            continue
        if "=>" not in s:
            problems.append(f"строка {no}: нет знака «=>» (нужно: как не надо => как надо)")
            continue
        left, right = s.split("=>", 1)
        pattern: List[str] = []
        for part in left.split():
            for w in _split_token(part)[0]:
                pattern.append(w.lower().replace("ё", "е"))
        replacement_words: List[str] = []
        for part in right.split():
            for w in _split_token(part)[0]:
                replacement_words.append(w.lower().replace("ё", "е"))
        if not pattern or not replacement_words:
            problems.append(f"строка {no}: слева и справа должны быть слова")
            continue
        if pattern == replacement_words:
            problems.append(f"строка {no}: слева и справа одно и то же")
            continue
        rules.append(Rule(tuple(pattern), " ".join(replacement_words), "свои правила"))
    return rules, problems


def parse_known_words(text: str) -> Set[str]:
    """«Свои слова» из rules_extra.txt: строки «+ слово». Такие слова проверка орфографии не считает ошибками."""
    words: Set[str] = set()
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if s.startswith("+"):
            for part in s[1:].split():
                for w in _split_token(part)[0]:
                    words.add(w.lower().replace("ё", "е"))
    return words


def _tokens(text: str) -> List[Tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", text)]


def analyze(text: str, extra_rules: Sequence[Rule] = ()) -> Analysis:
    if not text.strip():
        return Analysis(text, [])
    index = _DEFAULT_INDEX if not extra_rules else _build_index(list(extra_rules) + LEXICON)  # свои правила идут первыми
    tokens = _tokens(text)
    issues: List[Issue] = []

    # 1. слова-единицы: нормализованный вид каждого слова
    units: List[_Unit] = []
    tok_units: List[List[int]] = []  # для каждого токена — номера его единиц
    tok_reasons: List[Set[str]] = []
    for ti, (s, e, raw) in enumerate(tokens):
        words, reasons = _split_token(raw)
        mine: List[int] = []
        for wi, w in enumerate(words):
            fixed, changed, still_mixed = _fix_mixed(w)
            if changed:
                reasons.add("homoglyph")
            mine.append(len(units))
            units.append(_Unit(fixed.lower().replace("ё", "е"), ti, wi == 0, wi == len(words) - 1, still_mixed))
        tok_units.append(mine)
        tok_reasons.append(reasons)

    def span(a: int, b: int) -> Tuple[int, int]:
        return tokens[units[a].tok][0], tokens[units[b].tok][1]

    # 2. цепочки латиницы: 3+ слова подряд — отдельный случай инструкции (раздел 10)
    latin_runs = _runs([i for i, u in enumerate(units) if u.script == "lat"])

    # 3. слова и сочетания из таблиц. Сначала без ограничений. Затем в цепочках из 3+ слов, которые таблица
    #    покрывает не целиком, замены отменяются: такую цепочку решает человек, а не таблица.
    matches = _match_all(units, index, set())
    covered = {k for a, b, *_ in matches for k in range(a, b + 1)}
    blocked: Set[int] = {k for run in latin_runs if len(run) >= 3 and not all(x in covered for x in run) for k in run}
    if blocked:
        matches = _match_all(units, index, blocked)
    consumed: Set[int] = set()
    auto_spans: List[Tuple[int, int]] = []
    for a, b, replacement, section, note, foreign in matches:
        s, e = span(a, b)
        if text[s:e] != replacement:
            msg = f"По инструкции пишем «{replacement}»" + (f": {note}" if note else "")
            if foreign:
                msg += f". Иностранное слово: отметьте галочку {FOREIGN_CHECKBOX}"
            issues.append(Issue(s, e, ERROR, "lexicon", msg, _sec(section), replacement, True))
            auto_spans.append((s, e))
        consumed.update(range(a, b + 1))

    # 4. механические исправления в остальных токенах
    consumed_tokens = {units[k].tok for k in consumed}
    for ti, (s, e, raw) in enumerate(tokens):
        if ti in consumed_tokens:
            continue
        if not tok_units[ti]:
            a, b = _swallow(text, s, e, auto_spans)
            issues.append(Issue(a, b, ERROR, "format", "Знак препинания без слов: не ставим", _sec("1"), "", True))
            auto_spans.append((a, b))
            continue
        suggestion = " ".join(units[k].word for k in tok_units[ti])
        if suggestion != raw:
            parts = [t for key, t in _REASON_TEXT if key in tok_reasons[ti]]
            msg = ("Лишнее: " + ", ".join(parts)) if parts else f"Скрытое различие в символах. Нужно: «{suggestion}»"
            issues.append(Issue(s, e, ERROR, "format", msg, _sec("1"), suggestion, True))
            auto_spans.append((s, e))

    # 5. пробелы между словами (внутри уже заменяемых фрагментов не трогаем: там пробелы заменятся вместе с ними)
    for m in re.finditer(r"\s+", text):
        s, e = m.span()
        if any(a <= s and e <= b for a, b in auto_spans):
            continue
        run = m.group()
        if s == 0 or e == len(text):
            issues.append(Issue(s, e, ERROR, "whitespace", "Пробелы или перенос строки по краям текста", _sec("1"), "", True))
        elif run != " ":
            what = "Перенос строки: текст пишется в одну строку" if re.search(r"[\r\n]", run) else "Лишние пробелы"
            issues.append(Issue(s, e, ERROR, "whitespace", what, _sec("1"), " ", True))

    # 6. проверки, которые решает человек
    live = [k for k in range(len(units)) if k not in consumed]
    issues.extend(_manual_checks(units, tok_units, live, latin_runs, span))

    issues.sort(key=lambda x: (x.start, _LEVEL_RANK[x.level], x.end))
    return Analysis(text, issues, tuple(extra_rules))


def _swallow(text: str, s: int, e: int, taken: Sequence[Tuple[int, int]]) -> Tuple[int, int]:
    """При удалении фрагмента забираем один соседний пробел, чтобы не остался двойной."""
    m = re.match(r"\s+", text[e:])
    if m:
        return s, e + m.end()
    m2 = re.search(r"\s+$", text[:s])
    if m2 and not any(a < s and m2.start() < b for a, b in taken):
        return m2.start(), e
    return s, e


def _sec(section: str) -> str:
    return f"разд. {section}" if section and section[0].isdigit() else section


def _runs(indexes: Sequence[int]) -> List[List[int]]:
    runs: List[List[int]] = []
    for k in indexes:
        if runs and runs[-1][-1] == k - 1:
            runs[-1].append(k)
        else:
            runs.append([k])
    return runs


def _match_all(units: List[_Unit], index: Dict[str, List[Rule]], blocked: Set[int]) -> List[Tuple[int, int, str, str, str, bool]]:
    """Все непересекающиеся замены слева направо: (первая единица, последняя единица, замена, раздел, пояснение, иностранное)."""
    out: List[Tuple[int, int, str, str, str, bool]] = []
    i = 0
    while i < len(units):
        m = None if i in blocked else _match_at(units, i, index, blocked)
        if m is None:
            i += 1
            continue
        out.append((i, *m))
        i = m[0] + 1
    return out


def _match_at(
    units: List[_Unit], i: int, index: Dict[str, List[Rule]], blocked: Set[int]
) -> Optional[Tuple[int, str, str, str, bool]]:
    """Ищет правило, начинающееся на слове i. → (последняя единица, замена, раздел, пояснение, иностранное)."""
    if not units[i].first:
        return None
    for rule in index.get(units[i].word, ()):
        n = len(rule.pattern)
        j = i + n - 1
        if j >= len(units) or not units[j].last:
            continue
        if any(units[i + k].word != rule.pattern[k] or (i + k) in blocked for k in range(n)):
            continue
        return j, rule.replacement, rule.section, rule.note, rule.foreign
    w = units[i].word
    if units[i].last:
        for pat, repl, section, note in REGEX_RULES:
            m = pat.match(w)
            if m:
                new = m.expand(repl)
                if new != w:
                    return i, new, section, note, False
    if i + 1 < len(units) and units[i + 1].last and (i + 1) not in blocked:
        w2 = units[i + 1].word
        for first, second_prefix, section in JOIN_RULES:
            if w == first and w2.startswith(second_prefix):
                return i + 1, first + w2, section, "составное слово пишется слитно", False
    return None


def _manual_checks(units, tok_units, live, latin_runs, span) -> List[Issue]:  # type: ignore[no-untyped-def]
    out: List[Issue] = []
    live_set = set(live)

    def issue(a: int, b: int, level: str, code: str, msg: str, section: str, suggestion: Optional[str] = None) -> None:
        s, e = span(a, b)
        out.append(Issue(s, e, level, code, msg, _sec(section), suggestion, False))

    # звёздочки вместо мата (раздел 15)
    for k in live:
        if units[k].script == "mask":
            issue(k, k, ERROR, "mask", "Мат пишется полностью, без звёздочек", "15")

    # смесь латиницы и кириллицы, которую нельзя исправить заменой двойников
    for k in live:
        if units[k].mixed:
            issue(k, k, ERROR, "mixed", "В слове смешаны русские и латинские буквы. Запишите слово русскими буквами", "10")

    # латиница (раздел 10)
    for run in latin_runs:
        run_live = [k for k in run if k in live_set]
        if not run_live:
            continue
        words = [units[k].word for k in run]
        if len(run) >= 3 and not _is_repeat(words):
            issue(
                run[0], run[-1], ERROR, "latin_phrase",
                "3 и больше английских слова подряд. Если это фраза или строчка песни: поле остаётся пустым и ставится отметка "
                f"{UNTRANSCRIBABLE_MARK}. Если это название (компания, песня, игра): пишите русскими буквами и ставьте галочку {FOREIGN_CHECKBOX}",
                "10",
            )
        elif len(run) >= 3:
            issue(
                run_live[0], run_live[-1], ERROR, "latin",
                f"Повтор короткой вставки: пишем все повторы русскими буквами и ставим галочку {FOREIGN_CHECKBOX}", "10",
            )
        else:
            for sub in _runs(run_live):
                issue(
                    sub[0], sub[-1], ERROR, "latin",
                    f"Английские слова пишутся русскими буквами. Не забудьте галочку {FOREIGN_CHECKBOX}", "10",
                )

    # числа и символы словами (раздел 9): подряд идущие токены объединяются в одно замечание
    num_tokens: List[int] = []
    for k in live:
        if units[k].script in ("num", "sym"):
            ti = units[k].tok
            if not num_tokens or num_tokens[-1] != ti:
                num_tokens.append(ti)
    for group in _consecutive(num_tokens):
        parts: List[str] = []
        ok = True
        for ti in group:
            for k in tok_units[ti]:
                if k in live_set and units[k].script in ("num", "sym"):
                    spelled = spell_numeric_token(units[k].word)
                    if spelled is None:
                        ok = False
                    parts.append(spelled or units[k].word)
                else:
                    parts.append(units[k].word)
        first_u, last_u = tok_units[group[0]][0], tok_units[group[-1]][-1]
        if ok:
            issue(first_u, last_u, ERROR, "number",
                  "Числа пишутся словами. Предложение в именительном падеже: проверьте падеж и род по смыслу", "9", " ".join(parts))
        else:
            issue(first_u, last_u, ERROR, "number", "Цифры и символы пишутся словами", "9")

    # буквы не русского и не английского алфавита
    for k in live:
        if units[k].script == "other":
            issue(k, k, WARN, "other", f"Буквы другого алфавита. Если речь не на русском: поле пустое и отметка {UNTRANSCRIBABLE_MARK}", "отметка")

    # слова-подсказки из шпаргалки, которые бывают верными
    for k in live:
        hint = CHECK_WORDS.get(units[k].word)
        if hint:
            issue(k, k, WARN, "check_word", hint[1], "шпаргалка", hint[0])

    # смех, звуки-паразиты, распевы (разделы 7, 13, 14)
    cyr_live = [k for k in live if units[k].script == "cyr"]
    for run in _runs([k for k in cyr_live if _LAUGH_RE.match(units[k].word)]):
        issue(run[0], run[-1], WARN, "laugh", "Смех не записывается. Если это слово («ха», «хи» как междометие), оставьте", "14", "")
    for k in cyr_live:
        w = units[k].word
        if _PARASITE_RE.match(w):
            issue(k, k, WARN, "parasite", "Звуки-паразиты («эээ», «ммм») не записываются", "7", "")
    chant = [k for k in cyr_live if units[k].word in _CHANT]
    for run in _runs(chant):
        if len(run) >= 2:
            issue(run[0], run[-1], WARN, "chant", "Распевы без слов («ла-ла-ла», «оу-оу») не записываются", "13", "")
    for k in cyr_live:
        if _CHANT_LONG_RE.match(units[k].word):
            issue(k, k, WARN, "chant", "Распевы без слов («ооо») не записываются", "13", "")

    # заикание: повтор слога не пишется (раздел 5d)
    done: Set[int] = set()
    for n, k in enumerate(cyr_live):
        if k in done or n + 1 >= len(cyr_live):
            continue
        w = units[k].word
        # цепочка одинаковых фрагментов подряд
        m = n
        while m + 1 < len(cyr_live) and cyr_live[m + 1] == cyr_live[m] + 1 and units[cyr_live[m + 1]].word == w:
            m += 1
        nxt = m + 1
        if nxt >= len(cyr_live) or cyr_live[nxt] != cyr_live[m] + 1:
            continue
        target = units[cyr_live[nxt]].word
        if not (target.startswith(w) and len(target) > len(w)):
            continue
        repeated = m > n
        one_syllable = sum(1 for c in w if c in _VOWELS) == 1
        if repeated or (len(w) >= 2 and one_syllable and w not in _SHORT_WORDS):
            a, b = cyr_live[n], cyr_live[m]
            issue(a, b, WARN, "stutter",
                  "Возможное заикание: повтор одного слога не записывается. Если человек сказал слово целиком, оставьте", "5", "")
            done.update(range(a, b + 1))
    return out


def _is_repeat(words: Sequence[str]) -> bool:
    """Одно или два слова, повторённые подряд («lets go lets go»): по инструкции это повторы, а не фраза."""
    for period in (1, 2):
        if len(words) % period == 0 and len(words) // period >= 2 and list(words) == list(words[:period]) * (len(words) // period):
            return True
    return False


def _consecutive(values: Sequence[int]) -> List[List[int]]:
    groups: List[List[int]] = []
    for v in values:
        if groups and groups[-1][-1] == v - 1:
            groups[-1].append(v)
        else:
            groups.append([v])
    return groups
