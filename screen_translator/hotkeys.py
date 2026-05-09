from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

from PyQt5.QtCore import QAbstractNativeEventFilter, QByteArray


WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000


VK_ALIASES = {
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "SPACE": 0x20,
    "PGUP": 0x21,
    "PAGEUP": 0x21,
    "PGDN": 0x22,
    "PAGEDOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "INSERT": 0x2D,
    "INS": 0x2D,
    "DELETE": 0x2E,
    "DEL": 0x2E,
    "PRINTSCREEN": 0x2C,
    "PRTSC": 0x2C,
}

for index in range(1, 25):
    VK_ALIASES[f"F{index}"] = 0x70 + index - 1


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def parse_hotkey(shortcut: str) -> tuple[int, int]:
    parts = [part.strip().upper() for part in shortcut.split("+") if part.strip()]
    if not parts:
        raise ValueError("快捷键不能为空")

    modifiers = MOD_NOREPEAT
    key_code = 0
    for part in parts:
        if part in {"CTRL", "CONTROL"}:
            modifiers |= MOD_CONTROL
        elif part == "ALT":
            modifiers |= MOD_ALT
        elif part == "SHIFT":
            modifiers |= MOD_SHIFT
        elif part in {"WIN", "WINDOWS", "META"}:
            modifiers |= MOD_WIN
        elif len(part) == 1 and part.isalpha():
            key_code = ord(part)
        elif len(part) == 1 and part.isdigit():
            key_code = ord(part)
        elif part in VK_ALIASES:
            key_code = VK_ALIASES[part]
        else:
            raise ValueError(f"不支持的按键: {part}")

    if key_code == 0:
        raise ValueError("快捷键需要包含一个普通按键，例如 Ctrl+Alt+A")
    return modifiers, key_code


class GlobalHotkeyManager(QAbstractNativeEventFilter):
    def __init__(self) -> None:
        super().__init__()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._registered_ids: set[int] = set()

    def register(self, hotkey_id: int, shortcut: str, callback: Callable[[], None]) -> None:
        self.unregister(hotkey_id)
        modifiers, key_code = parse_hotkey(shortcut)
        ok = ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers, key_code)
        if not ok:
            raise RuntimeError(f"注册快捷键失败，可能已被占用: {shortcut}")
        self._registered_ids.add(hotkey_id)
        self._callbacks[hotkey_id] = callback

    def unregister(self, hotkey_id: int) -> None:
        if hotkey_id in self._registered_ids:
            ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
            self._registered_ids.discard(hotkey_id)
        self._callbacks.pop(hotkey_id, None)

    def unregister_all(self) -> None:
        for hotkey_id in list(self._registered_ids):
            self.unregister(hotkey_id)

    def nativeEventFilter(self, event_type: QByteArray, message: int) -> tuple[bool, int]:
        if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = ctypes.cast(int(message), ctypes.POINTER(MSG)).contents
            if msg.message == WM_HOTKEY:
                callback = self._callbacks.get(int(msg.wParam))
                if callback:
                    callback()
                    return True, 0
        return False, 0

