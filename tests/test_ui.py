import sys
import unittest

try:
    from transcheck import ui
except ImportError:  # нет tkinter
    raise unittest.SkipTest("нет tkinter")
from transcheck import rules_ru as R

from .helpers import TkCase, pump


def _offset(widget, index):
    counted = widget.count("1.0", str(index), "chars")  # Tk возвращает None, если расстояние равно нулю
    return counted[0] if counted else 0


def tag_ranges(widget, tag):
    r = widget.tag_ranges(tag)
    return [(_offset(widget, r[i]), _offset(widget, r[i + 1])) for i in range(0, len(r), 2)]


def tag_text(widget, tag):
    return [widget.get("1.0", "end-1c")[a:b] for a, b in tag_ranges(widget, tag)]


class MainWindowTests(TkCase):
    def make(self, **kw):
        self.calls = []
        kw.setdefault("on_fix_copy", lambda: self.calls.append("fix"))
        kw.setdefault("on_copy", lambda: self.calls.append("copy"))
        kw.setdefault("on_rules", lambda: self.calls.append("rules"))
        kw.setdefault("on_selftest", lambda: self.calls.append("selftest"))
        kw.setdefault("on_quit", lambda: self.calls.append("quit"))
        kw.setdefault("on_watch", lambda v: self.calls.append(("watch", v)))
        kw.setdefault("on_topmost", lambda v: self.calls.append(("topmost", v)))
        self.win = ui.MainWindow(self.root, **kw)
        self.root.deiconify()
        self.root.update()
        return self.win

    def test_empty_state(self):
        w = self.make()
        self.assertEqual(w.summary_var.get(), "Текста пока нет")
        self.assertEqual(w.tree.get_children(), ())

    def test_highlight_and_list(self):
        w = self.make()
        w.set_text("Привет, мир 25 ха ха")
        self.assertEqual(tag_text(w.text, "hl_error"), ["Привет,", "25"])
        self.assertEqual(tag_text(w.text, "hl_warn"), ["ха ха"])
        rows = [w.tree.item(i, "values") for i in w.tree.get_children()]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][0], "Исправить ✓")  # само исправится
        self.assertEqual(rows[1][0], "Исправить")
        self.assertEqual(rows[2][0], "Проверить")
        self.assertIn("исправить: 2", w.summary_var.get())
        self.assertIn("проверить: 1", w.summary_var.get())
        self.assertIn("исправится само: 1", w.summary_var.get())

    def test_no_issues(self):
        w = self.make()
        w.set_text("это правильный текст")
        self.assertEqual(w.summary_var.get(), "Замечаний нет")
        self.assertEqual(tag_ranges(w.text, "hl_error"), [])

    def test_select_row_shows_explanation_and_marks_place(self):
        w = self.make()
        w.set_text("позвони +7 900 123")
        w.tree.selection_set("0")
        w.root.update()
        self.assertEqual(tag_text(w.text, "hl_sel"), ["+7 900 123"])
        detail = w.detail_var.get()
        self.assertIn("плюс семь девятьсот сто двадцать три", detail)
        self.assertIn("разд. 9", detail)
        self.assertIn("Само не исправляется", detail)

    def test_detail_for_issue_without_suggestion(self):
        w = self.make()
        w.set_text("вышел бл*** на бульвар")
        w.tree.selection_set("0")
        w.root.update()
        self.assertIn("Предложения нет", w.detail_var.get())

    def test_apply_selected_number(self):
        w = self.make()
        w.set_text("мне 25 лет")
        w.tree.selection_set("0")
        w.apply_selected()
        self.assertEqual(w.get_text(), "мне двадцать пять лет")
        self.assertEqual(w.summary_var.get(), "Замечаний нет")

    def test_apply_selected_without_selection_or_suggestion(self):
        w = self.make()
        w.set_text("мне 25 лет")
        w.apply_selected()
        self.assertIn("выберите замечание", w.note_var.get())
        w.set_text("вышел бл*** на бульвар")
        w.tree.selection_set("0")
        w.apply_selected()
        self.assertEqual(w.get_text(), "вышел бл*** на бульвар")
        self.assertIn("нет предложения", w.note_var.get())

    def test_double_click_is_bound_to_apply(self):
        w = self.make()
        w.set_text("я последний раз сидел ха ха ха ну в общем вышел")
        self.assertTrue(w.tree.bind("<Double-1>"))  # двойной щелчок по строке применяет предложение
        w.tree.selection_set("0")
        w.apply_selected()  # то же действие, которое вызывает двойной щелчок
        self.assertEqual(w.get_text(), "я последний раз сидел ну в общем вышел")

    def test_fix_safe(self):
        w = self.make()
        w.set_text("Привет, Мир! щас 25")
        self.assertEqual(w.fix_safe(), "привет мир сейчас 25")
        self.assertEqual(w.get_text(), "привет мир сейчас 25")
        self.assertEqual([i.code for i in w.analysis.issues], ["number"])

    def test_typing_refreshes_after_pause(self):
        w = self.make()
        w.text.insert("1.0", "Привет")
        w._on_edit()
        pump(self.root, 450)
        self.assertEqual(tag_text(w.text, "hl_error"), ["Привет"])

    def test_paste_event_refreshes(self):
        w = self.make()
        self.root.clipboard_clear()
        self.root.clipboard_append("Мир, привет")
        w.text.focus_force()
        w.text.event_generate("<<Paste>>")
        pump(self.root, 450)
        self.assertEqual(w.get_text(), "Мир, привет")
        self.assertEqual(tag_text(w.text, "hl_error"), ["Мир,"])

    def test_clear(self):
        w = self.make()
        w.set_text("Привет")
        w.note_set("что-то")
        w.clear()
        self.assertEqual(w.get_text(), "")
        self.assertEqual(w.note_var.get(), "")
        self.assertEqual(w.tree.get_children(), ())

    def test_extra_rules_change_the_result(self):
        w = self.make()
        w.set_text("по тихому")
        self.assertEqual(w.analysis.issues, [])
        rules, _ = R.parse_extra_rules("по тихому => потихому")
        w.set_extra_rules(rules)
        self.assertEqual(w.fix_safe(), "потихому")

    def test_emoji_disables_highlight_but_not_list(self):
        w = self.make()
        w.set_text("Привет 😀 мир")
        self.assertEqual(tag_ranges(w.text, "hl_error"), [])
        self.assertTrue(w.tree.get_children())
        self.assertIn("подсветка отключена", w.note_var.get())

    def test_buttons_call_back(self):
        w = self.make(fix_hotkey="ctrl+alt+j")
        self.assertIn("Ctrl+Alt+J", w.btn_fix.cget("text"))
        w.btn_fix.invoke()
        self.assertEqual(self.calls, ["fix"])

    def test_checkbuttons_report_changes(self):
        w = self.make()
        w.watch_var.set(False)
        w.topmost_var.set(False)
        w._topmost_changed()
        self.assertIn(("topmost", False), self.calls)

    def test_x_minimizes_instead_of_closing(self):
        w = self.make()
        seen = []
        self.root.iconify = lambda: seen.append("iconify")  # на экране без оконного менеджера состояние окна не меняется
        self.root.deiconify = lambda: seen.append("deiconify")
        self.root.lift = lambda: seen.append("lift")
        w.minimize()
        w.show()
        self.assertEqual(seen, ["iconify", "deiconify", "lift"])
        self.assertIn("minimize", self.root.protocol("WM_DELETE_WINDOW"))  # крестик привязан к сворачиванию, а не к закрытию

    def test_everything_is_visible(self):
        """Последний элемент окна (памятка) целиком помещается в окно; ничего не обрезано."""
        w = self.make()
        w.set_text("Привет, Мир! щас 25 ха ха вышел бл*** на бульвар give me what I need")
        self.root.update()
        pump(self.root, 100)
        bottom = max(child.winfo_y() + child.winfo_height() for child in self.root.winfo_children())
        self.assertLessEqual(bottom, self.root.winfo_height(), (bottom, self.root.winfo_height()))
        self.assertGreater(w.tree.winfo_height(), 60)  # список замечаний не сжат до нуля

    def test_window_fits_a_small_screen_at_large_scale(self):
        """Экран 1080 пикселей при масштабе 150 %: окно не должно быть выше экрана, и всё содержимое остаётся видно."""
        self.root.tk.call("tk", "scaling", 2.0)  # 144 dpi = 150 %
        self.root.winfo_screenheight = lambda: 1080
        self.root.winfo_screenwidth = lambda: 1920
        w = self.make()
        w.set_text("Привет, Мир! щас 25 ха ха вышел бл*** на бульвар give me what I need")
        self.root.update()
        pump(self.root, 100)
        geometry = self.root.geometry()
        height = int(geometry.split("x")[1].split("+")[0])
        self.assertLessEqual(height, 1080 - 100)
        bottom = max(child.winfo_y() + child.winfo_height() for child in self.root.winfo_children())
        self.assertLessEqual(bottom, self.root.winfo_height())

    def test_labels_rewrap_when_window_is_resized(self):
        w = self.make()
        self.root.geometry("900x800")
        pump(self.root, 100)
        self.assertGreater(int(str(w.footer.cget("wraplength"))), 700)

    @unittest.skipUnless(sys.platform == "win32", "в Windows код клавиши не зависит от раскладки")
    def test_ctrl_keys_work_in_russian_layout(self):  # pragma: no cover
        w = self.make()
        w.set_text("текст")
        self.root.clipboard_clear()
        self.root.clipboard_append("вставка")
        w.text.focus_force()
        w.text.tag_add("sel", "1.0", "end-1c")
        w.text.event_generate("<Control-KeyPress>", keycode=86)  # V
        pump(self.root, 100)
        self.assertEqual(w.get_text(), "вставка")


class ReportWindow(TkCase):
    def test_report_window(self):
        win = ui.show_report(self.root, "Отчёт", "строка 1\nстрока 2")
        self.root.update()
        self.assertEqual(win.title(), "Отчёт")
        texts = [c for c in win.winfo_children() if c.winfo_class() == "Text"]
        self.assertEqual(texts[0].get("1.0", "end-1c"), "строка 1\nстрока 2")


class Helpers(unittest.TestCase):
    def test_pretty_hotkey(self):
        self.assertEqual(ui.pretty_hotkey("ctrl+alt+k"), "Ctrl+Alt+K")
        self.assertEqual(ui.pretty_hotkey("ctrl+shift+f5"), "Ctrl+Shift+F5")
        self.assertEqual(ui.pretty_hotkey("win+space"), "Win+Space")


if __name__ == "__main__":
    unittest.main()
