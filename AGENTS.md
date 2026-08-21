## Repository Guidelines

This document summarizes how to work with the thaipua repository: how it's organized, how to build, test, lint, and contribute. It mirrors our actual tooling and CI while providing quick commands for local development.

## Project Structure & Module Organization

- `src/thaipua/`: Core Python library and PySide6 desktop application.
  - `app.py` + `__main__.py`: Application entry points (`python -m thaipua` routes to `app.main`).
  - `core/`: GUI-free backend — Thai↔PUA encoding, Creation Engine string-table codec, PUA allocation, placement profiles, and composite font generation.
    - `fonttools/`: fontTools-based generation: `composer.py` (`ThaiPuaFontGenerator`), `settings.py` (`PlacementSettings` / `ConsonantSettings`), `specs.py` (`CompositeSpec`), `alternates.py` (GSUB discovery + shared lookup helpers), `ownership.py` (slot classification), `map_validation.py` (static-map validator), `bounding_box.py`.
    - `constants.py`: Filesystem locations (`APP_DATA_DIR`, `ASSETS_DIR`) and PUA range bounds.
  - `gui/`: PySide6 frontend.
    - `state.py`, `font_service.py`, `glyph_pen.py`: Deliberately PySide6-free layers, unit-testable without a `QApplication`.
    - `widgets/`: Three-column panes (`glyph_grid_pane.py`, `preview_pane.py`, `controls_pane.py`), dialogs, toolbar, status bar.
    - `icons.py`, `theme.py`, `main_window.py`: PySide6-importing surfaces.
- `assets/`: Bundled SVG icons (`icons/`), the sample font `fonts/Sarabun-Regular.ttf` (use it as test input), `images/logo.png`.
- `pyproject.toml`: Package config — `src/` layout, ruff / mypy / pytest settings.
- `pysidedeploy.spec`: Nuitka standalone-build config.
- `.github/workflows/release.yml`: Windows release build on `v*` tags.

Notes:
- Layering: `FontService` is the only GUI -> core facade (owns the live `ThaiPuaFontGenerator`); `MainWindow` is the single mutator of `AppState`; panes only emit signals.
- Keep `thaipua.core` and `gui.state` / `gui.font_service` / `gui.glyph_pen` **PySide6-free** (stdlib + fontTools only). Only `thaipua.app`, `gui/icons.py`, `gui/main_window.py`, `gui/theme.py`, and `gui/widgets/*` may import PySide6.
- Composite installs are **replace-in-place** (`ThaiPuaFontGenerator.install_composite`): glyphs install under stable prefixed names (`thaipua_XXXX`, prefix in `core/fonttools/ownership.py`) so rebuilds never need eviction and by-name references stay valid. Slot locking is decided by `classify_pua_slot` on two signals only — prefixed = owned, foreign composite = replaceable, everything else (unknown simple content, dangling cmap entries, non-glyf fonts) = LOCKED and skipped via `InstallResult` (never silently dropped).
- The `pua_mapping.json` is a **static, user-owned artifact**: `FontService.ensure_pua_map` loads it as-is and bootstraps a full allocation only when the file is missing/empty (`pua_map.ensure_pua_map`, reserving `_occupied_pua_chars`). Existing mappings are never mutated on load — collisions surface as validator badges (`map_validation.validate_pua_map`, shown in the mapping editor) and as skipped installs at regeneration time.
- `CompositeSpec` is derived from `pua_mapping.json` keys (consonant + combining marks -> single PUA char). SARA AM U+0E33 is normalized to NIKKHIT U+0E4D + SARA AA U+0E32 everywhere; keys never contain U+0E33.
- Pure preview path: `ThaiPuaFontGenerator.compose_components` resolves substitutions and computes offset/snap placements read-only (no `glyf`/`hmtx`/`cmap` writes), returning `ComponentPlacement` (glyph name + 6-tuple affine); `FontService.render_composite_path` replays them into a path via `glyph_pen.render_placed_components`. The PUA glyph grid renders cells from this path so the grid reflects live offsets/substitutions/snaps without touching the installed font; grid refresh is debounced (300 ms `QTimer`) after settings mutations, while the viewport rebuilds the single active composite per tick.
- Offset resolution in `ConsonantSettings.offset_for` layers the per-glyph tiers additively: `(mark_offsets[role][mark] or (0,0)) + (combo_offsets[combo_key][role] or (0,0)) + (base_offsets[role] or (0,0))`; `combo_offsets` is an additive delta on top of the generic `mark_offsets` (multi-mark glyphs store delta via `state.apply_offset`, single-mark glyphs store generic). A tone stacked on an above vowel resolves its base tier against the `tone_mark_on_above_vowel` role (falling back to `tone_mark`).

## Build, Test, and Development Commands

- Set up dev environment:
```bash
uv venv --python 3.12
uv sync
```

- Lint and format (ruff):
```bash
uv run ruff format .
uv run ruff check .
```

- Type check (mypy, `strict`):
```bash
uv run mypy .
```

- Run tests (always with coverage):
```bash
uv run pytest
```

- Build the standalone bundle (from the repo root; output at `build/thaipua.dist/`):
```bash
uv run pyside6-deploy -c pysidedeploy.spec
```
`pysidedeploy.spec` pins a machine-specific `python_path` — update it to `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (macOS/Linux) before building.

### Runtime data (dev runs write to the repo root)

`core/constants.py` sets `APP_DATA_DIR` to the repo root when run from source (the exe's dir for standalone builds). On startup/font load the app creates and mutates, at the repo root:

- `pua_mapping.json` — a static, user-owned artifact: auto-allocated with a PUA codepoint (starting U+E000) for every consonant+suffix combo only when the file is missing/empty; existing files are loaded as-is and edited through the mapping editor (toolbar table icon)
- `profiles/default.json` (seeded) and `profiles/<stem>.json` (written on Save Font)
- `settings.json` (theme mode)

Profile resolution tiers for a font: `profiles/<stem>.json` -> `profiles/<family>.json` (family = pre-hyphen stem) -> `default.json` -> built-in defaults.

## Coding Style & Naming Conventions

- 4-space indentation; modules/functions in `snake_case`, classes in `PascalCase`.
- ruff: line-length 120, double quotes. Run `uv run ruff format .` before committing; `uv run ruff check .` enforces import hygiene and lint rules (B, E, F, G, I, N, PT, UP, ERA, RUF, SIM).
- mypy `strict` with `disallow_untyped_defs`; PySide6/fontTools/qdarktheme/darkdetect are `ignore_missing_imports`.
- pep8-naming ignores Qt/fontTools camelCase method names (`paintEvent`, `addComponent`, `closeEvent`, ...) — extend that ignore list in `pyproject.toml` when adding new Qt/fontTools overrides.
- Prefer explicit, structured error handling: raise typed exceptions (`StringTableError`, `RuntimeError`) or log via `logging` module; only deliberately swallow in fallback paths (e.g. `FontService.close`).

## Testing Guidelines

- Tests live under `tests/`, named `test_*.py`: `test_pua_map.py` covers allocation (`ensure_pua_map` with `reserved_pua_chars`), `test_ownership.py` covers slot classification, `test_map_validation.py` covers the static-map validator, `test_install_composite.py` exercises installs against a real font (`assets/fonts/Sarabun-Regular.ttf`), and `test_font_service.py` covers the service facade with duck-typed `TTFont`/`glyf` fakes (no real font needed). Extend these when touching those paths.
- `mypy .` type-checks `tests/` under `strict` too — duck-typed fakes need explicit `cast`/annotations (see the `_FakeFont` stubs in `test_font_service.py`).
- The PySide6-free layers (`core/`, `gui/state.py`, `gui/font_service.py`, `gui/glyph_pen.py`) are unit-testable without a `QApplication` — keep them that way. `glyph_pen` renders into a duck-typed `PathLike` so tests substitute a light recorder.
- `ensure_app_data_dirs` accepts a `base_dir` argument for `tmp_path` isolation; theme/profile/PUA-map helpers accept explicit paths so tests never touch the repo root.
- Use `assets/fonts/Sarabun-Regular.ttf` as a sample source font in tests.
- `pytest` always runs coverage via addopts; don't add another coverage invocation.

## Commit & Pull Request Guidelines

- Use clear, imperative subjects (≤ 72 chars) with conventional commit styling (matches existing history):
  - `feat: add composite offset snapping`
  - `fix: preserve source encoding in string tables`
  - `docs: update installation instructions`
- Reference related issues and provide brief context in the PR body.
- PRs should describe scope and list the local commands run (`uv run ruff check .`, `uv run mypy .`, `uv run pytest`).

## CI Mirrors Local Commands

Our GitHub Actions workflow (`.github/workflows/release.yml`) builds a Windows standalone bundle on `v*` tags: Python 3.12, `uv sync`, then `uv run pyside6-deploy -c pysidedeploy.spec`, zipping `build/thaipua.dist/` into the release. There are no lint/test CI jobs yet — run the commands in this document locally so releases stay green.
