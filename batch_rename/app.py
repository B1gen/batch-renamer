from __future__ import annotations

import ctypes
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .core import (
    STATUS_CONFLICT,
    STATUS_INVALID,
    STATUS_OK,
    STATUS_UNCHANGED,
    PlanItem,
    Rules,
    build_plan,
    execute_plan,
    parse_extensions,
    scan_files,
    undo,
)

APP_TITLE = "Batch Rename"
PREVIEW_DELAY_MS = 150
MAX_ROWS = 5000

STATUS_LABELS = {
    STATUS_OK: "将修改",
    STATUS_UNCHANGED: "不变",
    STATUS_CONFLICT: "冲突",
    STATUS_INVALID: "无效",
}


class BatchRenameApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.files: list[Path] = []
        self.plan: list[PlanItem] = []
        self.history: list[list[tuple[Path, Path]]] = []
        self._preview_job: str | None = None
        self._scan_job: str | None = None

        root.title(f"{APP_TITLE} {__version__}")
        root.geometry("1180x720")
        root.minsize(900, 560)
        self._setup_style()

        self.source_dir = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.ext_filter = tk.StringVar()
        self.add_prefix = tk.StringVar()
        self.remove_prefix = tk.StringVar()
        self.add_suffix = tk.StringVar()
        self.remove_suffix = tk.StringVar()
        self.find_text = tk.StringVar()
        self.replace_text = tk.StringVar()
        self.move_enabled = tk.BooleanVar(value=False)
        self.target_dir = tk.StringVar()
        self.keep_structure = tk.BooleanVar(value=False)
        self.only_changed = tk.BooleanVar(value=False)
        self.summary = tk.StringVar(value="请选择一个文件夹开始")

        self._build_ui()

        for var in (self.source_dir, self.recursive, self.ext_filter):
            var.trace_add("write", lambda *_: self._schedule_scan())
        for var in (
            self.add_prefix, self.remove_prefix, self.add_suffix, self.remove_suffix,
            self.find_text, self.replace_text, self.keep_structure, self.only_changed,
        ):
            var.trace_add("write", lambda *_: self._schedule_preview())
        # Moving into a folder inside the source tree changes which files are scanned.
        for var in (self.move_enabled, self.target_dir):
            var.trace_add("write", lambda *_: self._schedule_scan())
        self.move_enabled.trace_add("write", lambda *_: self._sync_move_state())
        self._sync_move_state()

    def _setup_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview", rowheight=24)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Accent.TButton", padding=(14, 6))

    # ---------- layout ----------

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        source = ttk.LabelFrame(outer, text="源文件夹", padding=8)
        source.pack(fill=tk.X)
        ttk.Entry(source, textvariable=self.source_dir).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(source, text="浏览…", command=self._browse_source).grid(row=0, column=1)
        ttk.Button(source, text="刷新", command=self._rescan).grid(row=0, column=2, padx=(6, 0))
        options = ttk.Frame(source)
        options.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(options, text="包含子文件夹", variable=self.recursive).pack(side=tk.LEFT)
        ttk.Label(options, text="    只处理扩展名：").pack(side=tk.LEFT)
        ttk.Entry(options, textvariable=self.ext_filter, width=24).pack(side=tk.LEFT)
        ttk.Label(options, text="（如 jpg,png，留空为全部）", foreground="#666").pack(side=tk.LEFT)
        source.columnconfigure(0, weight=1)

        body = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        body.add(self._build_rules(body), weight=0)
        body.add(self._build_preview(body), weight=1)

        bottom = ttk.Frame(outer)
        bottom.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(bottom, textvariable=self.summary).pack(side=tk.LEFT)
        self.run_button = ttk.Button(bottom, text="执行", style="Accent.TButton", command=self._execute)
        self.run_button.pack(side=tk.RIGHT)
        self.undo_button = ttk.Button(bottom, text="撤销上一步", command=self._undo, state=tk.DISABLED)
        self.undo_button.pack(side=tk.RIGHT, padx=6)
        ttk.Button(bottom, text="清空规则", command=self._clear_rules).pack(side=tk.RIGHT)

    def _build_rules(self, parent: tk.Widget) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=(0, 0, 10, 0))

        def field(box: ttk.LabelFrame, row: int, label: str, var: tk.StringVar) -> None:
            ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(box, textvariable=var, width=26).grid(row=row, column=1, sticky="ew", pady=3, padx=(6, 0))
            box.columnconfigure(1, weight=1)

        prefix = ttk.LabelFrame(frame, text="前缀", padding=8)
        prefix.pack(fill=tk.X)
        field(prefix, 0, "添加前缀", self.add_prefix)
        field(prefix, 1, "删除前缀", self.remove_prefix)

        suffix = ttk.LabelFrame(frame, text="后缀（扩展名之前）", padding=8)
        suffix.pack(fill=tk.X, pady=(8, 0))
        field(suffix, 0, "添加后缀", self.add_suffix)
        field(suffix, 1, "删除后缀", self.remove_suffix)

        replace = ttk.LabelFrame(frame, text="删除 / 替换文件名中的文字", padding=8)
        replace.pack(fill=tk.X, pady=(8, 0))
        field(replace, 0, "查找", self.find_text)
        field(replace, 1, "替换为", self.replace_text)
        ttk.Label(replace, text="“替换为”留空即删除查找到的文字", foreground="#666").grid(
            row=2, column=0, columnspan=2, sticky="w"
        )

        move = ttk.LabelFrame(frame, text="移动", padding=8)
        move.pack(fill=tk.X, pady=(8, 0))
        ttk.Checkbutton(move, text="将文件移动到指定文件夹", variable=self.move_enabled).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self.target_entry = ttk.Entry(move, textvariable=self.target_dir, width=26)
        self.target_entry.grid(row=1, column=0, sticky="ew", pady=4)
        self.target_button = ttk.Button(move, text="浏览…", command=self._browse_target)
        self.target_button.grid(row=1, column=1, padx=(6, 0))
        self.keep_check = ttk.Checkbutton(move, text="保留子文件夹结构", variable=self.keep_structure)
        self.keep_check.grid(row=2, column=0, columnspan=2, sticky="w")
        move.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text="处理顺序：删除前缀/后缀 → 查找替换 → 添加前缀/后缀\n扩展名始终保持不变。",
            foreground="#666",
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(10, 0))
        return frame

    def _build_preview(self, parent: tk.Widget) -> ttk.Frame:
        frame = ttk.Frame(parent)
        header = ttk.Frame(frame)
        header.pack(fill=tk.X)
        ttk.Label(header, text="实时预览", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Checkbutton(header, text="只显示将修改/有问题的文件", variable=self.only_changed).pack(side=tk.RIGHT)

        table = ttk.Frame(frame)
        table.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        columns = ("old", "new", "location", "status")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="extended")
        for col, text, width, stretch in (
            ("old", "原文件名", 230, True),
            ("new", "新文件名", 230, True),
            ("location", "位置", 260, True),
            ("status", "状态", 150, False),
        ):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, stretch=stretch, anchor="w")
        self.tree.tag_configure(STATUS_OK, foreground="#0a6b2e")
        self.tree.tag_configure(STATUS_UNCHANGED, foreground="#888888")
        self.tree.tag_configure(STATUS_CONFLICT, foreground="#b35c00", background="#fff4e0")
        self.tree.tag_configure(STATUS_INVALID, foreground="#b00020", background="#fde8ea")

        yscroll = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self.tree.yview)
        xscroll = ttk.Scrollbar(table, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)

        self.empty_label = ttk.Label(table, text="", foreground="#888", anchor="center")
        return frame

    # ---------- actions ----------

    def _browse_source(self) -> None:
        path = filedialog.askdirectory(title="选择源文件夹", initialdir=self.source_dir.get() or None)
        if path:
            self.source_dir.set(os.path.normpath(path))

    def _browse_target(self) -> None:
        path = filedialog.askdirectory(
            title="选择目标文件夹", initialdir=self.target_dir.get() or self.source_dir.get() or None
        )
        if path:
            self.target_dir.set(os.path.normpath(path))

    def _sync_move_state(self) -> None:
        state = tk.NORMAL if self.move_enabled.get() else tk.DISABLED
        for widget in (self.target_entry, self.target_button, self.keep_check):
            widget.configure(state=state)

    def _clear_rules(self) -> None:
        for var in (
            self.add_prefix, self.remove_prefix, self.add_suffix, self.remove_suffix,
            self.find_text, self.replace_text,
        ):
            var.set("")
        self.move_enabled.set(False)

    def _rules(self) -> Rules:
        return Rules(
            add_prefix=self.add_prefix.get(),
            remove_prefix=self.remove_prefix.get(),
            add_suffix=self.add_suffix.get(),
            remove_suffix=self.remove_suffix.get(),
            find=self.find_text.get(),
            replace=self.replace_text.get(),
            move_enabled=self.move_enabled.get(),
            target_dir=self.target_dir.get(),
            keep_structure=self.keep_structure.get(),
        )

    def _schedule_scan(self) -> None:
        if self._scan_job:
            self.root.after_cancel(self._scan_job)
        self._scan_job = self.root.after(PREVIEW_DELAY_MS * 2, self._rescan)

    def _schedule_preview(self) -> None:
        if self._preview_job:
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(PREVIEW_DELAY_MS, self._refresh_preview)

    def _rescan(self) -> None:
        self._scan_job = None
        source = self.source_dir.get().strip()
        if not source:
            self.files = []
        elif not Path(source).is_dir():
            self.files = []
            self._refresh_preview(empty_message="文件夹不存在，请检查路径")
            return
        else:
            exclude = None
            if self.move_enabled.get() and self.target_dir.get().strip():
                exclude = Path(self.target_dir.get().strip())
            ext = parse_extensions(self.ext_filter.get())
            self.root.config(cursor="watch")
            self.root.update_idletasks()
            try:
                self.files = scan_files(Path(source), self.recursive.get(), ext or None, exclude)
            except OSError as exc:
                self.files = []
                messagebox.showerror(APP_TITLE, f"读取文件夹失败：\n{exc}")
            finally:
                self.root.config(cursor="")
        self._refresh_preview()

    def _refresh_preview(self, empty_message: str | None = None) -> None:
        self._preview_job = None
        source = self.source_dir.get().strip()
        root = Path(source) if source else Path(".")
        rules = self._rules()
        self.plan = build_plan(root, self.files, rules) if self.files else []

        self.tree.delete(*self.tree.get_children())
        visible = [
            i for i in self.plan
            if not (self.only_changed.get() and i.status == STATUS_UNCHANGED)
        ]
        for index, item in enumerate(visible[:MAX_ROWS]):
            self.tree.insert(
                "", tk.END, iid=str(index), tags=(item.status,),
                values=(item.src.name, item.dst.name, self._location_text(root, item),
                        self._status_text(item)),
            )

        counts = {s: 0 for s in STATUS_LABELS}
        for item in self.plan:
            counts[item.status] += 1

        if not source:
            message = "请选择一个文件夹开始"
        elif empty_message:
            message = empty_message
        elif not self.files:
            message = "该文件夹中没有匹配的文件"
        elif not visible:
            message = "当前规则不会修改任何文件"
        else:
            message = ""
        if message:
            self.empty_label.configure(text=message)
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.empty_label.place_forget()

        if self.plan:
            text = (f"共 {len(self.plan)} 个文件 · 将修改 {counts[STATUS_OK]} · "
                    f"冲突 {counts[STATUS_CONFLICT]} · 无效 {counts[STATUS_INVALID]}")
            if len(visible) > MAX_ROWS:
                text += f" · 仅显示前 {MAX_ROWS} 行"
        else:
            text = message
        self.summary.set(text)
        self.run_button.configure(state=tk.NORMAL if counts[STATUS_OK] else tk.DISABLED)

    def _location_text(self, root: Path, item: PlanItem) -> str:
        def rel(p: Path) -> str:
            try:
                r = p.relative_to(root)
                return "." if str(r) == "." else f".{os.sep}{r}"
            except ValueError:
                return str(p)

        src_dir, dst_dir = rel(item.src.parent), rel(item.dst.parent)
        return src_dir if src_dir == dst_dir else f"{src_dir}  →  {dst_dir}"

    @staticmethod
    def _status_text(item: PlanItem) -> str:
        label = STATUS_LABELS[item.status]
        return f"{label}：{item.message}" if item.message else label

    def _execute(self) -> None:
        todo = [i for i in self.plan if i.will_change]
        if not todo:
            return
        skipped = sum(1 for i in self.plan if i.status in (STATUS_CONFLICT, STATUS_INVALID))
        prompt = f"即将处理 {len(todo)} 个文件。"
        if skipped:
            prompt += f"\n另有 {skipped} 个冲突/无效的文件会被跳过。"
        if self.move_enabled.get() and self.target_dir.get().strip():
            prompt += f"\n\n目标文件夹：{self.target_dir.get().strip()}"
        if not messagebox.askokcancel(APP_TITLE, prompt + "\n\n确定继续吗？"):
            return

        result = execute_plan(self.plan)
        if result.done:
            self.history.append(result.done)
            self.undo_button.configure(state=tk.NORMAL)
        self._report(result, "完成")
        self._rescan()

    def _undo(self) -> None:
        if not self.history:
            return
        last = self.history[-1]
        if not messagebox.askokcancel(APP_TITLE, f"撤销上一步操作，恢复 {len(last)} 个文件？"):
            return
        result = undo(last)
        self.history.pop()
        if not self.history:
            self.undo_button.configure(state=tk.DISABLED)
        self._report(result, "已撤销")
        self._rescan()

    def _report(self, result, verb: str) -> None:
        if result.errors:
            details = "\n".join(f"• {p.name}: {msg}" for p, msg in result.errors[:15])
            if len(result.errors) > 15:
                details += f"\n… 以及另外 {len(result.errors) - 15} 个"
            messagebox.showwarning(
                APP_TITLE, f"{verb} {len(result.done)} 个文件，{len(result.errors)} 个失败：\n\n{details}"
            )
        else:
            messagebox.showinfo(APP_TITLE, f"{verb} {len(result.done)} 个文件。")


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def main() -> None:
    _enable_dpi_awareness()
    root = tk.Tk()
    BatchRenameApp(root)
    root.mainloop()
