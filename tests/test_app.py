import json
import os
import tempfile
import unittest

try:
    import tkinter as tk
except ImportError:  # нет tkinter
    raise unittest.SkipTest("нет tkinter")

from transcheck import app, config
from transcheck.config import TransCheckError

from .helpers import FakeWin, TkCase, russian_speller


class ControllerBase(TkCase):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.win = FakeWin()
        self.opened = []

    def make(self, cfg=None, speller=None):
        """По умолчанию словаря нет: тесты не должны зависеть от того, что установлено в Windows на сборщике."""
        if cfg is not None:
            with open(os.path.join(self.dir.name, "config.json"), "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        factory = (lambda: (speller, "словарь теста")) if speller is not None else (lambda: (None, "в тесте словаря нет"))
        self.c = app.Controller(self.root, self.dir.name, self.win, opener=self.opened.append, speller_factory=factory)
        # На экране без оконного менеджера Tk считает, что фокус всегда у него; в жизни фокус у браузера
        self.c._app_has_focus = lambda: False
        self.root.deiconify()
        self.root.update()
        return self.c

    def tearDown(self):
        c = getattr(self, "c", None)
        if c is not None:
            c.closing = True
            if c._after_id is not None:
                try:
                    self.root.after_cancel(c._after_id)
                except Exception:
                    pass
        super().tearDown()

    def tick(self):
        """Один шаг опроса, как по таймеру."""
        self.c._poll()
        self.root.update()


class Clipboard(ControllerBase):
    def test_start_registers_three_hotkeys(self):
        self.make()
        self.assertEqual(set(self.win.combos), {"hotkey_check", "hotkey_fix", "hotkey_quit"})
        self.assertTrue(os.path.isfile(os.path.join(self.dir.name, "rules_extra.txt")))
        self.assertTrue(os.path.isfile(os.path.join(self.dir.name, "config.json")))

    def test_text_in_clipboard_before_start_is_not_taken(self):
        self.win.user_copies("старый текст")
        c = self.make()
        self.tick()
        self.assertEqual(c.ui.get_text(), "")

    def test_copy_in_other_program_appears_in_window(self):
        c = self.make()
        self.win.user_copies("Привет, мир\r\nещё строка")
        self.tick()
        self.assertEqual(c.ui.get_text(), "Привет, мир\nещё строка")
        self.assertIn("взят из буфера", c.ui.note_var.get())
        self.assertGreater(len(c.ui.analysis.issues), 0)

    def test_identical_clipboard_text_does_not_touch_the_window(self):
        c = self.make()
        self.win.user_copies("привет")
        self.tick()
        c.ui.text.insert("end", " мир")  # человек дописал в окне
        c.ui.refresh()
        self.win.user_copies("привет")  # снова скопировали тот же текст, что был в окне раньше
        self.tick()
        self.assertEqual(c.ui.get_text(), "привет")  # новое копирование — это новый текст: окно показывает то, что скопировано

    def test_own_write_is_not_taken_back(self):
        c = self.make()
        self.win.user_copies("Привет, Мир")
        self.tick()
        c.fix_and_copy()
        fixed = c.ui.get_text()
        self.assertEqual(fixed, "привет мир")
        self.assertEqual(self.win.text, "привет мир")
        c.ui.text.insert("end", " да")  # дописали в окне
        self.tick()
        self.tick()
        self.assertEqual(c.ui.get_text(), "привет мир да")  # наша же запись в буфер текст не подменила

    def test_watch_off_ignores_copies(self):
        c = self.make({"watch_clipboard": False})
        self.win.user_copies("привет")
        self.tick()
        self.assertEqual(c.ui.get_text(), "")
        self.assertFalse(c.ui.watch_var.get())

    def test_checkbox_turns_watch_off_and_on(self):
        c = self.make()
        c.ui.watch_var.set(False)
        self.win.user_copies("первый")
        self.tick()
        self.assertEqual(c.ui.get_text(), "")
        c.ui.watch_var.set(True)
        self.tick()
        self.assertEqual(c.ui.get_text(), "")  # то, что скопировано, пока подхват был выключен, не всплывает потом
        self.win.user_copies("второй")
        self.tick()
        self.assertEqual(c.ui.get_text(), "второй")

    def test_copy_inside_our_window_does_not_replace_text(self):
        c = self.make()
        c.ui.set_text("мой текст")
        c._app_has_focus = lambda: True  # фокус в нашем окне
        self.win.user_copies("мой")  # выделили часть и нажали Ctrl+C внутри окна
        self.tick()
        self.assertEqual(c.ui.get_text(), "мой текст")
        c._app_has_focus = lambda: False
        self.tick()
        self.assertEqual(c.ui.get_text(), "мой текст")  # и позже тоже не подхватывается

    def test_too_long_text_is_not_taken(self):
        c = self.make({"max_chars": 20})
        self.win.user_copies("а" * 21)
        self.tick()
        self.assertEqual(c.ui.get_text(), "")
        self.assertIn("слишком много", c.ui.note_var.get())

    def test_non_text_clipboard_is_silent_when_watching_and_explained_on_hotkey(self):
        c = self.make()
        self.win.text = None
        self.win.seq += 1  # скопировали картинку
        self.tick()
        self.assertEqual(c.ui.note_var.get(), "")
        self.win.press("hotkey_check")
        self.tick()
        self.assertIn("нет текста", c.ui.note_var.get())

    def test_clipboard_busy_is_reported(self):
        c = self.make()
        self.win.busy = True
        self.win.seq += 1
        self.tick()
        self.assertIn("занят", c.ui.note_var.get())
        self.win.busy = False
        self.win.user_copies("после занятости")
        self.tick()
        self.assertEqual(c.ui.get_text(), "после занятости")

    def test_busy_clipboard_is_retried_and_text_arrives_when_it_frees_up(self):
        c = self.make()
        self.win.user_copies("после занятости")
        self.win.busy = True  # браузер ещё не закончил запись в буфер
        self.tick()
        self.tick()
        self.assertEqual(c.ui.get_text(), "")
        self.win.busy = False  # освободил
        self.tick()
        self.assertEqual(c.ui.get_text(), "после занятости")  # тот же номер изменений, но текст всё же подхвачен

    def test_busy_clipboard_gives_up_after_a_while(self):
        c = self.make()
        self.win.user_copies("никогда")
        self.win.busy = True
        for _ in range(c.BUSY_RETRIES + 2):
            self.tick()
        self.win.busy = False
        self.tick()
        self.assertEqual(c.ui.get_text(), "")  # бесконечных попыток нет

    def test_nul_and_cr_characters_are_normalized(self):
        c = self.make()
        self.win.user_copies("а\rб")
        self.tick()
        self.assertEqual(c.ui.get_text(), "а\nб")


class Hotkeys(ControllerBase):
    def test_check_hotkey_takes_clipboard_even_when_watch_is_off(self):
        c = self.make({"watch_clipboard": False})
        self.win.user_copies("Привет")
        self.win.press("hotkey_check")
        self.tick()
        self.assertEqual(c.ui.get_text(), "Привет")

    def test_fix_hotkey_fixes_and_copies(self):
        c = self.make()
        c.ui.set_text("Привет, Мир! щас")
        self.win.press("hotkey_fix")
        self.tick()
        self.assertEqual(self.win.text, "привет мир сейчас")
        self.assertEqual(c.ui.get_text(), "привет мир сейчас")
        self.assertIn("Замечаний нет", c.ui.note_var.get())

    def test_fix_reports_what_is_left_for_the_human(self):
        c = self.make()
        c.ui.set_text("Привет, мне 25 лет")
        c.fix_and_copy()
        self.assertEqual(self.win.text, "привет мне 25 лет")
        self.assertIn("Осталось на вашей проверке: 1", c.ui.note_var.get())

    def test_fix_with_nothing_to_fix_says_so(self):
        c = self.make()
        c.ui.set_text("привет мир")
        c.fix_and_copy()
        self.assertEqual(self.win.text, "привет мир")
        self.assertIn("исправлять было нечего", c.ui.note_var.get())

    def test_fix_without_text(self):
        c = self.make()
        c.fix_and_copy()
        self.assertEqual(self.win.writes, [])
        self.assertIn("Текста нет", c.ui.note_var.get())

    def test_fix_when_clipboard_is_busy_keeps_text_and_says_so(self):
        c = self.make()
        c.ui.set_text("Привет")
        self.win.busy = True
        c.fix_and_copy()
        self.assertIn("в буфер обмена он не попал", c.ui.note_var.get())
        self.assertIn("занят", c.ui.note_var.get())
        self.assertEqual(c.ui.get_text(), "привет")  # исправление в окне применено, копирование можно повторить
        self.win.busy = False
        c.copy_current()
        self.assertEqual(self.win.text, "привет")
        self.assertIn("скопирован", c.ui.note_var.get())

    def test_copy_button(self):
        c = self.make()
        c.ui.set_text("Привет, мир")
        c.copy_current()
        self.assertEqual(self.win.text, "Привет, мир")  # без исправлений: кнопка копирует как есть
        c.ui.clear()
        c.copy_current()
        self.assertIn("нечего", c.ui.note_var.get())

    def test_quit_hotkey_stops_everything(self):
        c = self.make()
        self.win.press("hotkey_quit")
        c._poll()
        self.assertTrue(c.closing)
        self.assertTrue(self.win.thread.stopped)
        with self.assertRaises(tk.TclError):
            self.root.winfo_exists()  # окно закрыто

    def test_hotkey_conflict_is_reported_at_start(self):
        self.win.hotkey_error = "Горячая клавиша для «hotkey_fix» уже занята другой программой."
        with self.assertRaises(TransCheckError) as cm:
            self.make()
        self.assertIn("занята", str(cm.exception))

    def test_bad_hotkey_in_config_is_reported_at_start(self):
        with self.assertRaises(TransCheckError):
            self.make({"hotkey_fix": "k"})

    def test_poll_survives_handler_errors(self):
        c = self.make()
        c._dispatch = lambda name: (_ for _ in ()).throw(RuntimeError("сбой"))
        self.win.press("hotkey_check")
        self.tick()
        self.assertIn("сбой", c.ui.note_var.get())
        self.assertFalse(c.closing)
        self.win.user_copies("после сбоя")
        self.tick()
        self.assertEqual(c.ui.get_text(), "после сбоя")


class ExtraRules(ControllerBase):
    def test_file_changes_are_picked_up_without_restart(self):
        c = self.make()
        c.ui.set_text("по тихому")
        self.assertEqual(c.ui.analysis.issues, [])
        path = config.rules_extra_path(self.dir.name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("по тихому => потихому\n")
        os.utime(path, (os.path.getmtime(path) + 5, os.path.getmtime(path) + 5))
        self.tick()
        self.assertEqual(c.ui.fix_safe(), "потихому")
        self.assertIn("обновлены (1)", c.ui.note_var.get())

    def test_problems_are_shown_and_good_lines_still_work(self):
        c = self.make()
        path = config.rules_extra_path(self.dir.name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("без стрелки\nоч => очень\n")
        os.utime(path, (os.path.getmtime(path) + 5, os.path.getmtime(path) + 5))
        self.tick()
        self.assertIn("строка 1", c.ui.note_var.get())
        c.ui.set_text("оч хорошо")
        self.assertEqual(c.ui.fix_safe(), "очень хорошо")

    def test_unreadable_file_is_reported(self):
        c = self.make()
        path = config.rules_extra_path(self.dir.name)
        with open(path, "wb") as f:
            f.write("оч => очень".encode("cp1251"))
        os.utime(path, (os.path.getmtime(path) + 5, os.path.getmtime(path) + 5))
        self.tick()
        self.assertIn("UTF-8", c.ui.note_var.get())

    def test_deleted_file_is_not_an_error(self):
        c = self.make()
        os.remove(config.rules_extra_path(self.dir.name))
        self.tick()
        self.tick()
        self.assertNotIn("Ошибка", c.ui.note_var.get())

    def test_open_rules_button(self):
        c = self.make()
        os.remove(config.rules_extra_path(self.dir.name))
        c.open_rules()
        self.assertEqual(self.opened, [config.rules_extra_path(self.dir.name)])
        self.assertTrue(os.path.isfile(self.opened[0]))

    def test_open_rules_failure_is_reported(self):
        c = self.make()

        def boom(path):
            raise OSError("нет программы для .txt")

        c.opener = boom
        c.open_rules()
        self.assertIn("нет программы", c.ui.note_var.get())


class SelfTestButton(ControllerBase):
    def test_selftest_report_opens_and_clipboard_check_restores_text(self):
        c = self.make()
        self.win.user_copies("то, что было в буфере")
        c.run_selftest()
        self.root.update()
        windows = [w for w in self.root.winfo_children() if w.winfo_class() == "Toplevel"]
        self.assertEqual(len(windows), 1)
        report = [x for x in windows[0].winfo_children() if x.winfo_class() == "Text"][0].get("1.0", "end-1c")
        self.assertIn("самопроверка", report)
        self.assertNotIn("СБОЙ", report)
        self.assertEqual(self.win.text, "то, что было в буфере")
        self.tick()
        self.assertEqual(c.ui.get_text(), "")  # проверочная запись не подхватывается как «скопированный текст»


class Spelling(ControllerBase):
    def test_default_without_dictionary_says_so(self):
        c = self.make()
        self.assertIsNone(c.speller)
        self.assertIn("не проверяет", c.ui.hint.cget("text"))
        self.assertIn("в тесте словаря нет", c.ui.hint.cget("text"))

    def test_dictionary_is_used_and_flag_file_is_removed(self):
        c = self.make(speller=russian_speller())
        c.ui.set_text("привет казел")
        self.assertEqual(c.ui.summary_var.get(), "Замечаний: 1")
        self.assertFalse(os.path.exists(os.path.join(self.dir.name, "spell_crash.flag")))

    def test_config_can_turn_spelling_off(self):
        c = self.make(cfg={"spellcheck": False}, speller=russian_speller())
        self.assertIsNone(c.speller)
        c.ui.set_text("привет казел")
        self.assertEqual(c.ui.summary_var.get(), "Замечаний нет")
        self.assertIn("spellcheck", c.ui.hint.cget("text"))

    def test_crash_flag_disables_spelling(self):
        with open(os.path.join(self.dir.name, "spell_crash.flag"), "w") as f:
            f.write("x")
        c = self.make(speller=russian_speller())
        self.assertIsNone(c.speller)
        self.assertIn("spell_crash.flag", c.ui.hint.cget("text"))

    def test_known_word_button_writes_the_file_and_the_word_stays_known(self):
        c = self.make(speller=russian_speller())
        c.ui.set_text("привет абвгд")
        c.ui.tree.selection_set("0")
        c.ui.mark_known()
        path = config.rules_extra_path(self.dir.name)
        with open(path, encoding="utf-8") as f:
            self.assertTrue(f.read().rstrip().endswith("+ абвгд"))
        self.assertIn("добавлено", c.ui.note_var.get())
        self.assertEqual(c.ui.summary_var.get(), "Замечаний нет")
        c.ui.set_text("привет абвгд")  # новый текст: слово уже в «своих словах»
        self.assertEqual(c.ui.summary_var.get(), "Замечаний нет")

    def test_known_words_from_file_are_read_at_start_and_on_change(self):
        config.ensure_rules_extra(self.dir.name)
        path = config.rules_extra_path(self.dir.name)
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n+ абвгд\n")
        c = self.make(speller=russian_speller())
        c.ui.set_text("привет абвгд эюяфц")
        self.assertEqual([c.ui.get_text()[i.start : i.end] for i in c.ui._shown], ["эюяфц"])
        with open(path, "a", encoding="utf-8") as f:
            f.write("+ эюяфц\n")
        os.utime(path, (os.path.getmtime(path) + 5, os.path.getmtime(path) + 5))
        self.tick()
        self.assertEqual(c.ui.summary_var.get(), "Замечаний нет")

    def test_known_word_is_appended_on_a_new_line(self):
        c = self.make(speller=russian_speller())
        path = config.rules_extra_path(self.dir.name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("оч => очень")  # последняя строка без перевода строки
        c.add_known_word("абвгд")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "оч => очень\n+ абвгд\n")

    def test_unwritable_rules_file_is_reported_but_word_works_until_exit(self):
        c = self.make(speller=russian_speller())
        path = config.rules_extra_path(self.dir.name)
        os.remove(path)
        os.mkdir(path)  # вместо файла папка: открыть на запись нельзя
        c.ui.set_text("привет абвгд")
        c.ui.tree.selection_set("0")
        c.ui.mark_known()
        self.assertIn("не удалось записать", c.ui.note_var.get())
        self.assertEqual(c.ui.summary_var.get(), "Замечаний нет")

    def test_fix_and_copy_counts_spelling_among_what_is_left(self):
        c = self.make(speller=russian_speller())
        c.ui.set_text("Привет казел")
        c.fix_and_copy()
        self.assertEqual(self.win.text, "привет казел")
        self.assertIn("Осталось на вашей проверке: 1", c.ui.note_var.get())

    def test_selftest_gets_the_dictionary(self):
        c = self.make(speller=russian_speller())
        c.run_selftest()
        self.root.update()
        windows = [w for w in self.root.winfo_children() if w.winfo_class() == "Toplevel"]
        report = [x for x in windows[0].winfo_children() if x.winfo_class() == "Text"][0].get("1.0", "end-1c")
        self.assertIn("[ ОК ] Орфография", report)
        self.assertIn("«казел» отклонён", report)


class Quit(ControllerBase):
    def test_x_button_quits_completely(self):
        c = self.make()
        self.root.tk.call(self.root.protocol("WM_DELETE_WINDOW"))  # так Windows сообщает окну о нажатии на крестик
        self.assertTrue(c.closing)
        self.assertTrue(self.win.thread.stopped)  # горячие клавиши освобождены
        with self.assertRaises(tk.TclError):
            self.root.winfo_exists()  # окно уничтожено, mainloop завершится, процесс выйдет

    def test_quit_cancels_polling(self):
        c = self.make()
        c.quit()
        c.quit()  # повторный вызов безвреден
        self.assertTrue(self.win.thread.stopped)


if __name__ == "__main__":
    unittest.main()
