"""Ban umbrella words in new first-party module and top-level class names.

Names like ``manager``, ``handler``, ``context``, or bare ``utils`` say
nothing about what a file or class actually does, so responsibilities pile
up under them with nothing pushing back. See docs/NAMING.md for the
vocabulary to use instead (State, Snapshot, Slice, Host, ...).

This guard is shrink-only: today's offenders are recorded in
tests/quality/umbrella_names_allowlist.txt so this test passes as of the
PR that introduced it. Do not add a new entry to silence a new offender —
rename it instead.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.shared.product_sources import product_python_files

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRODUCT_ROOTS = (
    "bootstrap",
    "config",
    "core",
    "gateway",
    "integrations",
    "infrastructure",
    "surfaces",
    "tools",
)
_UMBRELLA_WORDS = frozenset(
    {
        "port",
        "wiring",
        "manager",
        "handler",
        "processor",
        "engine",
        "wrapper",
        "coordinator",
        "context",
    }
)
_BARE_UMBRELLA_WORDS = frozenset({"utils", "helpers", "common", "misc"})
_ALLOWLIST_PATH = Path(__file__).resolve().parent / "umbrella_names_allowlist.txt"
_CLASS_NAME_PART_REGEX = re.compile(r"[A-Z][a-z0-9]*|[a-z0-9]+")


def _load_allowlist() -> set[tuple[str, str, str]]:
    allowlist: set[tuple[str, str, str]] = set()

    for line in _ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        path, kind, name = line.split("|", 2)
        allowlist.add((path, kind, name))
    return allowlist


def _is_test_path(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def _split_module_name(name: str) -> list[str]:
    return [part for part in name.strip("_").lower().split("_") if part]


def _split_class_name(name: str) -> list[str]:
    return [match.group(0).lower() for match in _CLASS_NAME_PART_REGEX.finditer(name.strip("_"))]


def _offending_word(words: list[str]) -> str | None:
    if len(words) == 1 and words[0] in _BARE_UMBRELLA_WORDS:
        return words[0]

    for word in words:
        if word in _UMBRELLA_WORDS:
            return word
    return None


def _umbrella_offenses(path: Path, tree: ast.AST) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []

    if path.stem == "__init__":
        module_name = path.parent.stem
    else:
        module_name = path.stem

    offending_word = _offending_word(_split_module_name(module_name))

    if offending_word is not None:
        hits.append(("module", module_name))

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            offending_word = _offending_word(_split_class_name(node.name))

            if offending_word is not None:
                hits.append(("class", node.name))

    return hits


def _scan_offenders(root: Path) -> set[tuple[str, str, str]]:
    offenders: set[tuple[str, str, str]] = set()

    for path in product_python_files(root):
        if _is_test_path(path):
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        relpath = path.relative_to(_REPO_ROOT).as_posix()
        for kind, name in _umbrella_offenses(path, tree):
            offenders.add((relpath, kind, name))

    return offenders


@pytest.mark.parametrize("package", _PRODUCT_ROOTS)
def test_product_packages_have_no_umbrella_names(package: str) -> None:
    root = _REPO_ROOT / package
    if not root.is_dir():
        pytest.skip(f"{package}/ missing")

    offenders: list[str] = []
    allowlist: set[tuple[str, str, str]] = _load_allowlist()
    for path in product_python_files(root):
        if _is_test_path(path):
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            offenders.append(f"{path.relative_to(_REPO_ROOT)}: syntax error: {exc}")
            continue

        relpath = path.relative_to(_REPO_ROOT).as_posix()
        for kind, name in _umbrella_offenses(path, tree):
            if (relpath, kind, name) in allowlist:
                continue

            offenders.append(f"{relpath}:{kind}: {name}")

    assert offenders == [], (
        "New umbrella name introduced (see docs/NAMING.md for the vocabulary to use "
        "instead). Rename it — do not add it to "
        "tests/quality/umbrella_names_allowlist.txt to silence this:\n" + "\n".join(offenders)
    )


def test_umbrella_allowlist_has_no_stale_entries() -> None:
    allowlist: set[tuple[str, str, str]] = _load_allowlist()

    offenders: set[tuple[str, str, str]] = set()
    for package in _PRODUCT_ROOTS:
        root = _REPO_ROOT / package
        if not root.is_dir():
            continue
        offenders |= _scan_offenders(root)

    stale_entries: set[tuple[str, str, str]] = allowlist - offenders
    assert stale_entries == set(), (
        "umbrella_names_allowlist.txt has entries that no longer match a real, "
        "current offender (already renamed, or never existed). Remove them:\n"
        + "\n".join(sorted(f"{path}|{kind}|{name}" for path, kind, name in stale_entries))
    )


def test_offending_package_dunder_init_uses_parent_dir_name(tmp_path):
    offending_package_dir = tmp_path / "prompt_manager"
    offending_package_dir.mkdir()

    init_file = offending_package_dir / "__init__.py"
    init_file.write_text("")

    tree = ast.parse("", filename=str(init_file))
    hits = _umbrella_offenses(init_file, tree)

    assert ("module", "prompt_manager") in hits
