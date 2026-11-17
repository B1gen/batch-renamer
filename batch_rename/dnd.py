"""Folder drag-and-drop support backed by tkinterdnd2.

The extension owns the native drag-and-drop integration, avoiding custom
Windows window-procedure hooks that can crash Tk applications.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import tkinter as tk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # Allows importing core code when the optional UI package is absent.
    DND_FILES = None
    TkinterDnD = None


def create_root() -> tk.Tk:
    """Create a Tk root with native drop support when tkinterdnd2 is installed."""
    if TkinterDnD is not None:
        return TkinterDnD.Tk()
    return tk.Tk()


def drag_drop_available() -> bool:
    return DND_FILES is not None


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


def hook_dropfiles(widget: tk.Widget, callback: Callable[[list[str]], None]) -> bool:
    """Call *callback* on the Tk thread when files are dropped onto *widget*."""
    if DND_FILES is None:
        return False

    def on_drop(event: tk.Event) -> str:
        try:
            paths = list(widget.tk.splitlist(event.data))
        except tk.TclError:
            paths = []
        callback(paths)
        return "break"

    try:
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", on_drop)
    except tk.TclError:
        return False
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
