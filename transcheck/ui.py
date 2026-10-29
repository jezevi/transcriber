"""Окно TransCheck (tkinter): текст, подсветка ошибок, список замечаний, кнопки."""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional, Sequence

from . import VERSION
from . import rules_ru as R
from .rules_ru import ERROR, INFO, WARN, Analysis, Issue, Rule

try:  # winapi есть только в Windows; без него окно всё равно создаётся (удобно для разработки и тестов)
    from . import winapi
except ImportError:  # pragma: no cover
    winapi = None  # type: ignore[assignment]

C = {
    "bg": "#f6f7f9",
    "panel": "#ffffff",
    "fg": "#1f2328",
    "muted": "#5b6470",
    "border": "#c3cad2",
    "err": "#b42318",
    "err_bg": "#ffd9d6",
    "warn": "#8a4b00",
    "warn_bg": "#ffeeb0",
    "sel_bg": "#b9d6ff",
    "ok": "#1a7f37",
    "btn": "#eceff3",
    "primary": "#1f6feb",
    "primary_fg": "#ffffff",
}
FONT = ("Segoe UI", 10)
FONT_TEXT = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 11, "bold")

LEVEL_WORD = {ERROR: "Исправить", WARN: "Проверить", INFO: "Заметка"}
FOOTER = (
    "Отметки в задании ставите вы сами. Иностранные слова или названия → галочка «В записи присутствуют иностранные слова». "
    "Английская фраза из 3+ слов, речь не на русском или ни одного слова не разобрать → поле пустое и отметка "
    "«Есть речь, которую невозможно транскрибировать»."
)


def pretty_hotkey(spec: str) -> str:
    names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win", "control": "Ctrl"}
    return "+".join(names.get(p.strip().lower(), p.strip().upper() if len(p.strip()) == 1 else p.strip().capitalize()) for p in spec.split("+"))


def _button(parent: tk.Misc, text: str, command: Callable[[], None], primary: bool = False) -> tk.Button:
    return tk.Button(
        parent, text=text, command=command, font=FONT_SMALL if not primary else ("Segoe UI", 10, "bold"),
        bg=C["primary"] if primary else C["btn"], fg=C["primary_fg"] if primary else C["fg"],
        activebackground=C["primary"] if primary else C["border"], activeforeground=C["primary_fg"] if primary else C["fg"],
        relief="flat" if primary else "groove", bd=1, padx=10, pady=5, cursor="hand2",
    )


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class MainWindow:
    """Главное окно. Обо всём внешнем (буфер обмена, файлы, выход) оно сообщает через функции, переданные в конструктор."""

    def __init__(
        self,
        root: tk.Tk,
        *,
        hotkeys_text: str = "",
        topmost: bool = True,
        watch: bool = True,
        on_fix_copy: Callable[[], None] = lambda: None,
        on_copy: Callable[[], None] = lambda: None,
        on_rules: Callable[[], None] = lambda: None,
        on_selftest: Callable[[], None] = lambda: None,
        on_quit: Callable[[], None] = lambda: None,
        on_watch: Callable[[bool], None] = lambda v: None,
        on_topmost: Callable[[bool], None] = lambda v: None,
        fix_hotkey: str = "",
    ) -> None:
        self.root = root
        self.on_fix_copy, self.on_copy, self.on_rules = on_fix_copy, on_copy, on_rules
        self.on_selftest, self.on_quit = on_selftest, on_quit
        self.on_watch, self.on_topmost = on_watch, on_topmost
        self.extra_rules: Sequence[Rule] = ()
        self.analysis: Analysis = R.analyze("")
        self._shown: List[Issue] = []  # замечания в том порядке, как они показаны в списке
        self._last_text = ""
        self._refresh_job: Optional[str] = None
        try:
            self.k = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)  # масштаб экрана: 1.0 = 100 %, 1.5 = 150 %
        except tk.TclError:
            self.k = 1.0
        k = self.k

        root.title(f"TransCheck {VERSION} — проверка расшифровки")
        root.configure(bg=C["bg"])
        root.attributes("-topmost", bool(topmost))
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        min_w, min_h = int(480 * k), int(580 * k)
        # окно не выше экрана: запас на заголовок окна и панель задач (при масштабе 150 % на экране 1080 пикселей высоты мало)
        width = min(int(600 * k), max(min_w, sw - 40))
        height = min(int(760 * k), max(min_h, sh - 110))
        x = max(0, sw - width - int(24 * k))
        y = max(0, min(int(30 * k), sh - height - 80))
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(min_w, min_h)
        root.protocol("WM_DELETE_WINDOW", self.minimize)

        pad = int(10 * k)
        head = tk.Frame(root, bg=C["bg"])
        head.pack(fill="x", padx=pad, pady=(pad, 0))
        tk.Label(head, text="Проверка расшифровки", font=("Segoe UI", 13, "bold"), bg=C["bg"], fg=C["fg"]).pack(side="left")
        tk.Label(head, text=f"инструкция от {R.INSTRUCTION_DATE}", font=FONT_SMALL, bg=C["bg"], fg=C["muted"]).pack(side="left", padx=(8, 0), pady=(4, 0))

        self._wrap_labels: List[tk.Label] = []
        self._pad = pad
        self.hint = tk.Label(
            root, justify="left", anchor="w", bg=C["bg"], fg=C["muted"], font=FONT_SMALL, wraplength=width - 2 * pad,
            text="Скопируйте текст из поля задания (Ctrl+A, затем Ctrl+C): он появится здесь сам. Можно печатать и прямо в этом окне."
            + (f"\nГорячие клавиши: {hotkeys_text}" if hotkeys_text else ""),
        )
        self.hint.pack(fill="x", padx=pad, pady=(4, 4))
        self._wrap_labels.append(self.hint)

        tf = tk.Frame(root, bg=C["border"])
        tf.pack(fill="x", padx=pad)
        self.text = tk.Text(
            tf, wrap="word", height=7, width=1, relief="flat", bd=0, highlightthickness=0, bg=C["panel"], fg=C["fg"], font=FONT_TEXT,
            padx=8, pady=6, undo=True, insertbackground=C["fg"], selectbackground="#9ec1ff", selectforeground=C["fg"],
        )
        scroll = ttk.Scrollbar(tf, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", padx=(0, 1), pady=1)
        self.text.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        # порядок создания = приоритет: выбранное выше ошибок, ошибки выше предупреждений
        self.text.tag_configure("hl_warn", background=C["warn_bg"])
        self.text.tag_configure("hl_error", background=C["err_bg"])
        self.text.tag_configure("hl_sel", background=C["sel_bg"], underline=True)
        self.text.bind("<KeyRelease>", self._on_edit)
        self.text.bind("<<Paste>>", self._on_edit)
        self.text.bind("<<Cut>>", self._on_edit)
        self.text.bind("<Control-KeyPress>", self._ctrl_key)

        self.summary_var = tk.StringVar()
        self.summary = tk.Label(root, textvariable=self.summary_var, anchor="w", font=FONT_BOLD, bg=C["bg"], fg=C["muted"])
        self.summary.pack(fill="x", padx=pad, pady=(8, 2))

        style = ttk.Style(root)
        try:
            style.theme_use("vista" if sys.platform == "win32" else "clam")
        except tk.TclError:
            pass
        style.configure("Issues.Treeview", rowheight=int(24 * k), font=FONT)
        style.configure("Issues.Treeview.Heading", font=FONT_SMALL)
        lf = tk.Frame(root, bg=C["border"])
        lf.pack(fill="both", expand=True, padx=pad)
        self.tree = ttk.Treeview(lf, columns=("lvl", "frag", "what"), show="headings", height=7, selectmode="browse", style="Issues.Treeview")
        self.tree.heading("lvl", text="Что делать")
        self.tree.heading("frag", text="Где")
        self.tree.heading("what", text="Правило")
        self.tree.column("lvl", width=int(90 * k), stretch=False)
        self.tree.column("frag", width=int(170 * k), stretch=False)
        self.tree.column("what", width=int(280 * k), stretch=True)
        self.tree.tag_configure(ERROR, foreground=C["err"])
        self.tree.tag_configure(WARN, foreground=C["warn"])
        tscroll = ttk.Scrollbar(lf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tscroll.set)
        tscroll.pack(side="right", fill="y", padx=(0, 1), pady=1)
        self.tree.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self.apply_selected())

        self.detail_var = tk.StringVar(value="Выберите замечание в списке: здесь появится пояснение, а двойной щелчок применит предложение.")
        self.detail = tk.Label(
            root, textvariable=self.detail_var, justify="left", anchor="nw", bg=C["panel"], fg=C["fg"], font=FONT_SMALL,
            wraplength=width - 2 * pad - 16, padx=8, pady=6, relief="solid", bd=1, height=5,
        )
        self.detail.pack(fill="x", padx=pad, pady=(6, 0))

        row1 = tk.Frame(root, bg=C["bg"])
        row1.pack(fill="x", padx=pad, pady=(8, 0))
        label = "Исправить безопасное и скопировать" + (f"  ({pretty_hotkey(fix_hotkey)})" if fix_hotkey else "")
        self.btn_fix = _button(row1, label, lambda: self.on_fix_copy(), primary=True)
        self.btn_fix.pack(side="left", fill="x", expand=True)
        self.btn_apply = _button(row1, "Применить выбранное", self.apply_selected)
        self.btn_apply.pack(side="left", padx=(6, 0))

        row2 = tk.Frame(root, bg=C["bg"])
        row2.pack(fill="x", padx=pad, pady=(6, 0))
        for label, command in (
            ("Копировать", lambda: self.on_copy()),
            ("Очистить", self.clear),
            ("Свои правила", lambda: self.on_rules()),
            ("Самопроверка", lambda: self.on_selftest()),
            ("Выход", lambda: self.on_quit()),
        ):
            _button(row2, label, command).pack(side="left", padx=(0, 6))

        row3 = tk.Frame(root, bg=C["bg"])
        row3.pack(fill="x", padx=pad, pady=(6, 0))
        self.watch_var = tk.BooleanVar(value=bool(watch))
        self.topmost_var = tk.BooleanVar(value=bool(topmost))
        tk.Checkbutton(
            row3, text="Подхватывать текст при копировании", variable=self.watch_var, bg=C["bg"], font=FONT_SMALL, activebackground=C["bg"],
            command=lambda: self.on_watch(bool(self.watch_var.get())),
        ).pack(side="left")
        tk.Checkbutton(
            row3, text="Поверх окон", variable=self.topmost_var, bg=C["bg"], font=FONT_SMALL, activebackground=C["bg"], command=self._topmost_changed,
        ).pack(side="left", padx=(12, 0))

        self.note_var = tk.StringVar()
        self.note = tk.Label(root, textvariable=self.note_var, justify="left", anchor="w", bg=C["bg"], fg=C["muted"], font=FONT_SMALL, wraplength=width - 2 * pad)
        self.note.pack(fill="x", padx=pad, pady=(6, 0))
        self.footer = tk.Label(root, text=FOOTER, justify="left", anchor="w", bg=C["bg"], fg=C["muted"], font=FONT_SMALL, wraplength=width - 2 * pad)
        self.footer.pack(fill="x", padx=pad, pady=(4, pad))
        self._wrap_labels += [self.note, self.footer]
        root.bind("<Configure>", self._on_resize)
        self.refresh()

    def _on_resize(self, event: tk.Event) -> None:
        """Подписи переносятся по ширине окна, когда его растягивают."""
        if event.widget is not self.root:
            return
        wrap = max(200, event.width - 2 * self._pad)
        for label in self._wrap_labels:
            label.configure(wraplength=wrap)
        self.detail.configure(wraplength=wrap - 16)

    # ── текст ──
    def get_text(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set_text(self, text: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.edit_reset()
        self.refresh()

    def clear(self) -> None:
        self.set_text("")
        self.note_set("")

    def set_extra_rules(self, rules: Sequence[Rule]) -> None:
        self.extra_rules = tuple(rules)
        self.refresh()

    def note_set(self, message: str, kind: str = "info") -> None:
        self.note_var.set(message)
        self.note.configure(fg={"ok": C["ok"], "error": C["err"]}.get(kind, C["muted"]))

    # ── разбор и показ ──
    def _on_edit(self, event: Optional[tk.Event] = None) -> None:
        if event is not None and getattr(event, "type", None) is not None and str(event.type) == "KeyRelease" and self.get_text() == self._last_text:
            return  # стрелки, Shift и другие клавиши, не менявшие текст
        if self._refresh_job is not None:
            self.root.after_cancel(self._refresh_job)
        self._refresh_job = self.root.after(200, self.refresh)

    def _ctrl_key(self, event: tk.Event) -> Optional[str]:
        """В русской раскладке Tk не узнаёт Ctrl+C/V/X/A/Z (клавиша приходит как кириллическая буква). В Windows код
        физической клавиши от раскладки не зависит, поэтому разбираем его сами."""
        if sys.platform != "win32":
            return None
        actions = {
            65: lambda: self.text.tag_add("sel", "1.0", "end-1c"),
            67: lambda: self.text.event_generate("<<Copy>>"),
            86: lambda: self.text.event_generate("<<Paste>>"),
            88: lambda: self.text.event_generate("<<Cut>>"),
            90: lambda: self._undo(),
        }
        action = actions.get(event.keycode)
        if action is None:
            return None
        action()
        return "break"

    def _undo(self) -> None:
        try:
            self.text.edit_undo()
        except tk.TclError:
            return
        self._on_edit()

    def refresh(self) -> None:
        self._refresh_job = None
        text = self.get_text()
        self._last_text = text
        self.analysis = R.analyze(text, self.extra_rules)
        issues = self.analysis.issues
        self._shown = list(issues)
        for tag in ("hl_warn", "hl_error", "hl_sel"):
            self.text.tag_remove(tag, "1.0", "end")
        astral = any(ord(c) > 0xFFFF for c in text)  # у Tk индексы символов за пределами BMP съезжают: без подсветки надёжнее
        for issue in issues:
            if issue.level != INFO and not astral:
                self.text.tag_add("hl_" + issue.level, self._idx(issue.start), self._idx(issue.end))
        self.tree.delete(*self.tree.get_children())
        for n, issue in enumerate(issues):
            frag = _short(text[issue.start : issue.end], 24) or "·"
            title = R.CODE_TITLES.get(issue.code, issue.code) + (f" ({issue.section})" if issue.section else "")
            self.tree.insert("", "end", iid=str(n), values=(LEVEL_WORD[issue.level] + (" ✓" if issue.auto else ""), frag, title), tags=(issue.level,))
        self.detail_var.set(
            "Выберите замечание в списке: здесь появится пояснение, а двойной щелчок применит предложение." if issues else ""
        )
        a = self.analysis
        autos = len(a.auto_issues)
        if not text.strip():
            self.summary_var.set("Текста пока нет")
            self.summary.configure(fg=C["muted"])
        elif not issues:
            self.summary_var.set("Замечаний нет")
            self.summary.configure(fg=C["ok"])
        else:
            parts = [f"исправить: {a.errors}", f"проверить: {a.warnings}"]
            if autos:
                parts.append(f"исправится само: {autos}")
            self.summary_var.set("Замечания — " + ", ".join(parts))
            self.summary.configure(fg=C["err"] if a.errors else C["warn"])
        if astral:
            self.note_set("В тексте есть эмодзи или редкие символы: подсветка отключена, список замечаний работает.")

    def _idx(self, n: int) -> str:
        return f"1.0+{n}c"

    def selected_issue(self) -> Optional[Issue]:
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return self._shown[int(sel[0])]
        except (ValueError, IndexError):
            return None

    def _on_select(self, event: Optional[tk.Event] = None) -> None:
        self.text.tag_remove("hl_sel", "1.0", "end")
        issue = self.selected_issue()
        if issue is None:
            return
        if not any(ord(c) > 0xFFFF for c in self.get_text()):
            self.text.tag_add("hl_sel", self._idx(issue.start), self._idx(issue.end))
            self.text.see(self._idx(issue.start))
        lines = [issue.message]
        if issue.suggestion is not None:
            lines.append("Предложение: " + ("убрать это место" if issue.suggestion == "" else f"«{issue.suggestion}»"))
            lines.append("Это исправится кнопкой «Исправить безопасное»." if issue.auto else "Само не исправляется. Двойной щелчок по строке или «Применить выбранное» применит предложение.")
        else:
            lines.append("Предложения нет: здесь решение за вами.")
        if issue.section:
            lines.append(f"Где в инструкции: {issue.section}.")
        self.detail_var.set("\n".join(lines))

    def apply_selected(self) -> None:
        issue = self.selected_issue()
        if issue is None:
            self.note_set("Сначала выберите замечание в списке.")
            return
        if issue.suggestion is None:
            self.note_set("У этого замечания нет предложения: исправьте текст сами.")
            return
        self.set_text(R.apply_issue(self.get_text(), issue))
        self.note_set("Предложение применено. Проверьте результат и при необходимости поправьте.", "ok")

    def fix_safe(self) -> str:
        """Применяет все безопасные исправления к тексту в окне и возвращает результат."""
        fixed = R.fix_all(self.get_text(), self.extra_rules)
        self.set_text(fixed)
        return fixed

    # ── окно ──
    def show(self) -> None:
        """Показать окно, не забирая фокус у программы, в которой вы работаете."""
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError:
            pass

    def minimize(self) -> None:
        self.root.iconify()

    def _topmost_changed(self) -> None:
        value = bool(self.topmost_var.get())
        self.root.attributes("-topmost", value)
        self.on_topmost(value)


def show_report(root: tk.Misc, title: str, text: str) -> tk.Toplevel:
    """Окно с текстом отчёта и кнопкой «Копировать всё»."""
    win = tk.Toplevel(root)
    win.title(title)
    try:
        k = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except tk.TclError:
        k = 1.0
    win.geometry(f"{int(680 * k)}x{int(520 * k)}")
    win.configure(bg=C["bg"])
    box = tk.Text(win, wrap="word", font=("Consolas", 10), bg=C["panel"], fg=C["fg"], padx=8, pady=6, relief="flat")
    box.insert("1.0", text)
    box.configure(state="disabled")
    bar = tk.Frame(win, bg=C["bg"])
    bar.pack(side="bottom", fill="x", padx=8, pady=8)
    box.pack(side="top", fill="both", expand=True, padx=8, pady=(8, 0))

    def copy_all() -> None:
        win.clipboard_clear()
        win.clipboard_append(text)
        win.update()

    _button(bar, "Копировать всё", copy_all).pack(side="left")
    _button(bar, "Закрыть", win.destroy).pack(side="left", padx=6)
    return win
