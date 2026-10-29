import os
import tempfile
import unittest

from transcheck import selftest

from .helpers import FakeSpeller, FakeWin, TkCase, russian_speller


class SelfTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def by_name(self, results):
        return {r.name: r for r in results}

    def test_without_windows_everything_runnable_passes(self):
        results = selftest.run_all(self.dir.name, gui=False, hotkeys_free=False)
        r = self.by_name(results)
        self.assertEqual(r["Правила на примерах из инструкции"].status, selftest.OK)
        self.assertEqual(r["Настройки и свои правила"].status, selftest.OK)
        self.assertEqual(r["Буфер обмена"].status, selftest.SKIP)
        self.assertEqual(r["Горячие клавиши"].status, selftest.SKIP)
        self.assertFalse([x for x in results if x.status == selftest.FAIL])

    def test_clipboard_step_with_working_clipboard_restores_previous_text(self):
        win = FakeWin()
        win.user_copies("прежний текст")
        results = selftest.run_all(self.dir.name, gui=False, hotkeys_free=False, winapi_mod=win)
        self.assertEqual(self.by_name(results)["Буфер обмена"].status, selftest.OK)
        self.assertEqual(win.text, "прежний текст")

    def test_clipboard_step_detects_broken_sequence_number(self):
        class Broken(FakeWin):
            def set_clipboard_text(self, text):
                self.text = text  # номер изменений не меняется: слежение за буфером не сработало бы

        results = selftest.run_all(self.dir.name, gui=False, hotkeys_free=False, winapi_mod=Broken())
        r = self.by_name(results)["Буфер обмена"]
        self.assertEqual(r.status, selftest.FAIL)
        self.assertIn("не изменился", r.detail)

    def test_clipboard_step_detects_garbled_text(self):
        class Garbles(FakeWin):
            def get_clipboard_text(self):
                return (self.text or "").replace("ё", "?")

        r = self.by_name(selftest.run_all(self.dir.name, gui=False, hotkeys_free=False, winapi_mod=Garbles()))["Буфер обмена"]
        self.assertEqual(r.status, selftest.FAIL)

    def test_hotkey_step(self):
        win = FakeWin()
        r = self.by_name(selftest.run_all(self.dir.name, gui=False, hotkeys_free=True, winapi_mod=win))["Горячие клавиши"]
        self.assertEqual(r.status, selftest.OK)
        self.assertTrue(win.thread.stopped)  # после проверки клавиши освобождены
        win2 = FakeWin()
        win2.hotkey_error = "Горячая клавиша для «hotkey_fix» уже занята другой программой."
        r = self.by_name(selftest.run_all(self.dir.name, gui=False, hotkeys_free=True, winapi_mod=win2))["Горячие клавиши"]
        self.assertEqual(r.status, selftest.FAIL)
        self.assertIn("занята", r.detail)

    def test_bad_config_is_a_failure_not_a_crash(self):
        with open(os.path.join(self.dir.name, "config.json"), "w", encoding="utf-8") as f:
            f.write("{ сломано")
        r = self.by_name(selftest.run_all(self.dir.name, gui=False, hotkeys_free=False))["Настройки и свои правила"]
        self.assertEqual(r.status, selftest.FAIL)
        self.assertIn("config.json", r.detail)

    def test_bad_extra_rules_are_reported(self):
        with open(os.path.join(self.dir.name, "rules_extra.txt"), "w", encoding="utf-8") as f:
            f.write("без стрелки\n")
        r = self.by_name(selftest.run_all(self.dir.name, gui=False, hotkeys_free=False))["Настройки и свои правила"]
        self.assertEqual(r.status, selftest.FAIL)
        self.assertIn("строка 1", r.detail)

    def test_spelling_step_is_skipped_without_dictionary(self):
        r = self.by_name(selftest.run_all(self.dir.name, gui=False, hotkeys_free=False, spell_status="в Windows нет словаря"))["Орфография"]
        self.assertEqual(r.status, selftest.SKIP)
        self.assertIn("в Windows нет словаря", r.detail)

    def test_spelling_step_checks_good_and_bad_words(self):
        r = self.by_name(selftest.run_all(self.dir.name, gui=False, hotkeys_free=False, speller=russian_speller(), spell_status="словарь теста"))["Орфография"]
        self.assertEqual(r.status, selftest.OK, r.detail)
        self.assertIn("«козел» принят", r.detail)
        self.assertIn("«казел» отклонён", r.detail)
        self.assertIn("козел", r.detail.split("варианты для «казел»:")[1])

    def test_spelling_step_fails_when_dictionary_accepts_everything(self):
        lenient = FakeSpeller(["козёл", "казел", "привет", "сейчас", "потому", "хотел", "вчера", "хател", "вчира", "патаму"])
        r = self.by_name(selftest.run_all(self.dir.name, gui=False, hotkeys_free=False, speller=lenient, spell_status="словарь"))["Орфография"]
        self.assertEqual(r.status, selftest.FAIL)
        self.assertIn("словарь принял", r.detail)

    def test_spelling_step_fails_when_dictionary_rejects_good_words(self):
        r = self.by_name(selftest.run_all(self.dir.name, gui=False, hotkeys_free=False, speller=FakeSpeller([]), spell_status="словарь"))["Орфография"]
        self.assertEqual(r.status, selftest.FAIL)
        self.assertIn("не принял", r.detail)

    def test_command_line_never_touches_the_dictionary(self):
        out = os.path.join(self.dir.name, "report.txt")
        selftest.main(["--selftest", "--quiet", "--no-gui", "--out", out])
        with open(out, encoding="utf-8") as f:
            report = f.read()
        self.assertIn("[ -- ] Орфография", report)
        self.assertIn("кнопкой «Самопроверка»", report)

    def test_report_text(self):
        text = selftest.format_report(selftest.run_all(self.dir.name, gui=False, hotkeys_free=False))
        self.assertIn("самопроверка", text)
        self.assertIn("Итог: всё в порядке", text)
        self.assertIn("НЕ проверяется", text)

    def test_main_writes_report_file_and_exit_code(self):
        out = os.path.join(self.dir.name, "report.txt")
        code = selftest.main(["--selftest", "--quiet", "--no-gui", "--out", out])
        with open(out, encoding="utf-8") as f:
            self.assertIn("Правила на примерах из инструкции", f.read())
        self.assertEqual(code, 0)

    def test_examples_are_in_sync_with_rules(self):
        from transcheck.rules_ru import analyze, fix_all

        for src, want in selftest.EXAMPLES:
            self.assertEqual(fix_all(src), want, src)
        for src, code in selftest.FLAGGED:
            self.assertIn(code, [i.code for i in analyze(src).issues], src)


class SelfTestWindow(TkCase):
    def test_window_step(self):
        with tempfile.TemporaryDirectory() as d:
            results = selftest.run_all(d, gui=True, hotkeys_free=False)
        r = {x.name: x for x in results}["Окно"]
        self.assertEqual(r.status, selftest.OK, r.detail)


if __name__ == "__main__":
    unittest.main()
