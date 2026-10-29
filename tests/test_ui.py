import sys
import unittest
from unittest import mock

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


def tk_label_like(root, window):
    """Подпись с теми же шрифтом, отступами и переносом, что у пояснения, но без заданной высоты: показывает, сколько места нужно тексту."""
    return ui.tk.Label(
        root, justify="left", anchor="nw", font=ui.FONT_SMALL, padx=10, pady=7,
        wraplength=int(str(window.detail.cget("wraplength"))),
    )


class MainWindowTests(TkCase):
    def make(self, font_extra=0, **kw):
        """font_extra: на сколько пунктов крупнее шрифты. На экране без Segoe UI Tk подставляет мелкий растровый шрифт одного размера,
        и тесты раскладки проходят зря; Helvetica масштабируется, как настоящий шрифт."""
        for name, spec in (("FONT", (10,)), ("FONT_TEXT", (12,)), ("FONT_SMALL", (9,)), ("FONT_BOLD", (11, "bold"))):
            patcher = mock.patch.object(ui, name, ("Helvetica", spec[0] + font_extra, *spec[1:]))
            patcher.start()
            self.addCleanup(patcher.stop)
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

    def mapped(self, widget):
        self.root.update()
        return bool(widget.winfo_ismapped())

    def mapped_chips(self, w):
        self.root.update()
        return [bool(label.winfo_ismapped()) for _, label in w._chips]

    def test_empty_state(self):
        w = self.make()
        self.assertEqual(w.summary_var.get(), "Текста пока нет")
        self.assertEqual(w.tree.get_children(), ())
        self.assertTrue(self.mapped(w.placeholder))  # вместо пустого поля серая подсказка
        self.assertTrue(self.mapped(w.tree_empty))  # вместо пустого списка подсказка по центру
        self.assertEqual(self.mapped_chips(w), [False, False, False])
        self.assertIn("появятся", w.detail_var.get())

    def test_highlight_and_list(self):
        w = self.make()
        w.set_text("Привет, мир 25 ха ха")
        self.assertEqual(tag_text(w.text, "hl_auto"), ["Привет,"])  # исправится само: синяя подсветка
        self.assertEqual(tag_text(w.text, "hl_error"), ["25"])  # вручную: красная
        self.assertEqual(tag_text(w.text, "hl_warn"), ["ха ха"])  # проверить: жёлтая
        rows = [w.tree.item(i, "values") for i in w.tree.get_children()]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][0], "Исправить ✓")  # само исправится
        self.assertEqual(rows[1][0], "Исправить")
        self.assertEqual(rows[2][0], "Проверить")
        self.assertEqual([w.tree.item(i, "tags")[0] for i in w.tree.get_children()], ["auto", "error", "warn"])
        self.assertEqual([var.get() for var, _ in w._chips], ["Исправится само: 1", "Исправить вручную: 1", "Проверить: 1"])
        self.assertEqual(self.mapped_chips(w), [True, True, True])
        self.assertEqual(w.summary_var.get(), "Замечаний: 3")
        self.assertFalse(self.mapped(w.placeholder))
        self.assertFalse(self.mapped(w.tree_empty))

    def test_chips_hide_when_zero(self):
        w = self.make()
        w.set_text("Привет, Мир!")  # только исправляемое само
        self.assertEqual(self.mapped_chips(w), [True, False, False])
        self.assertEqual(w.summary_var.get(), "Замечаний: 2")

    def test_no_issues(self):
        w = self.make()
        w.set_text("это правильный текст")
        self.assertEqual(w.summary_var.get(), "Замечаний нет")
        for tag in ("hl_error", "hl_warn", "hl_auto"):
            self.assertEqual(tag_ranges(w.text, tag), [])
        self.assertEqual(self.mapped_chips(w), [False, False, False])
        self.assertTrue(self.mapped(w.tree_empty))
        self.assertFalse(self.mapped(w.placeholder))

    def test_placeholder_follows_the_text(self):
        w = self.make()
        w.set_text("текст")
        self.assertFalse(self.mapped(w.placeholder))
        w.clear()
        self.assertTrue(self.mapped(w.placeholder))
        w.text.insert("1.0", "н")
        w._on_edit()  # подсказка пропадает сразу, не дожидаясь паузы
        self.root.update()
        self.assertFalse(self.mapped(w.placeholder))

    def test_stripe_color_follows_selected_issue(self):
        w = self.make()
        w.set_text("Привет, мир 25 ха ха")
        idle = str(w.detail_stripe.cget("bg"))
        colors = []
        for iid in w.tree.get_children():
            w.tree.selection_set(iid)
            w.root.update()
            colors.append(str(w.detail_stripe.cget("bg")))
        self.assertEqual(colors, [ui.C["auto"], ui.C["err"], ui.C["warn"]])
        w.set_text("")
        self.assertEqual(str(w.detail_stripe.cget("bg")), idle)

    def test_focus_changes_the_border_of_the_text(self):
        w = self.make()
        w.text.event_generate("<FocusIn>")
        self.assertEqual(str(w.text_frame.cget("bg")), ui.C["accent"])
        w.text.event_generate("<FocusOut>")
        self.assertEqual(str(w.text_frame.cget("bg")), ui.C["border"])

    def test_memo_collapses_and_expands_by_click(self):
        w = self.make()
        self.assertTrue(w.memo_open)  # на высоком экране памятка раскрыта
        self.assertTrue(self.mapped(w.memo_body))
        w.memo_title.event_generate("<Button-1>")
        self.assertFalse(w.memo_open)
        self.assertFalse(self.mapped(w.memo_body))
        self.assertEqual(w.memo_toggle.cget("text"), "показать")
        w.memo_toggle.event_generate("<Button-1>")
        self.assertTrue(w.memo_open)
        self.assertTrue(self.mapped(w.memo_body))
        self.assertEqual(w.memo_toggle.cget("text"), "скрыть")

    def test_button_hover(self):
        w = self.make()
        before = str(w.btn_fix.cget("bg"))
        w.btn_fix.event_generate("<Enter>")
        self.assertNotEqual(str(w.btn_fix.cget("bg")), before)
        w.btn_fix.event_generate("<Leave>")
        self.assertEqual(str(w.btn_fix.cget("bg")), before)

    def test_explanations_fit_into_the_card(self):
        """Пояснение не обрезается: карточка рассчитана на самое длинное из встречающихся и не прыгает при выборе строки."""
        from transcheck import selftest

        w = self.make()
        sources = [s for s, _ in selftest.EXAMPLES] + [s for s, _ in selftest.FLAGGED] + [
            "Привет, Мир! щас позвони по номеру +7 900 123 45 67 ха ха я по по пошел на youtube give me what I need pull me in вышел бл*** на бульвар ооо эээ ла ла ла",
        ]
        probe = tk_label_like(self.root, w)
        longest = 0
        for source in sources:
            w.set_text(source)
            for iid in w.tree.get_children():
                w.tree.selection_set(iid)
                w.root.update_idletasks()
                probe.configure(text=w.detail_var.get())
                longest = max(longest, probe.winfo_reqheight())
        probe.destroy()
        self.assertLessEqual(longest, w.detail.winfo_reqheight(), (longest, w.detail.winfo_reqheight()))

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
        self.assertEqual(tag_text(w.text, "hl_auto"), ["Привет"])

    def test_paste_event_refreshes(self):
        w = self.make()
        self.root.clipboard_clear()
        self.root.clipboard_append("Мир, привет")
        w.text.focus_force()
        w.text.event_generate("<<Paste>>")
        pump(self.root, 450)
        self.assertEqual(w.get_text(), "Мир, привет")
        self.assertEqual(tag_text(w.text, "hl_auto"), ["Мир,"])

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
        for tag in ("hl_error", "hl_warn", "hl_auto"):
            self.assertEqual(tag_ranges(w.text, tag), [])
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

    def clipped(self, w):
        """Элементы окна, которым дали меньше места, чем они просят. Список замечаний не считается: он может сжиматься."""
        self.root.update()
        pump(self.root, 100)
        return [
            (str(c), c.winfo_height(), c.winfo_reqheight())
            for c in self.root.winfo_children()
            if c.winfo_ismapped() and c is not w.tree.master and c.winfo_height() < c.winfo_reqheight()
        ]

    def test_everything_is_visible(self):
        """Последний элемент окна (памятка) целиком помещается в окно; ничего не обрезано."""
        w = self.make()
        w.set_text("Привет, Мир! щас 25 ха ха вышел бл*** на бульвар give me what I need")
        self.root.update()
        pump(self.root, 100)
        bottom = max(child.winfo_y() + child.winfo_height() for child in self.root.winfo_children())
        self.assertLessEqual(bottom, self.root.winfo_height(), (bottom, self.root.winfo_height()))
        self.assertEqual(self.clipped(w), [])  # окно может быть внутри экрана и всё равно обрезать подсказку, если ему дали мало места
        self.assertGreater(w.tree.winfo_height(), 60)  # список замечаний не сжат до нуля

    def test_small_window_squeezes_the_list_not_the_bottom(self):
        w = self.make()
        self.root.update_idletasks()
        need = self.root.winfo_reqheight()
        self.root.geometry(f"{self.root.winfo_width()}x{need - 90}")  # окно ниже, чем просит содержимое
        self.assertEqual(self.clipped(w), [])
        self.assertLess(w.tree.master.winfo_height(), w.tree.master.winfo_reqheight())  # сжался именно список

    def test_window_grows_when_fonts_are_larger(self):
        """Шрифт Windows выше, чем на машине разработчика: окно подстраивается, подсказки не обрезаны."""
        self.root.winfo_screenheight = lambda: 1080
        self.root.winfo_screenwidth = lambda: 1920
        w = self.make(font_extra=2)
        w.set_text("Привет, Мир! щас 25")
        self.assertEqual(self.clipped(w), [])  # с прежней раскладкой подсказка внизу оставалась высотой в одну строку
        # окно растёт до того, что просит содержимое, но не выше экрана (там сжимается список замечаний)
        self.assertGreaterEqual(self.root.winfo_height(), min(self.root.winfo_reqheight(), 1080 - 110) - 1)

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
        self.assertEqual(self.clipped(w), [])
        self.assertFalse(w.memo_open)  # места мало: памятка свёрнута, чтобы в списке осталось не меньше четырёх строк
        self.assertGreaterEqual(w.tree.winfo_height(), 4 * int(27 * w.k))

    def test_labels_rewrap_when_window_is_resized(self):
        w = self.make()
        self.root.geometry("900x800")
        pump(self.root, 100)
        self.assertGreater(int(str(w._memo_labels[0].cget("wraplength"))), 700)

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
