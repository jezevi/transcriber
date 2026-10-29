"""Окно TransCheck (tkinter): текст, подсветка ошибок, список замечаний, кнопки."""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional, Sequence, Tuple

from . import VERSION
from . import rules_ru as R
from .rules_ru import ERROR, INFO, WARN, Analysis, Issue, Rule

try:  # winapi есть только в Windows; без него окно всё равно создаётся (удобно для разработки и тестов)
    from . import winapi
except ImportError:  # pragma: no cover
    winapi = None  # type: ignore[assignment]

C = {
    "bg": "#f1f3f7",
    "panel": "#ffffff",
    "fg": "#18212f",
    "muted": "#667085",
    "border": "#d5dae2",
    "border_strong": "#b6bfcc",
    "accent": "#2563eb",
    "accent_dark": "#1d4ed8",
    "accent_fg": "#ffffff",
    "accent_soft": "#e3ecff",
    "auto": "#1d4ed8",  # исправится само
    "auto_bg": "#dde8ff",
    "err": "#b42318",  # исправить вручную
    "err_bg": "#ffd5d0",
    "err_chip": "#fee4e2",
    "warn": "#93370d",  # проверить
    "warn_bg": "#ffe9a6",
    "warn_chip": "#fef0c7",
    "ok": "#157f3b",
    "sel_bg": "#b3cbfa",
    "btn": "#ffffff",
    "btn_hover": "#e8ecf3",
    "memo_bg": "#eaf1ff",
    "memo_border": "#cbdaf8",
}
FONT = ("Segoe UI", 10)
FONT_TEXT = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 11, "bold")
FONT_TITLE = ("Segoe UI", 15, "bold")

LEVEL_WORD = {ERROR: "Исправить", WARN: "Проверить", INFO: "Заметка"}
MEMO_TITLE = "Отметки в задании ставите вы сами"
MEMO_LINES = (
    "Иностранные слова или названия → галочка «В записи присутствуют иностранные слова».",
    "Английская фраза из 3+ слов, речь не на русском или ни одного слова не разобрать → поле пустое и отметка "
    "«Есть речь, которую невозможно транскрибировать».",
)
PLACEHOLDER = "Скопируйте текст из поля задания (Ctrl+A, затем Ctrl+C): он появится здесь сам.\nИли напечатайте его прямо в этом окне."
TREE_EMPTY = "Здесь появятся замечания к тексту"
DETAIL_IDLE = "Выберите замечание в списке: здесь появится пояснение, а двойной щелчок применит предложение."
DETAIL_NONE = "Пояснения появятся, когда в тексте найдутся замечания."
CHIP_TEMPLATES = ("Исправится само: {}", "Исправить вручную: {}", "Проверить: {}")


def pretty_hotkey(spec: str) -> str:
    names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win", "control": "Ctrl"}
    return "+".join(names.get(p.strip().lower(), p.strip().upper() if len(p.strip()) == 1 else p.strip().capitalize()) for p in spec.split("+"))


def _button(parent: tk.Misc, text: str, command: Callable[[], None], primary: bool = False, kind: Optional[str] = None) -> tk.Button:
    """Плоская кнопка с подсветкой при наведении. kind: primary (главная), secondary (обычная), ghost (без рамки)."""
    kind = kind or ("primary" if primary else "secondary")
    bg, fg, hover, edge = {
        "primary": (C["accent"], C["accent_fg"], C["accent_dark"], C["accent"]),
        "secondary": (C["btn"], C["fg"], C["btn_hover"], C["border_strong"]),
        "ghost": (C["bg"], C["muted"], C["btn_hover"], C["bg"]),
    }[kind]
    font = (FONT[0], FONT[1], "bold") if kind == "primary" else FONT_SMALL
    button = tk.Button(
        parent, text=text, command=command, font=font, bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
        relief="flat", bd=0, highlightthickness=1, highlightbackground=edge, highlightcolor=C["accent"],
        padx=14, pady=7 if kind == "primary" else 5, cursor="hand2",
    )
    button.bind("<Enter>", lambda _e: button.configure(bg=hover))
    button.bind("<Leave>", lambda _e: button.configure(bg=bg))
    return button


def _chip(parent: tk.Misc, bg: str, fg: str) -> Tuple[tk.StringVar, tk.Label]:
    var = tk.StringVar()
    return var, tk.Label(parent, textvariable=var, bg=bg, fg=fg, font=FONT_SMALL, padx=8, pady=2)


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
        width = min(int(620 * k), max(min_w, sw - 40))
        height = min(int(780 * k), max(min_h, sh - 110))
        x = max(0, sw - width - int(24 * k))
        y = max(0, min(int(30 * k), sh - height - 80))
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(min_w, min_h)
        root.protocol("WM_DELETE_WINDOW", self.minimize)

        pad = int(12 * k)
        self._pad = pad
        self._wrap_labels: List[tk.Label] = []
        self._memo_labels: List[tk.Label] = []
        self._style(root)

        # ── шапка ──
        accent_strip = tk.Frame(root, bg=C["accent"], height=max(3, int(3 * k)))
        head = tk.Frame(root, bg=C["panel"])
        head_in = tk.Frame(head, bg=C["panel"])
        head_in.pack(fill="x", padx=pad, pady=(int(10 * k), int(9 * k)))
        tk.Label(head_in, text="Проверка расшифровки", font=FONT_TITLE, bg=C["panel"], fg=C["fg"]).pack(anchor="w")
        tk.Label(head_in, text=f"по инструкции от {R.INSTRUCTION_DATE}  ·  версия {VERSION}", font=FONT_SMALL, bg=C["panel"], fg=C["muted"]).pack(anchor="w")
        tk.Frame(head, bg=C["border"], height=1).pack(fill="x")

        self.hint = tk.Label(
            root, justify="left", anchor="w", bg=C["bg"], fg=C["muted"], font=FONT_SMALL, wraplength=width - 2 * pad,
            text=(f"Горячие клавиши: {hotkeys_text}" if hotkeys_text else ""),
        )
        self._wrap_labels.append(self.hint)

        # ── поле для текста ──
        self.text_frame = tk.Frame(root, bg=C["border"])
        self.text = tk.Text(
            self.text_frame, wrap="word", height=7, width=1, relief="flat", bd=0, highlightthickness=0, bg=C["panel"], fg=C["fg"], font=FONT_TEXT,
            padx=10, pady=8, spacing1=1, spacing3=1, undo=True, insertbackground=C["fg"], insertwidth=2,
            selectbackground=C["sel_bg"], selectforeground=C["fg"],
        )
        scroll = ttk.Scrollbar(self.text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", padx=(0, 1), pady=1)
        self.text.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        # порядок создания = приоритет: выбранное выше ошибок, ошибки выше предупреждений, предупреждения выше «исправится само»
        self.text.tag_configure("hl_auto", background=C["auto_bg"])
        self.text.tag_configure("hl_warn", background=C["warn_bg"])
        self.text.tag_configure("hl_error", background=C["err_bg"])
        self.text.tag_configure("hl_sel", background=C["sel_bg"], underline=True)
        self.text.bind("<KeyRelease>", self._on_edit)
        self.text.bind("<<Paste>>", self._on_edit)
        self.text.bind("<<Cut>>", self._on_edit)
        self.text.bind("<Control-KeyPress>", self._ctrl_key)
        self.text.bind("<FocusIn>", lambda _e: self.text_frame.configure(bg=C["accent"]))  # рамка поля подсвечивается, когда в нём курсор
        self.text.bind("<FocusOut>", lambda _e: self.text_frame.configure(bg=C["border"]))
        self.placeholder = tk.Label(self.text, text=PLACEHOLDER, justify="left", anchor="nw", bg=C["panel"], fg=C["muted"], font=FONT_SMALL, cursor="xterm", bd=0, highlightthickness=0, padx=0, pady=0)
        self.placeholder.bind("<Button-1>", lambda _e: self.text.focus_set())

        # ── состояние и счётчики ──
        self.status = tk.Frame(root, bg=C["bg"])
        self.summary_var = tk.StringVar()
        self.summary = tk.Label(self.status, textvariable=self.summary_var, anchor="w", font=FONT_BOLD, bg=C["bg"], fg=C["muted"])
        self.summary.pack(side="left")
        self._chips: List[Tuple[tk.StringVar, tk.Label]] = [
            _chip(self.status, C["auto_bg"], C["auto"]),
            _chip(self.status, C["err_chip"], C["err"]),
            _chip(self.status, C["warn_chip"], C["warn"]),
        ]

        # ── список замечаний ──
        self.list_frame = tk.Frame(root, bg=C["border"])
        self.tree = ttk.Treeview(self.list_frame, columns=("lvl", "frag", "what"), show="headings", height=7, selectmode="browse", style="Issues.Treeview")
        self.tree.heading("lvl", text="Что делать", anchor="w")
        self.tree.heading("frag", text="Где", anchor="w")
        self.tree.heading("what", text="Правило", anchor="w")
        self.tree.column("lvl", width=int(104 * k), stretch=False)
        self.tree.column("frag", width=int(170 * k), stretch=False)
        self.tree.column("what", width=int(280 * k), stretch=True)
        self.tree.tag_configure("auto", foreground=C["auto"])
        self.tree.tag_configure(ERROR, foreground=C["err"])
        self.tree.tag_configure(WARN, foreground=C["warn"])
        self.tree.tag_configure(INFO, foreground=C["muted"])
        tscroll = ttk.Scrollbar(self.list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tscroll.set)
        tscroll.pack(side="right", fill="y", padx=(0, 1), pady=1)
        self.tree.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self.apply_selected())
        self.tree_empty = tk.Label(self.list_frame, text=TREE_EMPTY, bg=C["panel"], fg=C["muted"], font=FONT_SMALL)

        # ── пояснение к выбранному замечанию: карточка с цветной полосой слева ──
        self.detail_card = tk.Frame(root, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        self.detail_stripe = tk.Frame(self.detail_card, bg=C["border"], width=max(4, int(4 * k)))
        self.detail_stripe.pack(side="left", fill="y")
        self.detail_var = tk.StringVar(value=DETAIL_NONE)
        self.detail = tk.Label(
            self.detail_card, textvariable=self.detail_var, justify="left", anchor="nw", bg=C["panel"], fg=C["fg"], font=FONT_SMALL,
            wraplength=width - 2 * pad - int(34 * k), padx=10, pady=7, height=5,
        )
        self.detail.pack(side="left", fill="both", expand=True)

        # ── кнопки ──
        row1 = tk.Frame(root, bg=C["bg"])
        label = "Исправить безопасное и скопировать" + (f"  ({pretty_hotkey(fix_hotkey)})" if fix_hotkey else "")
        self.btn_fix = _button(row1, label, lambda: self.on_fix_copy(), primary=True)
        self.btn_fix.pack(side="left", fill="x", expand=True)
        self.btn_apply = _button(row1, "Применить выбранное", self.apply_selected)
        self.btn_apply.pack(side="left", fill="y", padx=(8, 0))

        row2 = tk.Frame(root, bg=C["bg"])
        for text_, command in (("Копировать", lambda: self.on_copy()), ("Очистить", self.clear)):
            _button(row2, text_, command).pack(side="left", padx=(0, 6))
        for text_, command in (("Выход", lambda: self.on_quit()), ("Самопроверка", lambda: self.on_selftest()), ("Свои правила", lambda: self.on_rules())):
            _button(row2, text_, command, kind="ghost").pack(side="right", padx=(2, 0))

        row3 = tk.Frame(root, bg=C["bg"])
        self.watch_var = tk.BooleanVar(value=bool(watch))
        self.topmost_var = tk.BooleanVar(value=bool(topmost))
        ttk.Checkbutton(
            row3, text="Подхватывать текст при копировании", variable=self.watch_var, style="Opt.TCheckbutton",
            command=lambda: self.on_watch(bool(self.watch_var.get())),
        ).pack(side="left")
        ttk.Checkbutton(row3, text="Поверх окон", variable=self.topmost_var, style="Opt.TCheckbutton", command=self._topmost_changed).pack(side="left", padx=(16, 0))

        self.note_var = tk.StringVar()
        self.note = tk.Label(root, textvariable=self.note_var, justify="left", anchor="w", bg=C["bg"], fg=C["muted"], font=FONT_SMALL, wraplength=width - 2 * pad)
        self._wrap_labels.append(self.note)

        # ── памятка: сворачивается, чтобы на невысоком экране оставалось место для списка замечаний ──
        self.memo = tk.Frame(root, bg=C["memo_bg"], highlightthickness=1, highlightbackground=C["memo_border"])
        self.memo_open = True
        self.memo_head = tk.Frame(self.memo, bg=C["memo_bg"], cursor="hand2")
        self.memo_head.pack(fill="x", padx=int(10 * k), pady=int(6 * k))
        self.memo_title = tk.Label(self.memo_head, anchor="w", bg=C["memo_bg"], fg=C["fg"], font=(FONT_SMALL[0], FONT_SMALL[1], "bold"), cursor="hand2")
        self.memo_title.pack(side="left")
        self.memo_toggle = tk.Label(self.memo_head, bg=C["memo_bg"], fg=C["accent"], font=FONT_SMALL, cursor="hand2")
        self.memo_toggle.pack(side="right")
        for part in (self.memo_head, self.memo_title, self.memo_toggle):
            part.bind("<Button-1>", lambda _e: self.set_memo(not self.memo_open))
        self.memo_body = tk.Frame(self.memo, bg=C["memo_bg"])
        for line in MEMO_LINES:
            item = tk.Frame(self.memo_body, bg=C["memo_bg"])
            item.pack(fill="x", pady=(0, int(3 * k)))
            tk.Label(item, text="•", bg=C["memo_bg"], fg=C["accent"], font=FONT_SMALL).pack(side="left", anchor="n")
            body = tk.Label(item, text=line, justify="left", anchor="w", bg=C["memo_bg"], fg=C["muted"], font=FONT_SMALL, wraplength=width - 2 * pad - int(50 * k))
            body.pack(side="left", fill="x", expand=True, padx=(5, 0))
            self._memo_labels.append(body)
        self.footer = self._memo_labels[0]
        self.set_memo(True)

        # ── раскладка. Нижние элементы упакованы раньше списка и прижаты вниз: если места не хватает, сжимается список замечаний,
        #    а пояснение, кнопки и памятка остаются целыми. ──
        accent_strip.pack(fill="x")
        head.pack(fill="x")
        self.hint.pack(fill="x", padx=pad, pady=(int(8 * k), int(4 * k)))
        self.text_frame.pack(fill="x", padx=pad)
        self.status.pack(fill="x", padx=pad, pady=(int(10 * k), int(4 * k)))
        self.memo.pack(side="bottom", fill="x", padx=pad, pady=(int(6 * k), pad))
        self.note.pack(side="bottom", fill="x", padx=pad, pady=(int(6 * k), 0))
        row3.pack(side="bottom", fill="x", padx=pad, pady=(int(8 * k), 0))
        row2.pack(side="bottom", fill="x", padx=pad, pady=(int(6 * k), 0))
        row1.pack(side="bottom", fill="x", padx=pad, pady=(int(10 * k), 0))
        self.detail_card.pack(side="bottom", fill="x", padx=pad, pady=(int(8 * k), 0))
        self.list_frame.pack(fill="both", expand=True, padx=pad)
        self.tree_empty.lift()

        # Шрифт и масштаб Windows могут сделать содержимое выше, чем рассчитано заранее. Если на экране не помещаются хотя бы четыре
        # строки списка, сначала сворачиваем памятку, потом делаем поле для текста ниже; окно не бывает выше экрана.
        available = max(min_h, sh - 110)
        row = int(27 * k)
        root.update_idletasks()
        if root.winfo_reqheight() - 3 * row > available:
            self.set_memo(False)
            root.update_idletasks()
        if root.winfo_reqheight() - 3 * row > available:
            self.text.configure(height=5)
            root.update_idletasks()
        need = root.winfo_reqheight()
        if need > height:
            height = min(need, available)
            y = max(0, min(int(30 * k), sh - height - 80))
            root.geometry(f"{width}x{height}+{x}+{y}")
        root.bind("<Configure>", self._on_resize)
        self.refresh()

    def set_memo(self, show: bool) -> None:
        self.memo_open = bool(show)
        self.memo_title.configure(text=("▾  " if show else "▸  ") + MEMO_TITLE)
        self.memo_toggle.configure(text="скрыть" if show else "показать")
        if show:
            self.memo_body.pack(fill="x", padx=int(10 * self.k), pady=(0, int(4 * self.k)))
        else:
            self.memo_body.pack_forget()

    def _style(self, root: tk.Tk) -> None:
        """Одна тема на всех системах: стили Windows (vista) не позволяют красить список и заголовки."""
        k = self.k
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Issues.Treeview", background=C["panel"], fieldbackground=C["panel"], foreground=C["fg"], rowheight=int(27 * k), font=FONT,
            borderwidth=0, relief="flat", lightcolor=C["panel"], darkcolor=C["panel"], bordercolor=C["panel"],
        )
        style.map("Issues.Treeview", background=[("selected", C["accent_soft"])], foreground=[("selected", C["fg"])])
        style.configure(
            "Issues.Treeview.Heading", font=FONT_SMALL, background=C["bg"], foreground=C["muted"], relief="flat", borderwidth=0,
            lightcolor=C["bg"], darkcolor=C["bg"], bordercolor=C["border"], padding=(int(8 * k), int(5 * k)),
        )
        style.map("Issues.Treeview.Heading", background=[("active", C["btn_hover"])])
        style.configure(
            "Vertical.TScrollbar", background=C["border"], troughcolor=C["bg"], bordercolor=C["bg"], lightcolor=C["border"],
            darkcolor=C["border"], arrowcolor=C["muted"], relief="flat", gripcount=0,
        )
        style.map("Vertical.TScrollbar", background=[("active", C["border_strong"])])
        style.configure("Opt.TCheckbutton", background=C["bg"], foreground=C["fg"], font=FONT_SMALL, focuscolor=C["bg"])
        style.map(
            "Opt.TCheckbutton", background=[("active", C["bg"])], indicatorbackground=[("selected", C["accent"]), ("!selected", C["panel"])],
            indicatorforeground=[("selected", C["accent_fg"])],
        )

    def _on_resize(self, event: tk.Event) -> None:
        """Подписи переносятся по ширине окна, когда его растягивают."""
        if event.widget is not self.root:
            return
        wrap = max(200, event.width - 2 * self._pad)
        for label in self._wrap_labels:
            label.configure(wraplength=wrap)
        for label in self._memo_labels:
            label.configure(wraplength=max(160, wrap - int(50 * self.k)))
        self.detail.configure(wraplength=max(160, wrap - int(34 * self.k)))

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
        self._update_placeholder()
        if event is not None and getattr(event, "type", None) is not None and str(event.type) == "KeyRelease" and self.get_text() == self._last_text:
            return  # стрелки, Shift и другие клавиши, не менявшие текст
        if self._refresh_job is not None:
            self.root.after_cancel(self._refresh_job)
        self._refresh_job = self.root.after(200, self.refresh)

    def _update_placeholder(self) -> None:
        """Серая подсказка в пустом поле: исчезает, как только в поле что-то появилось."""
        if self.text.get("1.0", "end-1c"):
            self.placeholder.place_forget()
        else:
            self.placeholder.place(x=0, y=1)  # Text сам добавляет к координатам свои внутренние отступы (padx, pady)
            self.placeholder.lift()

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
        for tag in ("hl_auto", "hl_warn", "hl_error", "hl_sel"):
            self.text.tag_remove(tag, "1.0", "end")
        astral = any(ord(c) > 0xFFFF for c in text)  # у Tk индексы символов за пределами BMP съезжают: без подсветки надёжнее
        for issue in issues:
            if issue.level == INFO or astral:
                continue
            tag = "hl_auto" if issue.auto else "hl_" + issue.level
            self.text.tag_add(tag, self._idx(issue.start), self._idx(issue.end))
        self.tree.delete(*self.tree.get_children())
        for n, issue in enumerate(issues):
            frag = _short(text[issue.start : issue.end], 24) or "·"
            title = R.CODE_TITLES.get(issue.code, issue.code) + (f" ({issue.section})" if issue.section else "")
            self.tree.insert(
                "", "end", iid=str(n), values=(LEVEL_WORD[issue.level] + (" ✓" if issue.auto else ""), frag, title),
                tags=("auto" if issue.auto else issue.level,),
            )
        self._set_detail(DETAIL_IDLE if issues else DETAIL_NONE, C["border"])
        if issues:
            self.tree_empty.place_forget()
        else:
            self.tree_empty.place(relx=0.5, rely=0.55, anchor="center")
            self.tree_empty.lift()
        self._update_placeholder()
        auto = sum(1 for i in issues if i.auto)
        manual = sum(1 for i in issues if i.level == ERROR and not i.auto)
        check = sum(1 for i in issues if i.level != ERROR and not i.auto)
        for (var, label), template, count in zip(self._chips, CHIP_TEMPLATES, (auto, manual, check)):
            label.pack_forget()
            var.set(template.format(count))
        for (var, label), count in zip(self._chips, (auto, manual, check)):
            if count:
                label.pack(side="left", padx=(8, 0))
        if not text.strip():
            self.summary_var.set("Текста пока нет")
            self.summary.configure(fg=C["muted"])
        elif not issues:
            self.summary_var.set("Замечаний нет")
            self.summary.configure(fg=C["ok"])
        else:
            self.summary_var.set(f"Замечаний: {len(issues)}")
            self.summary.configure(fg=C["err"] if manual else C["warn"] if check else C["auto"])
        if astral:
            self.note_set("В тексте есть эмодзи или редкие символы: подсветка отключена, список замечаний работает.")

    def _set_detail(self, message: str, stripe: str) -> None:
        self.detail_var.set(message)
        self.detail_stripe.configure(bg=stripe)

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
        stripe = C["auto"] if issue.auto else {ERROR: C["err"], WARN: C["warn"]}.get(issue.level, C["muted"])
        self._set_detail("\n".join(lines), stripe)

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
    box = tk.Text(win, wrap="word", font=("Consolas", 10), bg=C["panel"], fg=C["fg"], padx=10, pady=8, relief="flat", highlightthickness=1, highlightbackground=C["border"])
    box.insert("1.0", text)
    box.configure(state="disabled")
    bar = tk.Frame(win, bg=C["bg"])
    bar.pack(side="bottom", fill="x", padx=10, pady=10)
    box.pack(side="top", fill="both", expand=True, padx=10, pady=(10, 0))

    def copy_all() -> None:
        win.clipboard_clear()
        win.clipboard_append(text)
        win.update()

    _button(bar, "Копировать всё", copy_all, primary=True).pack(side="left")
    _button(bar, "Закрыть", win.destroy).pack(side="left", padx=8)
    return win
