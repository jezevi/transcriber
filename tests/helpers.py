"""Общие вещи для тестов окна и приложения: заглушка модуля winapi и проверка наличия экрана."""
import gc
import queue
import time
import unittest

from transcheck.config import TransCheckError

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None  # type: ignore[assignment]


def have_display() -> bool:
    if tk is None:
        return False
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


class FakeThread:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class FakeWin:
    """Ведёт себя как transcheck.winapi: буфер обмена с номером изменений и регистрация горячих клавиш."""

    def __init__(self) -> None:
        self.text = None
        self.seq = 10
        self.busy = False
        self.combos = None
        self.queue = None
        self.thread = FakeThread()
        self.hotkey_error = None
        self.writes = []

    def clipboard_seq(self) -> int:
        return self.seq

    def get_clipboard_text(self):
        if self.busy:
            raise TransCheckError("Буфер обмена занят другой программой. Повторите через секунду.")
        return self.text

    def set_clipboard_text(self, text: str) -> None:
        if self.busy:
            raise TransCheckError("Буфер обмена занят другой программой. Повторите через секунду.")
        self.text = text
        self.seq += 2  # настоящий Windows тоже может изменить номер дважды: очистка и запись
        self.writes.append(text)

    def user_copies(self, text) -> None:
        """Пользователь сам скопировал текст (Ctrl+C в браузере)."""
        self.text = text
        self.seq += 1

    def start_hotkeys(self, combos, out: "queue.Queue"):
        if self.hotkey_error:
            raise TransCheckError(self.hotkey_error)
        self.combos = combos
        self.queue = out
        return self.thread

    def press(self, name: str) -> None:
        self.queue.put(name)


def pump(root, ms: int = 400) -> None:
    """Даёт Tk обработать события и отложенные вызовы."""
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        root.update()
        time.sleep(0.01)


class TkCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not have_display():
            raise unittest.SkipTest("нет tkinter или экрана")

    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self) -> None:
        try:
            for job in self.root.tk.splitlist(self.root.tk.call("after", "info")):
                self.root.after_cancel(job)  # отложенные вызовы не должны пережить окно
            self.root.destroy()
        except tk.TclError:
            pass
        self.root = None
        gc.collect()  # объекты Tk нужно освобождать в главном потоке
