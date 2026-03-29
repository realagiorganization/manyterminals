#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv-test"


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def copy_file(src: Path, rootfs: Path) -> None:
    dst = rootfs / src.relative_to("/")
    ensure_parent(dst)
    if src.is_symlink():
        target = os.readlink(src)
        if not os.path.isabs(target):
            target = str(src.resolve())
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        os.symlink(target, dst)
        target_path = src.resolve()
        if target_path.exists():
            copy_path(target_path, rootfs)
        return
    shutil.copy2(src, dst)


def copy_tree(src: Path, rootfs: Path, *, ignore: shutil.IgnorePattern | None = None) -> None:
    dst = rootfs / src.relative_to("/")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True, ignore=ignore)


def copy_tree_to_absolute_destination(src: Path, rootfs: Path, destination: Path) -> None:
    dst = rootfs / destination.relative_to("/")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)


def copy_path(src: Path, rootfs: Path, *, ignore: shutil.IgnorePattern | None = None) -> None:
    if src.is_dir():
        copy_tree(src, rootfs, ignore=ignore)
    else:
        copy_file(src, rootfs)


def ldd_paths(binary: Path) -> set[Path]:
    result = subprocess.run(["ldd", str(binary)], capture_output=True, text=True, check=True)
    libs: set[Path] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if "=>" in line:
            right = line.split("=>", 1)[1].strip().split(" ", 1)[0]
            if right.startswith("/"):
                libs.add(Path(right))
        elif line.startswith("/"):
            libs.add(Path(line.split(" ", 1)[0]))
    return libs


def copy_binary_with_libs(binary: Path, rootfs: Path) -> None:
    copy_path(binary, rootfs)
    resolved = binary.resolve()
    if resolved != binary:
        copy_path(resolved, rootfs)
    for lib in ldd_paths(resolved):
        copy_path(lib, rootfs)
        lib_alias = Path(str(lib).replace("/usr/lib/", "/lib/", 1))
        if lib_alias.exists():
            copy_path(lib_alias, rootfs)
        resolved_lib = lib.resolve()
        if resolved_lib != lib:
            copy_path(resolved_lib, rootfs)
            resolved_alias = Path(str(resolved_lib).replace("/usr/lib/", "/lib/", 1))
            if resolved_alias.exists():
                copy_path(resolved_alias, rootfs)


def write_minimal_etc(rootfs: Path) -> None:
    etc = rootfs / "etc"
    etc.mkdir(parents=True, exist_ok=True)
    (etc / "passwd").write_text("root:x:0:0:root:/root:/bin/sh\n", encoding="utf-8")
    (etc / "group").write_text("root:x:0:\n", encoding="utf-8")
    (etc / "nsswitch.conf").write_text("passwd: files\ngroup: files\nhosts: files dns\n", encoding="utf-8")
    (etc / "hosts").write_text("127.0.0.1 localhost\n", encoding="utf-8")
    (etc / "resolv.conf").write_text("nameserver 1.1.1.1\n", encoding="utf-8")


def build_rootfs(rootfs: Path) -> None:
    if not VENV.exists():
        raise SystemExit(f"{VENV} is required for local docker fallback")

    for directory in ["proc", "sys", "dev", "tmp", "root", "work"]:
        (rootfs / directory).mkdir(parents=True, exist_ok=True)

    write_minimal_etc(rootfs)

    binaries = [
        Path("/bin/sh"),
        Path("/usr/bin/env"),
        Path("/usr/bin/python3"),
        Path("/usr/bin/tmux"),
        Path("/usr/bin/ps"),
    ]
    for binary in binaries:
        copy_binary_with_libs(binary, rootfs)
    copy_file(Path("/usr/bin/python3"), rootfs)

    python_bin = (VENV / "bin" / "python").resolve()
    copy_binary_with_libs(python_bin, rootfs)
    stdlib = Path(sysconfig.get_path("stdlib"))
    platstdlib = Path(sysconfig.get_path("platstdlib"))
    copy_path(stdlib, rootfs)
    if platstdlib != stdlib:
        copy_path(platstdlib, rootfs)

    copy_path(Path("/usr/lib/locale/C.utf8"), rootfs)
    copy_path(Path("/usr/share/terminfo"), rootfs)
    copy_tree_to_absolute_destination(VENV, rootfs, Path("/opt/manyterminals-venv"))

    repo_ignore = shutil.ignore_patterns(".git", ".venv-test", "__pycache__", ".pytest_cache")
    copy_tree(ROOT, rootfs, ignore=repo_ignore)


def import_image(rootfs: Path, image_tag: str) -> None:
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as handle:
        tar_path = Path(handle.name)
    try:
        with tarfile.open(tar_path, "w") as tar:
            for child in rootfs.iterdir():
                tar.add(child, arcname=child.relative_to(rootfs))
        run(
            [
                "docker",
                "import",
                "--change",
                "ENV LANG=C.utf8",
                "--change",
                "ENV LC_ALL=C.utf8",
                str(tar_path),
                image_tag,
            ]
        )
    finally:
        tar_path.unlink(missing_ok=True)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: build_local_test_image.py IMAGE_TAG", file=sys.stderr)
        return 2
    image_tag = sys.argv[1]
    with tempfile.TemporaryDirectory(prefix="manyterminals-rootfs-") as tempdir:
        rootfs = Path(tempdir)
        build_rootfs(rootfs)
        import_image(rootfs, image_tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
