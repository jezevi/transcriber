"""Управление программой: слежение за буфером обмена, горячие клавиши, правила, запуск."""
from __future__ import annotations

import os
import queue
import sys
import traceback
from typing import Any, Callable, Optional

from . import config, rules_ru
from .config import TransCheckError


class Controller:
    """Всё, что связывает окно с Windows. Модуль winapi передаётся снаружи, поэтому логику можно проверять без Windows."""

    POLL_MS = 250
    BUSY_RETRIES = 8  # сколько шагов опроса (по 0,25 с) ждать, пока другая программа освободит буфер обмена

    def __init__(
        self,
        root: Any,
        directory: str,
        winapi_mod: Any,
        *,
        opener: Optional[Callable[[str], None]] = None,
        window_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        from . import ui

        self.root = root
        self.directory = directory
        self.win = winapi_mod
        self.cfg = config.load_config(directory)
        combos = config.parse_all_hotkeys(self.cfg)
        config.ensure_rules_extra(directory)
        self.opener = opener or _default_opener
        self.events: "queue.Queue[Any]" = queue.Queue()
        self.closing = False
        self._after_id: Optional[str] = None
        self._own_seq: Optional[int] = None
        self._busy_retries = 0
        self._last_seq: Optional[int] = winapi_mod.clipboard_seq()  # то, что лежало в буфере до запуска, не подхватываем
        self._rules_mtime: Optional[float] = None
        self._rules_problems: list = []

        hotkeys_text = "   ".join(
            f"{ui.pretty_hotkey(str(self.cfg[name]))} — {label}"
            for name, label in (("hotkey_check", "взять текст из буфера"), ("hotkey_fix", "исправить и скопировать"), ("hotkey_quit", "выход"))
        )
        factory = window_factory or ui.MainWindow
        self.ui = factory(
            root,
            hotkeys_text=hotkeys_text,
            fix_hotkey=str(self.cfg["hotkey_fix"]),
            topmost=bool(self.cfg["topmost"]),
            watch=bool(self.cfg["watch_clipboard"]),
            on_fix_copy=self.fix_and_copy,
            on_copy=self.copy_current,
            on_rules=self.open_rules,
            on_selftest=self.run_selftest,
            on_quit=self.quit,
            on_watch=self._watch_changed,
            on_topmost=self._topmost_changed,
        )
        self.hotkey_thread = winapi_mod.start_hotkeys(combos, self.events)
        self._reload_rules()
        self._after_id = root.after(self.POLL_MS, self._poll)

    # ── цикл опроса: горячие клавиши, буфер обмена, файл правил ──
    def _poll(self) -> None:
        if self.closing:
            return
        try:
            while True:
                name = self.events.get_nowait()
                self._dispatch(name)
        except queue.Empty:
            pass
        except Exception as e:  # сбой обработчика не должен останавливать опрос
            self.ui.note_set(f"Ошибка: {e}", "error")
        try:
            self._watch_clipboard()
            self._reload_rules()
        except Exception as e:
            self.ui.note_set(f"Ошибка: {e}", "error")
        if not self.closing:
            self._after_id = self.root.after(self.POLL_MS, self._poll)

    def _dispatch(self, name: str) -> None:
        if name == "hotkey_check":
            self.take_clipboard(force=True)
            self.ui.show()
        elif name == "hotkey_fix":
            self.fix_and_copy()
        elif name == "hotkey_quit":
            self.quit()

    # ── буфер обмена ──
    def _app_has_focus(self) -> bool:
        try:
            return self.root.focus_displayof() is not None
        except Exception:
            return False

    def _watch_clipboard(self) -> None:
        if not self.ui.watch_var.get():
            self._last_seq = self.win.clipboard_seq()
            return
        seq = self.win.clipboard_seq()
        if seq == self._last_seq:
            return
        if self._own_seq is not None and seq == self._own_seq:
            self._last_seq = seq  # это записали мы сами
            return
        if self._app_has_focus():
            self._last_seq = seq  # копирование внутри окна TransCheck не должно подменять текст
            return
        if self.take_clipboard(force=False) or self._busy_retries >= self.BUSY_RETRIES:
            self._last_seq = seq  # прочитали (или перестали пытаться); иначе повторим на следующем шаге опроса
            self._busy_retries = 0
        else:
            self._busy_retries += 1

    def take_clipboard(self, force: bool) -> bool:
        """Берёт текст из буфера обмена в окно. False — буфер занят другой программой, можно повторить позже."""
        try:
            text = self.win.get_clipboard_text()
        except TransCheckError as e:
            self.ui.note_set(str(e), "error")
            return False
        if text is None:
            if force:
                self.ui.note_set("В буфере обмена нет текста. Скопируйте текст из поля задания: Ctrl+A, затем Ctrl+C.", "error")
            return True
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        limit = int(self.cfg["max_chars"])  # type: ignore[call-overload]
        if len(text) > limit:
            self.ui.note_set(f"В буфере {len(text)} символов — это слишком много для расшифровки (предел {limit}), текст не взят.", "error")
            return True
        if text == self.ui.get_text():
            return True
        self.ui.set_text(text)
        self.ui.note_set("Текст взят из буфера обмена.")
        return True

    def copy_current(self) -> None:
        text = self.ui.get_text()
        if not text:
            self.ui.note_set("Копировать нечего: текста нет.", "error")
            return
        if self._write_clipboard(text):
            self.ui.note_set("Текст скопирован. В поле задания: Ctrl+A, затем Ctrl+V.", "ok")

    def fix_and_copy(self) -> None:
        if not self.ui.get_text().strip():
            self.ui.note_set("Текста нет: скопируйте текст из поля задания (Ctrl+A, затем Ctrl+C).", "error")
            return
        before = self.ui.get_text()
        fixed = self.ui.fix_safe()
        if not self._write_clipboard(fixed):
            return
        left = self.ui.analysis
        rest = left.errors + left.warnings
        changed = "Исправлено и скопировано." if fixed != before else "Автоматически исправлять было нечего, текст скопирован как есть."
        if rest:
            self.ui.note_set(f"{changed} Осталось на вашей проверке: {rest}. Посмотрите список, потом вставьте текст в поле: Ctrl+A, Ctrl+V.", "error")
        else:
            self.ui.note_set(f"{changed} Замечаний нет. В поле задания: Ctrl+A, затем Ctrl+V.", "ok")

    def _write_clipboard(self, text: str) -> bool:
        """True, если текст лежит в буфере обмена. При неудаче в окне остаётся честное объяснение."""
        try:
            self.win.set_clipboard_text(text)
        except TransCheckError as e:
            self.ui.note_set(f"Текст в окне исправлен, но в буфер обмена он не попал: {e} Нажмите «Копировать» ещё раз.", "error")
            return False
        self._own_seq = self.win.clipboard_seq()
        self._last_seq = self._own_seq
        return True

    # ── свои правила ──
    def _reload_rules(self) -> None:
        path = config.rules_extra_path(self.directory)
        try:
            mtime: Optional[float] = os.path.getmtime(path)
        except OSError:
            mtime = None
        current = mtime if mtime is not None else -1.0
        if self._rules_mtime is not None and current == self._rules_mtime:
            return
        first = self._rules_mtime is None
        self._rules_mtime = current
        try:
            text = config.read_rules_extra(self.directory)
        except TransCheckError as e:
            self.ui.set_extra_rules(())
            self.ui.note_set(str(e), "error")
            return
        rules, problems = rules_ru.parse_extra_rules(text)
        self.ui.set_extra_rules(rules)
        if problems:
            self.ui.note_set("Свои правила: " + "; ".join(problems[:3]), "error")
        elif not first:
            self.ui.note_set(f"Свои правила обновлены ({len(rules)}).", "ok")

    def open_rules(self) -> None:
        path = config.ensure_rules_extra(self.directory)
        try:
            self.opener(path)
        except Exception as e:
            self.ui.note_set(f"Не удалось открыть файл {path}: {e}", "error")

    # ── настройки окна ──
    def _watch_changed(self, value: bool) -> None:
        self.ui.note_set("Текст подхватывается при копировании." if value else "Автоподхват выключен: текст берётся клавишей «взять текст из буфера».")

    def _topmost_changed(self, value: bool) -> None:
        pass

    # ── самопроверка ──
    def run_selftest(self) -> None:
        from . import selftest, ui

        results = selftest.run_all(self.directory, gui=False, hotkeys_free=False, winapi_mod=self.win)
        ui.show_report(self.root, "TransCheck: самопроверка", selftest.format_report(results))
        # проверка записи в буфер могла изменить его: не принимаем это за копирование пользователя
        self._last_seq = self.win.clipboard_seq()

    # ── выход ──
    def quit(self) -> None:
        if self.closing:
            return
        self.closing = True
        try:
            self.hotkey_thread.stop()
        except Exception:
            pass
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
        self.root.destroy()


def _default_opener(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
    else:  # pragma: no cover
        raise OSError("открыть файл можно только в Windows")


def logging_flush() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.flush()
        except (OSError, ValueError):
            pass


def main(argv: Optional[list] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    directory = config.app_dir()
    if "--selftest" in args:
        from . import selftest

        return selftest.main(args)
    if sys.platform != "win32":
        print("TransCheck работает только в Windows. Проверку правил можно запустить так: python run.py --selftest")
        return 2
    from . import winapi

    try:
        winapi.set_dpi_aware()
        if not winapi.acquire_single_instance():
            winapi.message_box("TransCheck", "TransCheck уже запущен. Его окно можно найти на панели задач.")
            return 0
        import tkinter as tk

        root = tk.Tk()
        try:
            Controller(root, directory, winapi)
        except TransCheckError as e:
            root.destroy()
            winapi.message_box("TransCheck: не удалось запустить", str(e), 0x10)
            return 1
        root.mainloop()
        # Выходим сразу, не дожидаясь обычного завершения интерпретатора: иначе сборщик мусора может освободить
        # объекты tkinter из чужого потока, и Tcl аварийно завершает процесс (окно «программа не отвечает»).
        logging_flush()
        os._exit(0)
    except Exception:
        text = traceback.format_exc()
        try:
            with open(os.path.join(directory, "transcheck_crash.log"), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass
        winapi.message_box(
            "TransCheck: сбой при запуске",
            "Программа не смогла запуститься. Подробности в файле transcheck_crash.log рядом с программой.\n\n" + text[-600:],
            0x10,
        )
        return 1
