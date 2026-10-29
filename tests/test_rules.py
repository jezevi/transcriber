"""Проверка ядра правил. Основа — примеры «Неправильно → Правильно» из инструкции (версия от 28.10.2026).
Примеры в комментариях: «разд. N» — номер раздела инструкции."""
import random
import unittest

from transcheck import rules_ru as R
from transcheck.rules_ru import ERROR, WARN, analyze, apply_issue, fix_all, parse_extra_rules


def codes(text, **kw):
    return [i.code for i in analyze(text, **kw).issues]


def one(text, code):
    found = [i for i in analyze(text).issues if i.code == code]
    assert len(found) == 1, (text, code, analyze(text).issues)
    return found[0]


class CleanText(unittest.TestCase):
    """Правильные примеры из инструкции не должны получать замечаний."""

    def test_correct_examples_have_no_issues(self):
        good = [
            "позвони по номеру плюс семь девятьсот сто двадцать три сорок пять шестьдесят семь",  # разд. 9
            "какая погода в субботу в твери",  # разд. 3
            "есть ли дождь в москве",  # разд. 6
            "номер карты эт самое два три пять",  # разд. 7
            "номер карты два три пять",
            "позвони александре василькова васильевой",  # разд. 5a
            "я пошел гулять",  # разд. 5d
            "я сказал",
            "поехали в мос а нет нет в калугу",  # разд. 5b: «мос» — обрыв слова, пишется
            "улица респуб республики",  # разд. 5b: обрыв слова из двух слогов пишется
            "ського вокзала уходит поезд",
            "мы уже все спланиро",
            "ипотеке да процент по ипотеке",  # разд. 5c
            "карты сбербанк сделать",  # разд. 4
            "ихний евоный нашлася пасиб ща че ниче",  # разд. 4: так и слышим
            "красивый девушка",  # разд. 4
            "мтс ндфл снилс смску в смске дкп кп",  # разд. 2
            "а б в г д е",  # разд. 2: случайный набор букв
            "екарный бабай тыры пыры",
            "скажите мне баланс",
            "сберпэй сбербизнес сберонлайн сбер айди гугл плэй кюар код",  # разд. 10–11
            "маткапитал допсоглашение физлицо юрлицо корсчет юрпроверка",  # разд. 12
            "монитор самсунг фулл эйчди",
            "компания мс интермарк авто каско",
            "ну короче он такой окей ноу проблем",
            "я начинаю шоу тайм ран ран ран",  # разд. 13: после перевода в кириллицу
            "господи помилуй господи помилуй господи помилуй",  # повторы слов — не заикание
            "вышел блять на бульвар",  # разд. 15
            "пошел нахуй",
            "ебаный насос",
            "на держи",  # разд. 13: «на» — слово, не распев
            "на на ешь",
            "ой ой ой",
            "зе намбэр из нот эвэйлэбл",
            "ну прям пару сек",
            "тысяча пятьдесят",
            "алло",
        ]
        for text in good:
            with self.subTest(text=text):
                self.assertEqual(analyze(text).issues, [], text)

    def test_empty_and_blank(self):
        self.assertEqual(analyze("").issues, [])
        self.assertEqual(analyze("   \n\t ").issues, [])


class Mechanical(unittest.TestCase):
    def test_case_punctuation_yo(self):  # разд. 1
        self.assertEqual(fix_all("Привет, Мир! Это тест — ёжик."), "привет мир это тест ежик")
        self.assertEqual(fix_all("«Привет»... (да?) нет; ладно: хорошо"), "привет да нет ладно хорошо")

    def test_hyphen_becomes_space(self):  # разд. 1 и шпаргалка («че то», «че нибудь»)
        self.assertEqual(fix_all("че-то по-русски"), "че то по русски")
        self.assertEqual(fix_all("есть ли дождь в гав-гав москве"), "есть ли дождь в гав гав москве")

    def test_missing_space_after_punctuation(self):
        self.assertEqual(fix_all("привет,как дела?да"), "привет как дела да")

    def test_whitespace(self):
        self.assertEqual(fix_all("  привет   мир \n"), "привет мир")
        self.assertEqual(fix_all("привет\nмир"), "привет мир")
        self.assertEqual(fix_all("привет мир"), "привет мир")

    def test_invisible_characters_and_stress_marks(self):
        self.assertEqual(fix_all("при​вет"), "привет")
        self.assertEqual(fix_all("приве́т"), "привет")

    def test_decomposed_i_kratkoe_survives(self):
        decomposed = "мо" + "и\u0306"  # «й» из двух символов
        self.assertEqual(fix_all(decomposed), "мой")  # собирается в обычную «й», а не теряет «и» или значок

    def test_lone_dash_and_dots_are_removed_without_double_space(self):
        self.assertEqual(fix_all("привет — мир"), "привет мир")
        self.assertEqual(fix_all("привет ... мир"), "привет мир")
        self.assertEqual(fix_all("— привет"), "привет")
        self.assertEqual(fix_all("привет —"), "привет")
        self.assertEqual(fix_all(" — аб — — "), "аб")

    def test_latin_lookalike_letters_inside_russian_word(self):
        word = "пpивет"  # латинская p
        self.assertEqual(fix_all(word), "привет")
        self.assertEqual(fix_all("Привeт Mир"), "привет мир")  # латинские e и M
        a = analyze(word)
        self.assertTrue(a.issues[0].auto)
        self.assertIn("латинские буквы", a.issues[0].message)

    def test_unfixable_mixed_script(self):
        a = analyze("приvет")
        self.assertEqual([i.code for i in a.issues], ["mixed"])
        self.assertFalse(a.issues[0].auto)


class Lexicon(unittest.TestCase):
    def test_abbreviations(self):  # разд. 2
        self.assertEqual(fix_all("позвони в эмтээс по эндэфээл и снилса"), "позвони в мтс по ндфл и снилс")
        self.assertEqual(fix_all("оформим кпэшка"), "оформим кп")

    def test_slang_table(self):  # шпаргалка и разд. 4
        pairs = {
            "щас приду": "сейчас приду",
            "ниче се": "ниче себе",
            "алё это я": "алло это я",
            "Алё, это я": "алло это я",
            "наверно так": "наверное так",
            "риэлтор и риелтер": "риелтор и риелтор",
            "типо того": "типа того",
            "кешбек и кешбэк": "кэшбэк и кэшбэк",
            "пидиэф и хмл": "пдф и иксмл",
            "в доме клике": "в домклике",
            "писят": "пятьдесят",
        }
        for src, want in pairs.items():
            with self.subTest(src=src):
                self.assertEqual(fix_all(src), want)

    def test_tyshcha(self):  # разд. 4: «тыщ» — «тысяч»; числительные пишем правильно
        self.assertEqual(fix_all("три тыщ рублей"), "три тысяч рублей")
        self.assertEqual(fix_all("тыща рублей"), "тысяча рублей")
        self.assertEqual(fix_all("две тыщи"), "две тысячи")

    def test_oye(self):  # разд. 7: «ойеееей» — «ой ой ой»
        self.assertEqual(fix_all("ойеееей что это"), "ой ой ой что это")

    def test_sber_words(self):  # разд. 10–11
        self.assertEqual(fix_all("сбер ай ди, сбер пэй, гуглплэй, кю ар код"), "сбер айди сберпэй гугл плэй кюар код")
        for a, b in {
            "сбер бизнес": "сбербизнес", "сбер кидс": "сберкидс", "сбер купон": "сберкупон", "сбер страхование": "сберстрахование",
            "сбер авто": "сберавто", "сбер мобайл": "сбермобайл", "сбер прайм": "сберпрайм", "сбер маркет": "сбермаркет",
            "сбер спасибо": "сберспасибо", "сбер онлайн": "сберонлайн", "сберконтактмониторинг": "сберконтакт мониторинг",
        }.items():
            with self.subTest(a=a):
                self.assertEqual(fix_all(a), b)

    def test_sber_alone_and_assistant_names_untouched(self):
        self.assertEqual(analyze("сбер включи свет салют джой").issues, [])

    def test_compound_words(self):  # разд. 12
        pairs = {
            "мат капитал": "маткапитал", "доп соглашение": "допсоглашение", "физ лицо": "физлицо", "юр лицо": "юрлицо",
            "кор счет": "корсчет", "юр проверка": "юрпроверка", "физ лица": "физлица", "кор счета": "корсчета",
        }
        for a, b in pairs.items():
            with self.subTest(a=a):
                self.assertEqual(fix_all(a), b)

    def test_mat_table(self):  # разд. 15
        self.assertEqual(fix_all("вышел блядь на бульвар"), "вышел блять на бульвар")
        self.assertEqual(fix_all("пошел на хуй"), "пошел нахуй")
        self.assertEqual(fix_all("ёбаный насос"), "ебаный насос")
        self.assertEqual(fix_all("ебанный насос"), "ебаный насос")
        self.assertEqual(fix_all("ахуенно"), "охуенно")

    def test_mat_mask_is_flagged_not_changed(self):  # разд. 15
        for text in ("вышел бл*** на бульвар", "ну ***"):
            a = analyze(text)
            self.assertEqual([i.code for i in a.issues], ["mask"], text)
            self.assertFalse(a.issues[0].auto)
            self.assertEqual(a.fixed, text)

    def test_latin_table_words_replaced(self):  # шпаргалка и разд. 10
        pairs = {
            "отменить подписку на youtube": "отменить подписку на ютуб",
            "монитор samsung full hd": "монитор самсунг фулл эйчди",
            "компания mc intermark auto каско": "компания мс интермарк авто каско",
            "jpeg и pdf": "джипег и пдф",
            "usb и nfc": "юсб и энэфси",
            "the": "зе",
            "tele2 и 2gis": "теле два и два гис",
            "minecraft minecraft я играю в minecraft моя жизнь": "майнкрафт майнкрафт я играю в майнкрафт моя жизнь",
            "ok": "окей",
            "Okay": "окей",
        }
        for src, want in pairs.items():
            with self.subTest(src=src):
                self.assertEqual(fix_all(src), want)

    def test_foreign_word_reminder_is_in_message(self):
        a = analyze("отменить подписку на youtube")
        self.assertIn("иностранные слова", a.issues[0].message)

    def test_check_words_are_only_warnings(self):  # шпаргалка: «тока, ток» — не всегда ошибка
        for text in ("я тока пришел", "электрический ток"):
            a = analyze(text)
            self.assertEqual([i.code for i in a.issues], ["check_word"], text)
            self.assertFalse(a.issues[0].auto)
            self.assertEqual(a.issues[0].level, WARN)
            self.assertEqual(a.fixed, text)
        self.assertEqual(apply_issue("я тока пришел", analyze("я тока пришел").issues[0]), "я только пришел")


class Latin(unittest.TestCase):
    def test_short_run_is_asked_for_cyrillic(self):  # разд. 10
        a = analyze("поставь на repeat")
        i = one("поставь на repeat", "latin")
        self.assertEqual(a.issues[0].level, ERROR)
        self.assertIn("иностранные слова", i.message)
        self.assertFalse(i.auto)

    def test_three_words_are_a_phrase(self):  # разд. 10: строчка песни — отметка «невозможно транскрибировать»
        for text in (
            "закрой глаза give me what I need pull me in so deep я хочу чтобы ты была счастливой",
            "here in the group everything but jack",
            "the first way to access GPT is to literally search GPT dot com",
        ):
            with self.subTest(text=text):
                i = one(text, "latin_phrase")
                self.assertIn("невозможно транскрибировать", i.message)
                self.assertFalse(i.auto)

    def test_phrase_is_not_partially_replaced_by_the_table(self):
        a = analyze("the number is not available")
        self.assertEqual([i.code for i in a.issues], ["latin_phrase"])
        self.assertEqual(a.fixed, "the number is not available")

    def test_repeated_short_insertion_is_not_a_phrase(self):  # разд. 10: «летс гоу летс гоу» — повторы
        i = one("let's go let's go о да ну вот опять расенган подвел", "latin")
        self.assertIn("Повтор", i.message)

    def test_names_of_any_length_covered_by_table_are_ok(self):
        self.assertEqual([i.code for i in analyze("компания mc intermark auto каско").issues], ["lexicon"])

    def test_apostrophe_is_removed_inside_latin(self):  # английские сокращения без апострофа
        self.assertEqual(fix_all("it's"), "its")

    def test_other_alphabets(self):
        i = one("привет 你好", "other")
        self.assertEqual(i.level, WARN)


class Numbers(unittest.TestCase):
    def test_phone_example_from_instruction(self):  # разд. 9
        i = one("позвони по номеру +7 900 123 45 67", "number")
        self.assertEqual(i.suggestion, "плюс семь девятьсот сто двадцать три сорок пять шестьдесят семь")
        self.assertFalse(i.auto)
        self.assertEqual(
            apply_issue("позвони по номеру +7 900 123 45 67", i),
            "позвони по номеру плюс семь девятьсот сто двадцать три сорок пять шестьдесят семь",
        )

    def test_single_number_with_punctuation(self):
        text = "мне 25, а ему 30."
        issues = [i for i in analyze(text).issues if i.code == "number"]
        self.assertEqual([i.suggestion for i in issues], ["двадцать пять", "тридцать"])
        self.assertEqual(apply_issue(text, issues[0]), "мне двадцать пять а ему 30.")
        self.assertEqual(apply_issue(text, issues[1]), "мне 25, а ему тридцать")

    def test_digits_inside_words_have_no_suggestion(self):
        i = one("у меня 5g", "number")
        self.assertIsNone(i.suggestion)
        i = one("номер 007", "number")
        self.assertIsNone(i.suggestion)

    def test_number_with_ending_keeps_the_ending(self):
        i = one("в 12-м часу", "number")
        self.assertEqual(i.suggestion, "двенадцать м")  # окончание остаётся отдельным словом: человек правит сам

    def test_symbols(self):
        self.assertIsNone(one("скидка 50%", "number").suggestion)
        self.assertEqual(one("плюс + два", "number").suggestion, "плюс")

    def test_numbers_are_never_auto(self):
        for text in ("1 2 3", "в 2026 году", "+7 900"):
            self.assertEqual(analyze(text).fixed, text)


class SoundsAndStutter(unittest.TestCase):
    def test_laughter_is_flagged_and_removed_on_request(self):  # разд. 14
        text = "я последний раз сидел ха ха ха ну в общем вышел"
        i = one(text, "laugh")
        self.assertEqual(text[i.start : i.end], "ха ха ха")
        self.assertEqual(apply_issue(text, i), "я последний раз сидел ну в общем вышел")  # ровно как в инструкции
        self.assertEqual(analyze(text).fixed, text)  # автоматически не удаляется

    def test_laughter_variants(self):
        for w in ("хаха", "ахаха", "хихи", "хехе", "хохо", "ха-ха-ха"):
            with self.subTest(w=w):
                self.assertIn("laugh", codes(f"ну {w} ладно"))

    def test_words_that_look_like_laughter_are_not_flagged(self):
        for w in ("ухо", "муха", "хата", "хорошо", "ахи"):
            with self.subTest(w=w):
                self.assertNotIn("laugh", codes(f"ну {w} ладно"))

    def test_parasite_sounds(self):  # разд. 7
        for text in ("номер карты эммммм два три пять", "ну эээ да", "ммм ладно"):
            with self.subTest(text=text):
                self.assertIn("parasite", codes(text))
        i = one("номер карты эммммм два три пять", "parasite")
        self.assertEqual(apply_issue("номер карты эммммм два три пять", i), "номер карты два три пять")

    def test_words_are_not_parasites(self):  # «эт самое», «эх», «угу» записываются
        for text in ("эт самое два", "эх жаль", "угу", "ага", "ну", "ой"):
            self.assertNotIn("parasite", codes(text), text)

    def test_chant(self):  # разд. 13
        i = one("певица тянет ла ла ла ла ла ла", "chant")
        self.assertEqual(i.suggestion, "")
        self.assertIn("chant", codes("оу оу оу"))
        self.assertIn("chant", codes("ну ооо да"))

    def test_chant_needs_two_in_a_row(self):
        self.assertNotIn("chant", codes("ну ла да"))

    def test_stutter_examples_from_instruction(self):  # разд. 5d
        text = "я по по по пошел гулять"
        i = one(text, "stutter")
        self.assertEqual(apply_issue(text, i), "я пошел гулять")
        text = "я ска сказал"
        i = one(text, "stutter")
        self.assertEqual(apply_issue(text, i), "я сказал")

    def test_whole_word_repeats_are_not_stutter(self):  # повторы слов пишутся
        for text in ("нет нет нет", "майнкрафт майнкрафт", "господи помилуй господи помилуй", "по полю", "под подарок"):
            self.assertNotIn("stutter", codes(text), text)

    def test_stutter_is_never_auto(self):
        text = "я по по по пошел гулять"
        self.assertEqual(analyze(text).fixed, text)


class Whitespace(unittest.TestCase):
    def test_messages_and_autos(self):
        a = analyze("привет  мир")
        self.assertEqual([i.code for i in a.issues], ["whitespace"])
        self.assertTrue(a.issues[0].auto)
        a = analyze("привет\nмир")
        self.assertIn("Перенос строки", a.issues[0].message)


class ExtraRules(unittest.TestCase):
    def test_parse(self):
        rules, problems = parse_extra_rules(
            "# комментарий\n\nсинхронизация => синхронизация\nпо тихому => потихому\nкак-то так => както так\nбез стрелки\n=> х\nа => а\n"
        )
        self.assertEqual([(r.pattern, r.replacement) for r in rules], [(("по", "тихому"), "потихому"), (("как", "то", "так"), "както так")])
        self.assertEqual(len(problems), 4)
        self.assertTrue(any("строка 6" in p for p in problems))

    def test_extra_rules_apply_and_win_over_builtin(self):
        rules, _ = parse_extra_rules("по тихому => потихому\nщас => сей час\n")
        self.assertEqual(fix_all("Щас иду по тихому", rules), "сей час иду потихому")
        self.assertEqual(fix_all("щас"), "сейчас")  # без своих правил — встроенное

    def test_extra_rules_message(self):
        rules, _ = parse_extra_rules("по тихому => потихому\n")
        self.assertEqual(analyze("по тихому", rules).issues[0].section, "свои правила")


class Structure(unittest.TestCase):
    def test_spans_point_to_the_problem(self):
        text = "привет, Мир"
        for i in analyze(text).issues:
            self.assertTrue(0 <= i.start < i.end <= len(text))
        self.assertEqual([text[i.start : i.end] for i in analyze(text).issues], ["привет,", "Мир"])

    def test_issues_are_sorted(self):
        a = analyze("Привет 25 мир, ха ха")
        self.assertEqual([i.start for i in a.issues], sorted(i.start for i in a.issues))

    def test_counts(self):
        a = analyze("Привет, 25 ха ха")
        self.assertEqual(a.errors, sum(1 for i in a.issues if i.level == ERROR))
        self.assertEqual(a.warnings, sum(1 for i in a.issues if i.level == WARN))
        self.assertTrue(a.errors >= 2 and a.warnings >= 1)

    def test_apply_issue_removal_takes_one_neighbour_space(self):
        text = "а ха ха б"
        i = one(text, "laugh")
        self.assertEqual(apply_issue(text, i), "а б")
        text = "а ха ха"
        self.assertEqual(apply_issue(text, one(text, "laugh")), "а")

    def test_apply_issue_without_suggestion_changes_nothing(self):
        text = "вышел бл*** на бульвар"
        self.assertEqual(apply_issue(text, analyze(text).issues[0]), text)


class Robustness(unittest.TestCase):
    ALPHABET = list("абвгдеёжзийклмнопрстуфхцчшщъыьэюя") + list("ABCabcxyzopeHK") + list("ХАРТ") + list(
        "0123456789+%№ -—–.,!?;:'\"«»()*…\n\t ​́"
    )
    SNIPPETS = [
        "щас", "сбер", "пэй", "ха", "по", "ска", "сказал", "ok", "the", "мат", "капитал", "на", "хуй", "блядь", "алё", "тыща", "ойеееей",
        "full", "hd", "samsung", "эмм", "ла", "ла", "ток", "Привет,", "ёж", "25", "+7", "бл***", "—",
    ]

    def _random_text(self, rng):
        parts = []
        for _ in range(rng.randint(0, 14)):
            if rng.random() < 0.6:
                parts.append(rng.choice(self.SNIPPETS))
            else:
                parts.append("".join(rng.choice(self.ALPHABET) for _ in range(rng.randint(1, 8))))
            parts.append(rng.choice([" ", " ", " ", "  ", "\n", ""]))
        return "".join(parts)

    def test_fix_is_stable_and_leaves_no_auto_issues(self):
        rng = random.Random(20261028)
        for n in range(1500):
            text = self._random_text(rng)
            fixed = fix_all(text)
            with self.subTest(n=n, text=text):
                again = analyze(fixed)
                self.assertEqual([i for i in again.issues if i.auto], [], repr(fixed))
                self.assertEqual(fix_all(fixed), fixed)

    def test_auto_issues_never_overlap_and_spans_are_valid(self):
        rng = random.Random(7)
        for n in range(1500):
            text = self._random_text(rng)
            a = analyze(text)
            autos = sorted(a.auto_issues, key=lambda i: i.start)
            for i in a.issues:
                self.assertTrue(0 <= i.start <= i.end <= len(text), (text, i))
            for left, right in zip(autos, autos[1:]):
                self.assertLessEqual(left.end, right.start, (text, left, right))

    def test_fix_never_adds_forbidden_characters(self):
        rng = random.Random(99)
        forbidden = set(".,!?;:\"«»()…—–") | set("ЁёABCEHKMOPTXY") | set("\n\t ​")
        for n in range(1500):
            text = self._random_text(rng)
            fixed = fix_all(text)
            self.assertFalse(forbidden & set(fixed), (text, fixed))
            self.assertEqual(fixed, fixed.strip())
            self.assertNotIn("  ", fixed)

    def test_every_lexicon_replacement_is_final(self):
        # замена не должна сама попадать под правило: иначе исправление не было бы устойчивым
        for rule in R.LEXICON:
            with self.subTest(rule=rule.pattern):
                a = analyze(rule.replacement)
                self.assertEqual([i for i in a.issues if i.auto], [], rule)

    def test_text_without_changes_keeps_identity(self):
        text = "это уже правильный текст"
        self.assertEqual(analyze(text).fixed, text)

    def test_long_text_is_fast(self):
        import time

        text = ("Привет, Мир! сбер пэй 25 ха ха " * 400)[:5000]
        t0 = time.perf_counter()
        analyze(text)
        self.assertLess(time.perf_counter() - t0, 1.0)


if __name__ == "__main__":
    unittest.main()
