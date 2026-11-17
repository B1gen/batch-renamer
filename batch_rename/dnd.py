"""Windows Explorer drops onto tkinter widgets, plus path picking for those drops.

Drag-and-drop uses the shell WM_DROPFILES message so the app stays on the
standard library. Other platforms keep the browse buttons and ignore drops.
"""

from __future__ import annotations

import sys
from pathlib import Path

import tkinter as tk

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4

_HOOKS: dict[int, _Hook] = {}
_api_ready = False


class _Hook:
    def __init__(self) -> None:
        self.callback = None
        self.old = None
        self.wndproc = None


def folder_from_drop(paths: list[str | bytes]) -> str | None:
    """Pick a folder from a drop. Directories win; a file means its parent folder."""
    folders: list[Path] = []
    parents: list[Path] = []
    for raw in paths:
        text = _decode_dropped(raw)
        if not text:
            continue
        path = Path(text)
        try:
            is_dir = path.is_dir()
            is_file = path.is_file()
        except OSError:
            continue
        if is_dir:
            folders.append(path)
        elif is_file:
            parents.append(path.parent)
    chosen = folders[0] if folders else (parents[0] if parents else None)
    if chosen is None:
        return None
    return str(chosen.resolve()) if chosen.exists() else None


def hook_dropfiles(widget: tk.Widget, callback) -> bool:
    """Invoke callback(list[str]) on the Tk thread when files are dropped on widget."""
    if sys.platform != "win32":
        return False
    _ensure_api()
    try:
        widget.update_idletasks()
        hwnd = int(widget.winfo_id())
    except (tk.TclError, OSError, ValueError):
        return False

    def deliver(paths: list[str], cb=callback, target: tk.Widget = widget) -> None:
        copied = list(paths)
        try:
            target.after(0, lambda: cb(copied))
        except tk.TclError:
            pass

    try:
        first = hwnd not in _HOOKS
        _subclass(hwnd, deliver)
    except OSError:
        return False
    if first:
        widget.bind("<Destroy>", lambda _event, window=hwnd: _restore(window), add="+")
    return True


def _decode_dropped(value: str | bytes) -> str:
    if isinstance(value, bytes):
        for encoding in ("utf-8", "mbcs", "gbk"):
            try:
                text = value.decode(encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            text = value.decode("utf-8", "replace")
    else:
        text = str(value)
    return text.strip("\x00").strip()


def _ensure_api() -> None:
    global _api_ready
    if _api_ready:
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    pointer = ctypes.c_void_p
    is_64 = ctypes.sizeof(pointer) == 8
    get_long = user32.GetWindowLongPtrW if is_64 else user32.GetWindowLongW
    set_long = user32.SetWindowLongPtrW if is_64 else user32.SetWindowLongW
    for fn in (get_long, set_long):
        fn.argtypes = [wintypes.HWND, ctypes.c_int, pointer]
        fn.restype = pointer
    # GetWindowLong only takes two arguments; setting a third argtype makes
    # ctypes reject the call. Split them.
    get_long.argtypes = [wintypes.HWND, ctypes.c_int]
    set_long.argtypes = [wintypes.HWND, ctypes.c_int, pointer]

    user32.CallWindowProcW.argtypes = [
        pointer, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    ]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    ]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t

    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    shell32.DragAcceptFiles.restype = None
    shell32.DragQueryFileW.argtypes = [
        wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT,
    ]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragFinish.argtypes = [wintypes.HANDLE]
    shell32.DragFinish.restype = None

    _api_ready = True


def _user32():
    import ctypes
    return ctypes.windll.user32


def _shell32():
    import ctypes
    return ctypes.windll.shell32


def _set_window_proc(hwnd: int, proc):
    import ctypes
    user32 = _user32()
    set_long = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW
    ctypes.set_last_error(0)
    old = set_long(hwnd, GWLP_WNDPROC, proc)
    if not old and ctypes.get_last_error():
        raise OSError(ctypes.get_last_error(), "SetWindowLongPtr failed")
    return old


def _subclass(hwnd: int, callback) -> None:
    import ctypes
    from ctypes import wintypes

    existing = _HOOKS.get(hwnd)
    if existing is not None:
        existing.callback = callback
        return

    hook = _Hook()
    hook.callback = callback
    wndproc_type = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    )

    def wndproc(window, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            try:
                paths = _paths_from_hdrop(wparam)
            except Exception:
                paths = []
            finally:
                try:
                    _shell32().DragFinish(wparam)
                except Exception:
                    pass
            try:
                if hook.callback is not None:
                    hook.callback(paths)
            except Exception:
                pass
            return 0
        if hook.old:
            return _user32().CallWindowProcW(hook.old, window, msg, wparam, lparam)
        return _user32().DefWindowProcW(window, msg, wparam, lparam)

    hook.wndproc = wndproc_type(wndproc)
    hook.old = _set_window_proc(hwnd, ctypes.cast(hook.wndproc, ctypes.c_void_p))
    _shell32().DragAcceptFiles(hwnd, True)
    _HOOKS[hwnd] = hook


def _restore(hwnd: int) -> None:
    hook = _HOOKS.pop(int(hwnd), None)
    if hook is None or not hook.old:
        return
    try:
        _set_window_proc(hwnd, hook.old)
    except OSError:
        pass


def _paths_from_hdrop(hdrop) -> list[str]:
    import ctypes

    shell32 = _shell32()
    count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
    if not count or count > 10000:
        return []
    paths: list[str] = []
    for index in range(count):
        length = shell32.DragQueryFileW(hdrop, index, None, 0)
        if not length or length > 32768:
            continue
        buf = ctypes.create_unicode_buffer(length + 1)
        shell32.DragQueryFileW(hdrop, index, buf, length + 1)
        if buf.value:
            paths.append(buf.value)
    return paths
