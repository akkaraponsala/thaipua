"""G9: the domain layer stays free of fontTools/Qt/direct-IO dependencies."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

DOMAIN_MODULES: tuple[str, ...] = (
    "thai",
    "cluster",
    "grid",
    "pua_map",
    "slots",
    "errors",
    "resolution",
    "settings",
    "layout",
)
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
DOMAIN_DIR = SRC_DIR / "thaipua" / "core" / "domain"

_HEAVY_TOP_LEVELS: frozenset[str] = frozenset({"fontTools", "PySide6", "PySide", "pathlib"})

_STUB_PROBE = """\
import importlib
import sys
import types
from pathlib import Path

src = Path(sys.argv[1])
sys.path.insert(0, str(src))
before = set(sys.modules)
stubs = {
    "thaipua": src / "thaipua",
    "thaipua.core": src / "thaipua" / "core",
    "thaipua.core.domain": src / "thaipua" / "core" / "domain",
}
for name, path in stubs.items():
    stub = types.ModuleType(name)
    stub.__path__ = [str(path)]
    sys.modules[name] = stub
for mod in [
    "thai", "cluster", "grid", "pua_map", "slots",
    "errors", "resolution", "settings", "layout",
]:
    importlib.import_module(f"thaipua.core.domain.{mod}")
new = sorted(m for m in sys.modules if m not in before)
heavy = sorted(m for m in new if m.split(".")[0] in {"fontTools", "PySide6", "PySide"})
print(f"new={len(new)} heavy={heavy}")
if heavy:
    raise SystemExit(f"heavy modules loaded: {heavy}")
if len(new) > 250:
    raise SystemExit(f"import budget blown: {len(new)} new modules")
"""

_UNSTUBBED_PROBE = """\
import sys

sys.path.insert(0, sys.argv[1])
import thaipua.core.domain.grid  # noqa: F401

print("fontTools" in sys.modules)
"""


def _imported_roots(tree: ast.AST) -> set[str]:
    """Collect top-level package names from every import statement."""
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            roots.add(node.module.split(".")[0])
    return roots


def test_domain_modules_statically_free_of_heavy_imports() -> None:
    for mod in DOMAIN_MODULES:
        tree = ast.parse((DOMAIN_DIR / f"{mod}.py").read_text(encoding="utf-8"))
        heavy = _imported_roots(tree) & _HEAVY_TOP_LEVELS
        assert not heavy, f"domain/{mod} imports heavy packages: {sorted(heavy)}"
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "thaipua.core.domain":
                continue
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                assert not node.module.startswith("thaipua.core") or node.module.startswith("thaipua.core.domain"), (
                    f"domain/{mod} reaches into legacy core: {node.module}"
                )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                raise AssertionError(f"domain/{mod} performs direct IO via open()")


def test_domain_modules_load_without_heavy_transitive_imports() -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _STUB_PROBE, str(SRC_DIR)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, f"stubbed domain import failed:\n{proc.stdout}\n{proc.stderr}"


def test_unstubbed_domain_import_skips_legacy_tree() -> None:
    """Land A15: lazy `_reexports` keeps the unstubbed domain import cheap."""
    proc = subprocess.run(
        [sys.executable, "-c", _UNSTUBBED_PROBE, str(SRC_DIR)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, f"unstubbed import failed:\n{proc.stdout}\n{proc.stderr}"
    assert proc.stdout.strip() == "False", "lazy parents must not load fontTools (A15)"


def test_full_core_package_still_smoke_imports() -> None:
    import thaipua.core

    for name in thaipua.core.__all__:
        assert getattr(thaipua.core, name) is not None, f"missing legacy export: {name}"
