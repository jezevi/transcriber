"""Windows-специфика: буфер обмена, горячие клавиши, масштаб экрана, один экземпляр программы.

Программа НЕ нажимает клавиши в чужих окнах и не читает чужие окна: текст она берёт только из буфера обмена,
когда вы сами его скопировали. Модуль импортируется только в Windows. Все функции WinAPI описаны с явными типами
аргументов: без этого на 64-битной Windows указатели и дескрипторы обрезаются до 32 бит.
"""
from __future__ import annotations

import sys

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("transcheck.winapi работает только в Windows")

import ctypes
import ctypes.wintypes as wt
import queue
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import TransCheckError

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _sig(fn, restype, *argtypes):  # type: ignore[no-untyped-def]
    fn.restype = restype
    fn.argtypes = list(argtypes)


_sig(user32.OpenClipboard, wt.BOOL, wt.HWND)
_sig(user32.CloseClipboard, wt.BOOL)
_sig(user32.EmptyClipboard, wt.BOOL)
_sig(user32.GetClipboardData, wt.HANDLE, wt.UINT)
_sig(user32.SetClipboardData, wt.HANDLE, wt.UINT, wt.HANDLE)
_sig(user32.GetClipboardSequenceNumber, wt.DWORD)
_sig(kernel32.GlobalAlloc, wt.HGLOBAL, wt.UINT, ctypes.c_size_t)
_sig(kernel32.GlobalLock, ctypes.c_void_p, wt.HGLOBAL)
_sig(kernel32.GlobalUnlock, wt.BOOL, wt.HGLOBAL)
_sig(kernel32.GlobalFree, wt.HGLOBAL, wt.HGLOBAL)
_sig(user32.RegisterHotKey, wt.BOOL, wt.HWND, ctypes.c_int, wt.UINT, wt.UINT)
_sig(user32.UnregisterHotKey, wt.BOOL, wt.HWND, ctypes.c_int)
_sig(user32.GetMessageW, ctypes.c_int, ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
_sig(user32.PeekMessageW, wt.BOOL, ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT)
_sig(user32.PostThreadMessageW, wt.BOOL, wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM)
_sig(kernel32.GetCurrentThreadId, wt.DWORD)
_sig(user32.GetSystemMetrics, ctypes.c_int, ctypes.c_int)
_sig(kernel32.CreateMutexW, wt.HANDLE, ctypes.c_void_p, wt.BOOL, wt.LPCWSTR)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
ERROR_HOTKEY_ALREADY_REGISTERED = 1409
ERROR_ALREADY_EXISTS = 183

_KEEP: List[int] = []


def set_dpi_aware() -> None:
    """Нужно вызвать до создания окон: иначе при масштабе 125–150 % окно получается размытым."""
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = wt.BOOL
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def acquire_single_instance(name: str = "Local\\TransCheck_single_instance") -> bool:
    """True — мы первые. False — программа уже запущена."""
    handle = kernel32.CreateMutexW(None, False, name)
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    if handle:
        _KEEP.append(handle)  # держим дескриптор до конца процесса
    return not already


def message_box(title: str, text: str, icon: int = 0x40) -> None:
    """Системное окно с сообщением; не требует tkinter (нужно для ошибок на старте). icon: 0x10 — ошибка, 0x40 — информация."""
    try:
        user32.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
        user32.MessageBoxW.restype = ctypes.c_int
        user32.MessageBoxW(None, text, title, icon)
    except OSError:
        pass


def virtual_screen() -> Tuple[int, int, int, int]:
    """(x, y, ширина, высота) всех мониторов вместе; x и y могут быть отрицательными."""
    return (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77), user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))


# ── буфер обмена ──

def clipboard_seq() -> int:
    return int(user32.GetClipboardSequenceNumber())


def _open_clipboard(retries: int = 25, delay: float = 0.02) -> bool:
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(delay)
    return False


def get_clipboard_text() -> Optional[str]:
    """Текст из буфера или None, если там не текст (картинка, файлы) либо пусто."""
    if not _open_clipboard():
        raise TransCheckError("Буфер обмена занят другой программой. Повторите через секунду.")
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> None:
    data = text.replace("\x00", "").replace("\r\n", "\n").replace("\n", "\r\n")
    buf = ctypes.create_unicode_buffer(data)
    size = ctypes.sizeof(buf)
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        raise TransCheckError("Не хватило памяти, чтобы положить текст в буфер обмена.")
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        kernel32.GlobalFree(handle)
        raise TransCheckError("Не удалось подготовить буфер обмена.")
    ctypes.memmove(ptr, buf, size)
    kernel32.GlobalUnlock(handle)
    if not _open_clipboard():
        kernel32.GlobalFree(handle)
        raise TransCheckError("Буфер обмена занят другой программой. Повторите через секунду.")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise TransCheckError("Не удалось записать текст в буфер обмена.")
        # после успешного SetClipboardData память принадлежит системе: освобождать её нельзя
    finally:
        user32.CloseClipboard()


# ── горячие клавиши ──

class HotkeyThread(threading.Thread):
    """Отдельный поток с собственным циклом сообщений: RegisterHotKey привязывает клавиши к потоку."""

    def __init__(self, combos: Dict[str, Tuple[int, int]], out: "queue.Queue[Any]") -> None:
        super().__init__(daemon=True, name="transcheck-hotkeys")
        self.combos = combos
        self.out = out
        self.ready = threading.Event()
        self.error: Optional[str] = None
        self.thread_id = 0

    def run(self) -> None:
        self.thread_id = int(kernel32.GetCurrentThreadId())
        msg = wt.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0x0400, 0x0400, 0)  # создаёт очередь сообщений потока
        ids: Dict[int, str] = {}
        for i, (name, (mods, vk)) in enumerate(self.combos.items(), start=1):
            if not user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                err = ctypes.get_last_error()
                if err == ERROR_HOTKEY_ALREADY_REGISTERED:
                    self.error = (
                        f"Горячая клавиша для «{name}» уже занята другой программой. "
                        f"Измените «{name}» в config.json (например, ctrl+alt+h)."
                    )
                else:
                    self.error = f"Windows не дал зарегистрировать горячую клавишу «{name}» (код {err})."
                break
            ids[i] = name
        self.ready.set()
        if self.error:
            for i in ids:
                user32.UnregisterHotKey(None, i)
            return
        while True:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r <= 0:  # 0 — WM_QUIT, -1 — ошибка
                break
            if msg.message == WM_HOTKEY:
                hotkey = ids.get(int(msg.wParam))
                if hotkey:
                    self.out.put(hotkey)
        for i in ids:
            user32.UnregisterHotKey(None, i)

    def stop(self) -> None:
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


def start_hotkeys(combos: Dict[str, Tuple[int, int]], out: "queue.Queue[Any]") -> HotkeyThread:
    t = HotkeyThread(combos, out)
    t.start()
    if not t.ready.wait(3.0):
        raise TransCheckError("Не удалось запустить обработку горячих клавиш (нет ответа от Windows).")
    if t.error:
        raise TransCheckError(t.error)
    return t
