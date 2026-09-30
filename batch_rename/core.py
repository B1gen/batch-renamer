"""Rename/move planning and execution, independent of the GUI."""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

INVALID_CHARS = set('<>:"/\\|?*')
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

STATUS_OK = "ok"
STATUS_UNCHANGED = "unchanged"
STATUS_CONFLICT = "conflict"
STATUS_INVALID = "invalid"


@dataclass
class Rules:
    add_prefix: str = ""
    remove_prefix: str = ""
    add_suffix: str = ""
    remove_suffix: str = ""
    find: str = ""
    replace: str = ""
    move_enabled: bool = False
    target_dir: str = ""
    keep_structure: bool = False


@dataclass
class PlanItem:
    src: Path
    dst: Path
    status: str = STATUS_OK
    message: str = ""

    @property
    def will_change(self) -> bool:
        return self.status == STATUS_OK


@dataclass
class ExecutionResult:
    done: list[tuple[Path, Path]] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)


def parse_extensions(text: str) -> set[str]:
    """'jpg, .PNG txt' -> {'.jpg', '.png', '.txt'}"""
    parts = text.replace(";", ",").replace(" ", ",").split(",")
    return {("." + p.strip().lstrip(".")).lower() for p in parts if p.strip().lstrip(".")}


def scan_files(
    root: Path,
    recursive: bool,
    extensions: set[str] | None = None,
    exclude_dir: Path | None = None,
) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        return []
    exclude = _norm(exclude_dir) if exclude_dir else None
    files: list[Path] = []

    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            if exclude:
                dirnames[:] = [d for d in dirnames if _norm(Path(dirpath) / d) != exclude]
            dirnames.sort(key=str.lower)
            for name in sorted(filenames, key=str.lower):
                files.append(Path(dirpath) / name)
    else:
        files = sorted((p for p in root.iterdir() if p.is_file()), key=lambda p: p.name.lower())

    if extensions:
        files = [p for p in files if p.suffix.lower() in extensions]
    return files


def transform_stem(stem: str, rules: Rules) -> str:
    """Apply rules to the name without extension: remove first, then replace, then add."""
    if rules.remove_prefix and stem.startswith(rules.remove_prefix):
        stem = stem[len(rules.remove_prefix):]
    if rules.remove_suffix and stem.endswith(rules.remove_suffix):
        stem = stem[: -len(rules.remove_suffix)]
    if rules.find:
        stem = stem.replace(rules.find, rules.replace)
    return f"{rules.add_prefix}{stem}{rules.add_suffix}"


def validate_name(name: str) -> str:
    """Return an error message, or '' if the file name is valid on Windows."""
    stem = Path(name).stem if Path(name).suffix else name
    if not stem.strip():
        return "文件名为空"
    bad = sorted({c for c in name if c in INVALID_CHARS or ord(c) < 32})
    if bad:
        return "包含非法字符 " + " ".join(bad)
    if name.endswith((" ", ".")):
        return "文件名不能以空格或点结尾"
    if stem.split(".")[0].upper() in RESERVED_NAMES:
        return "系统保留名称"
    return ""


def build_plan(root: Path, files: list[Path], rules: Rules) -> list[PlanItem]:
    root = Path(root)
    target_root = Path(rules.target_dir) if rules.move_enabled and rules.target_dir.strip() else None
    plan: list[PlanItem] = []

    for src in files:
        new_name = transform_stem(src.stem, rules) + src.suffix
        if target_root is not None:
            dst_dir = target_root
            if rules.keep_structure:
                try:
                    dst_dir = target_root / src.parent.relative_to(root)
                except ValueError:
                    pass
        else:
            dst_dir = src.parent
        item = PlanItem(src=src, dst=dst_dir / new_name)

        error = validate_name(new_name)
        if error:
            item.status, item.message = STATUS_INVALID, error
        elif _norm(item.dst) == _norm(src) and item.dst.name == src.name:
            item.status = STATUS_UNCHANGED
        plan.append(item)

    _mark_conflicts(plan)
    return plan


def _mark_conflicts(plan: list[PlanItem]) -> None:
    by_dst: dict[str, list[PlanItem]] = {}
    for item in plan:
        if item.status in (STATUS_OK, STATUS_UNCHANGED):
            by_dst.setdefault(_norm(item.dst), []).append(item)
    for items in by_dst.values():
        if len(items) > 1:
            for item in items:
                if item.status == STATUS_OK:
                    item.status, item.message = STATUS_CONFLICT, "多个文件重名"

    # A destination that already exists is only fine if the file there is itself
    # being moved away. Marking one conflict can invalidate another, so iterate.
    changed = True
    while changed:
        changed = False
        leaving = {_norm(i.src) for i in plan if i.status == STATUS_OK}
        for item in plan:
            if item.status != STATUS_OK:
                continue
            dst_key = _norm(item.dst)
            if dst_key == _norm(item.src):
                continue  # case-only rename
            if item.dst.exists() and dst_key not in leaving:
                item.status, item.message = STATUS_CONFLICT, "目标文件已存在"
                changed = True


def execute_plan(plan: list[PlanItem]) -> ExecutionResult:
    """Two-phase move (src -> temp -> dst) so swaps and chains are safe."""
    result = ExecutionResult()
    staged: list[tuple[PlanItem, Path]] = []
    token = uuid.uuid4().hex[:8]

    for index, item in enumerate(i for i in plan if i.will_change):
        temp = item.src.with_name(f".~batchrename_{token}_{index}{item.src.suffix}")
        try:
            os.rename(item.src, temp)
            staged.append((item, temp))
        except OSError as exc:
            result.errors.append((item.src, str(exc)))

    for item, temp in staged:
        try:
            item.dst.parent.mkdir(parents=True, exist_ok=True)
            if item.dst.exists():
                raise FileExistsError(f"目标文件已存在: {item.dst}")
            shutil.move(str(temp), str(item.dst))
            result.done.append((item.src, item.dst))
        except OSError as exc:
            result.errors.append((item.src, str(exc)))
            try:
                os.rename(temp, item.src)
            except OSError:
                result.errors.append((item.src, f"无法恢复，文件暂存为 {temp}"))
    return result


def undo(done: list[tuple[Path, Path]]) -> ExecutionResult:
    plan = [PlanItem(src=dst, dst=src) for src, dst in done]
    return execute_plan(plan)


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))
