from pathlib import Path

from batch_rename.core import (
    STATUS_CONFLICT,
    STATUS_INVALID,
    STATUS_OK,
    STATUS_UNCHANGED,
    Rules,
    build_plan,
    execute_plan,
    parse_extensions,
    scan_files,
    transform_stem,
    undo,
)


def make(root: Path, *names: str) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)


def test_transform_order():
    rules = Rules(add_prefix="new_", remove_prefix="old_", add_suffix="_v2", remove_suffix="_v1",
                  find="draft", replace="final")
    assert transform_stem("old_report draft_v1", rules) == "new_report final_v2"


def test_remove_prefix_only_when_present():
    assert transform_stem("abc", Rules(remove_prefix="x")) == "abc"


def test_parse_extensions():
    assert parse_extensions("jpg, .PNG txt;gif") == {".jpg", ".png", ".txt", ".gif"}
    assert parse_extensions("  ") == set()


def test_scan_recursive_and_filter(tmp_path):
    make(tmp_path, "a.jpg", "b.txt", "sub/c.jpg", "sub/deep/d.JPG")
    assert len(scan_files(tmp_path, recursive=False)) == 2
    jpgs = scan_files(tmp_path, recursive=True, extensions={".jpg"})
    assert sorted(p.name for p in jpgs) == ["a.jpg", "c.jpg", "d.JPG"]


def test_scan_excludes_target(tmp_path):
    make(tmp_path, "a.txt", "out/b.txt")
    files = scan_files(tmp_path, recursive=True, exclude_dir=tmp_path / "out")
    assert [p.name for p in files] == ["a.txt"]


def test_plan_statuses(tmp_path):
    make(tmp_path, "a.txt", "b.txt", "keep.txt", "x_a.txt")
    files = scan_files(tmp_path, recursive=False)
    plan = {i.src.name: i for i in build_plan(tmp_path, files, Rules(find="b", replace="a"))}
    assert plan["a.txt"].status == STATUS_UNCHANGED
    assert plan["b.txt"].status == STATUS_CONFLICT  # a.txt exists and stays

    plan = build_plan(tmp_path, files, Rules(find="keep", replace="a?"))
    assert {i.src.name: i.status for i in plan}["keep.txt"] == STATUS_INVALID


def test_duplicate_targets_conflict(tmp_path):
    make(tmp_path, "a.txt", "sub/a.txt", "sub/b.txt")
    target = tmp_path / "flat"
    files = scan_files(tmp_path, recursive=True)
    plan = build_plan(tmp_path, files, Rules(move_enabled=True, target_dir=str(target)))
    statuses = {str(i.src.relative_to(tmp_path)): i.status for i in plan}
    assert statuses["a.txt"] == STATUS_CONFLICT
    assert statuses[str(Path("sub/a.txt"))] == STATUS_CONFLICT
    assert statuses[str(Path("sub/b.txt"))] == STATUS_OK


def test_chain_rename_into_vacated_name(tmp_path):
    make(tmp_path, "1.txt", "11.txt")
    files = scan_files(tmp_path, recursive=False)
    # 1 -> 11 is fine because 11 -> 111 vacates it
    plan = build_plan(tmp_path, files, Rules(add_prefix="1"))
    assert all(i.status == STATUS_OK for i in plan)
    assert not execute_plan(plan).errors
    assert sorted(p.name for p in tmp_path.iterdir()) == ["11.txt", "111.txt"]


def test_swap_is_allowed_and_executes(tmp_path):
    make(tmp_path, "a.txt", "b.txt")
    files = scan_files(tmp_path, recursive=False)
    # a->b and b->a via replacing the single letter
    plan = build_plan(tmp_path, files, Rules())
    plan[0].dst, plan[1].dst = plan[1].src, plan[0].src
    plan[0].status = plan[1].status = STATUS_OK
    result = execute_plan(plan)
    assert not result.errors
    assert (tmp_path / "a.txt").read_text() == "b.txt"
    assert (tmp_path / "b.txt").read_text() == "a.txt"


def test_execute_move_with_structure_and_undo(tmp_path):
    src = tmp_path / "src"
    make(src, "a.txt", "sub/b.txt")
    target = tmp_path / "dest"
    rules = Rules(add_prefix="p_", move_enabled=True, target_dir=str(target), keep_structure=True)
    plan = build_plan(src, scan_files(src, recursive=True), rules)
    result = execute_plan(plan)
    assert not result.errors
    assert (target / "p_a.txt").exists()
    assert (target / "sub" / "p_b.txt").read_text() == "sub/b.txt"
    assert not (src / "a.txt").exists()

    back = undo(result.done)
    assert not back.errors
    assert (src / "sub" / "b.txt").exists()
    assert not (target / "p_a.txt").exists()


def test_move_flat(tmp_path):
    make(tmp_path, "a.txt", "sub/b.txt")
    target = tmp_path / "flat"
    rules = Rules(move_enabled=True, target_dir=str(target))
    files = scan_files(tmp_path, recursive=True, exclude_dir=target)
    result = execute_plan(build_plan(tmp_path, files, rules))
    assert not result.errors
    assert sorted(p.name for p in target.iterdir()) == ["a.txt", "b.txt"]
