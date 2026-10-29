import ctypes
import os
import sys
import tempfile
import unittest

from transcheck import rules_ru as R
from transcheck import spell

from .helpers import FakeSpeller, russian_speller

# ── поддельный COM: проверяем наш обмен с интерфейсами через ctypes (порядок методов, типы параметров, освобождение строк) ──

FT = spell._FUNCTYPE
_KEEP: list = []  # поддельные объекты должны жить, пока идёт тест


def make_object(methods):
    """COM-объект: указатель на указатель на таблицу методов. methods: номер метода → функция."""
    table = (ctypes.c_void_p * 24)()
    for index, fn in methods.items():
        table[index] = ctypes.cast(fn, ctypes.c_void_p).value
    head = ctypes.c_void_p(ctypes.addressof(table))
    _KEEP.append((table, head, methods))
    return ctypes.addressof(head)


RELEASE = FT(ctypes.c_uint32, ctypes.c_void_p)(lambda this: 0)
P = ctypes.c_void_p
PP = ctypes.POINTER(ctypes.c_void_p)


def wide(text):
    buf = ctypes.create_unicode_buffer(text)
    _KEEP.append(buf)
    return ctypes.addressof(buf)


class FakeChecker:
    """Поддельный ISpellChecker: слова из набора верны, «москва» словарь предлагает исправить на «Москва» (только регистр)."""

    def __init__(self, words=("привет", "мир"), proper=None, suggestions=None, fail_check=False):
        self.words, self.proper = set(words), proper or {"москва": "Москва"}
        self.suggestions = suggestions or {"казел": ["козёл", "казан", "казнь"]}
        self.fail_check = fail_check
        self.freed = []
        self.pointer = make_object({
            2: RELEASE,
            4: FT(ctypes.c_int32, P, ctypes.c_wchar_p, PP)(self._check),
            5: FT(ctypes.c_int32, P, ctypes.c_wchar_p, PP)(self._suggest),
        })

    def free(self, pointer):
        self.freed.append(pointer)

    def _check(self, this, text, out):
        if self.fail_check:
            return ctypes.c_int32(0x80004005).value  # E_FAIL
        found, pos = [], 0
        for word in text.split():
            start = text.index(word, pos)
            pos = start + len(word)
            low = word.lower()
            if low in self.words:
                continue
            if low in self.proper:
                found.append((start, len(word), 2, self.proper[low]))
            else:
                found.append((start, len(word), 1, ""))
        state = {"i": 0}

        def error_object(item):
            start, length, action, replacement = item
            return make_object({
                2: RELEASE,
                3: FT(ctypes.c_int32, P, ctypes.POINTER(ctypes.c_uint32))(lambda this, o: (o.__setitem__(0, start), 0)[1]),
                4: FT(ctypes.c_int32, P, ctypes.POINTER(ctypes.c_uint32))(lambda this, o: (o.__setitem__(0, length), 0)[1]),
                5: FT(ctypes.c_int32, P, ctypes.POINTER(ctypes.c_int32))(lambda this, o: (o.__setitem__(0, action), 0)[1]),
                6: FT(ctypes.c_int32, P, PP)(lambda this, o: (o.__setitem__(0, wide(replacement) if replacement else None), 0)[1]),
            })

        def next_error(this, o):
            if state["i"] >= len(found):
                o[0] = None
                return 1  # S_FALSE
            o[0] = error_object(found[state["i"]])
            state["i"] += 1
            return 0

        out[0] = make_object({2: RELEASE, 3: FT(ctypes.c_int32, P, PP)(next_error)})
        return 0

    def _suggest(self, this, word, out):
        items = self.suggestions.get(word.lower(), [])
        state = {"i": 0}

        def next_string(this, celt, rgelt, fetched):
            if state["i"] >= len(items):
                fetched[0] = 0
                return 1
            rgelt[0] = wide(items[state["i"]])
            state["i"] += 1
            fetched[0] = 1
            return 0

        out[0] = make_object({2: RELEASE, 3: FT(ctypes.c_int32, P, ctypes.c_uint32, PP, ctypes.POINTER(ctypes.c_uint32))(next_string)})
        return 0


class ComLayer(unittest.TestCase):
    def make(self, **kw):
        fake = FakeChecker(**kw)
        return fake, spell.ComSpeller(fake.pointer, free=fake.free)

    def test_check_reads_errors(self):
        fake, sp = self.make()
        self.assertEqual(sp.check("привет казел москва"), [(7, 5, 1, ""), (13, 6, 2, "Москва")])
        self.assertEqual(len(fake.freed), 1)  # строку замены освободили

    def test_check_without_errors(self):
        _, sp = self.make()
        self.assertEqual(sp.check("привет мир"), [])

    def test_suggest_reads_strings(self):
        fake, sp = self.make()
        self.assertEqual(sp.suggest("казел"), ["козёл", "казан", "казнь"])
        self.assertEqual(len(fake.freed), 3)
        self.assertEqual(sp.suggest("казел", limit=2), ["козёл", "казан"])
        self.assertEqual(sp.suggest("неведомо"), [])

    def test_is_correct(self):
        _, sp = self.make()
        self.assertTrue(sp.is_correct("привет"))
        self.assertFalse(sp.is_correct("казел"))
        self.assertTrue(sp.is_correct("москва"))  # словарь предлагает только поправить регистр: для расшифровки это верное слово

    def test_failed_call_raises(self):
        _, sp = self.make(fail_check=True)
        with self.assertRaises(spell.SpellError) as cm:
            sp.check("привет")
        self.assertIn("0x80004005", str(cm.exception))

    def test_null_pointer_is_refused(self):
        with self.assertRaises(spell.SpellError):
            spell.ComSpeller(0).check("привет")

    def test_guid(self):
        g = spell._guid("{7AB36653-1796-484B-BDFA-E74F1DB7C1DC}")
        self.assertEqual((g.Data1, g.Data2, g.Data3), (0x7AB36653, 0x1796, 0x484B))
        self.assertEqual(bytes(g.Data4), bytes.fromhex("BDFAE74F1DB7C1DC"))

    def test_without_windows(self):
        if sys.platform == "win32":
            self.skipTest("проверка для систем без Windows")
        speller, reason = spell.create_windows_speller()
        self.assertIsNone(speller)
        self.assertIn("только в Windows", reason)

    @unittest.skipUnless(sys.platform == "win32", "настоящий COM есть только в Windows")
    def test_real_windows_speller(self):  # pragma: no cover
        """Если в Windows есть английский словарь, проверяем на нём настоящие вызовы COM (русский на сборщике GitHub вряд ли установлен)."""
        speller, reason = spell.create_windows_speller("en-US")
        if speller is None:
            self.skipTest(reason)
        self.assertTrue(speller.is_correct("hello"))
        self.assertFalse(speller.is_correct("helo"))
        self.assertIn("hello", [w.lower() for w in speller.suggest("helo")])


# ── слова и замечания ──

class Words(unittest.TestCase):
    def test_yo_variants(self):
        self.assertEqual(spell.yo_variants("козел"), ["козёл"])
        self.assertEqual(spell.yo_variants("привет"), ["привёт"])
        self.assertEqual(spell.yo_variants("кот"), [])
        self.assertIn("ещё", spell.yo_variants("еще"))
        many = spell.yo_variants("нееееет")
        self.assertIn("нёёёёёт", many)
        self.assertLessEqual(len(many), 15)

    def test_word_regex(self):
        words = [m.group() for m in spell.WORD_RE.finditer("Привет, кто-то 25 abc по-русски, ёж!")]
        self.assertEqual(words, ["Привет", "кто-то", "по-русски", "ёж"])


class Service(unittest.TestCase):
    def test_yo_is_not_required(self):
        sp = FakeSpeller(["козёл"])
        self.assertTrue(spell.SpellService(sp).is_correct("козел"))
        self.assertTrue(spell.SpellService(sp).is_correct("Козёл"))

    def test_hyphenated_by_parts(self):
        service = spell.SpellService(FakeSpeller(["кто", "то", "по", "русски"]))
        self.assertTrue(service.is_correct("кто-то"))
        self.assertTrue(service.is_correct("по-русски"))
        self.assertFalse(spell.SpellService(FakeSpeller(["кто"])).is_correct("кто-тоо"))

    def test_answers_are_remembered(self):
        sp = FakeSpeller(["мир"])
        service = spell.SpellService(sp)
        for _ in range(5):
            service.is_correct("мир")
        self.assertEqual(sp.checked, ["мир"])

    def test_suggestions_are_written_as_in_transcripts(self):
        sp = FakeSpeller([], {"казел": ["Козёл", "кто-то", "abc", "казел", "козел", "ещё", "а", "б", "в"]})
        self.assertEqual(spell.SpellService(sp).suggestions("Казел"), ["козел", "кто то", "еще", "а", "б"])  # не больше пяти, без латиницы и повторов

    def test_broken_suggest_is_not_fatal(self):
        class Broken(FakeSpeller):
            def suggest(self, word, limit=8):
                raise spell.SpellError("нет")

        self.assertEqual(spell.SpellService(Broken()).suggestions("казел"), [])


class Issues(unittest.TestCase):
    def find(self, text, speller=None, known=None, occupied=(), **kw):
        return spell.find_spelling_issues(text, spell.SpellService(speller or russian_speller()), known, occupied, **kw)

    def test_flags_unknown_words(self):
        text = "привет казел, мир хател"
        issues = self.find(text)
        self.assertEqual([text[i.start : i.end] for i in issues], ["казел", "хател"])
        first = issues[0]
        self.assertEqual((first.level, first.code, first.auto, first.suggestion), (R.WARN, "spell", False, "козел"))
        self.assertIn("«казел»", first.message)
        self.assertIn("Варианты: козел, казан.", first.message)  # само слово среди вариантов не показываем

    def test_no_variants(self):
        issues = self.find("привет абвгд")
        self.assertEqual(issues[0].suggestion, None)
        self.assertIn("Вариантов нет", issues[0].message)

    def test_known_words_and_short_words_are_skipped(self):
        self.assertEqual(self.find("привет казел", known={"казел"}), [])
        self.assertEqual(self.find("привет ы", known=None), [])  # слова из одной буквы не проверяем
        self.assertEqual(self.find("привет Казел", known={"казел"}), [])  # регистр не важен

    def test_other_rules_have_priority(self):
        text = "привет щас казел"
        issues = self.find(text, occupied=[(7, 10)])
        self.assertEqual([text[i.start : i.end] for i in issues], ["казел"])

    def test_only_cyrillic_words(self):
        self.assertEqual(self.find("привет abcde 12345 +7"), [])

    def test_limit(self):
        text = " ".join(f"ббб{chr(1072 + i % 20)}{chr(1072 + i // 20)}" for i in range(100))
        self.assertEqual(len(self.find(text, limit=7)), 7)

    def test_dictionary_failure_stops_quietly(self):
        class Dead(FakeSpeller):
            def is_correct(self, word):
                raise spell.SpellError("не отвечает")

        self.assertEqual(self.find("привет казел", speller=Dead()), [])

    def test_probe(self):
        self.assertEqual(spell.probe(russian_speller(), spell.GOOD_WORDS, spell.BAD_WORDS), [])
        lenient = FakeSpeller(list(spell.GOOD_WORDS) + list(spell.BAD_WORDS) + ["козёл"])
        self.assertTrue(any("словарь принял" in p for p in spell.probe(lenient, spell.GOOD_WORDS, spell.BAD_WORDS)))
        strict = FakeSpeller([])
        self.assertTrue(any("не принял" in p for p in spell.probe(strict, spell.GOOD_WORDS, spell.BAD_WORDS)))


class Guard(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.flag = os.path.join(self.dir.name, spell.GUARD_FILE)

    def test_working_speller_is_returned_and_flag_removed(self):
        seen = []

        def factory():
            seen.append(os.path.exists(self.flag))  # пока идёт попытка, файл-метка лежит рядом
            return russian_speller(), "словарь теста"

        speller, status = spell.create_guarded(self.dir.name, factory)
        self.assertIsNotNone(speller)
        self.assertEqual((seen, status), ([True], "словарь теста"))
        self.assertFalse(os.path.exists(self.flag))

    def test_flag_left_by_a_crash_disables_spelling(self):
        with open(self.flag, "w") as f:
            f.write("x")

        def factory():
            raise AssertionError("после аварии пробовать нельзя")

        speller, status = spell.create_guarded(self.dir.name, factory)
        self.assertIsNone(speller)
        self.assertIn(spell.GUARD_FILE, status)
        self.assertTrue(os.path.exists(self.flag))  # метку убирает только человек

    def test_unavailable_dictionary(self):
        speller, status = spell.create_guarded(self.dir.name, lambda: (None, "нет словаря ru-RU"))
        self.assertEqual((speller, status), (None, "нет словаря ru-RU"))
        self.assertFalse(os.path.exists(self.flag))

    def test_dictionary_that_rejects_good_words_is_not_used(self):
        speller, status = spell.create_guarded(self.dir.name, lambda: (FakeSpeller([]), "странный"))
        self.assertIsNone(speller)
        self.assertIn("странно", status)

    def test_dictionary_that_fails_is_not_used(self):
        class Dead(FakeSpeller):
            def is_correct(self, word):
                raise spell.SpellError("код 0x80004005")

        speller, status = spell.create_guarded(self.dir.name, lambda: (Dead(), "словарь"))
        self.assertIsNone(speller)
        self.assertIn("0x80004005", status)
        self.assertFalse(os.path.exists(self.flag))

    def test_read_only_folder_still_works(self):
        speller, _ = spell.create_guarded(os.path.join(self.dir.name, "нет такой папки"), lambda: (russian_speller(), "ок"))
        self.assertIsNotNone(speller)


class KnownWords(unittest.TestCase):
    def test_parse_known_words(self):
        text = "# комментарий\n+ Яндекс\n+ ёлка, ваще\nпо тихому => потихому\n+\n"
        self.assertEqual(R.parse_known_words(text), {"яндекс", "елка", "ваще"})
        rules, problems = R.parse_extra_rules(text)
        self.assertEqual((len(rules), problems), (1, []))  # строки «+ слово» не считаются ошибками в правилах


if __name__ == "__main__":
    unittest.main()
