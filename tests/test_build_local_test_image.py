from __future__ import annotations

from pathlib import Path

from scripts import build_local_test_image as builder


def test_copy_file_rewrites_relative_symlink_to_absolute_target(tmp_path) -> None:
    source_root = tmp_path / "source"
    rootfs = tmp_path / "rootfs"
    shell_path = source_root / "bin" / "sh"
    dash_path = source_root / "usr" / "bin" / "dash"
    dash_path.parent.mkdir(parents=True, exist_ok=True)
    dash_path.write_text("#!/bin/sh\n", encoding="utf-8")
    shell_path.parent.mkdir(parents=True, exist_ok=True)
    shell_path.symlink_to("../usr/bin/dash")

    builder.copy_file(shell_path, rootfs)

    copied_shell = rootfs / shell_path.relative_to("/")
    copied_target = rootfs / dash_path.relative_to("/")
    assert copied_shell.is_symlink()
    assert Path(copied_shell.readlink()).is_absolute()
    assert copied_shell.readlink() == dash_path
    assert copied_target.exists()
