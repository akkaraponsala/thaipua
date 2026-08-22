## Repository Guidelines

This document is for AI coding agents. It explains how `thaipua` is organized, how to build and test it, and the non-obvious invariants that will break the app if violated.

> **Maintenance rule:** Keep this file concise. Only add invariants. Prefer 1 line over 3. Remove outdated notes immediately.

## Project Structure & Module Organization

```
thaipua/
├── src/thaipua/
│   ├── core/                         # PySide6-free backend (stdlib + fontTools only)
│   │   ├── fonttools/                # Generation engine
│   │   │   ├── composer.py           # ThaiPuaFontGenerator: compose_components (read-only) + install_composite (mutating)
│   │   │   ├── settings.py           # PlacementSettings / ConsonantSettings, Offset, SnapConfig, SubstitutionRule
│   │   │   ├── specs.py              # CompositeSpec, THAI_CONSONANTS / BELOW_VOWELS / ABOVE_VOWELS / TONE_MARKS / CONSONANT_PROTRUSION
│   │   │   ├── ownership.py          # SlotOwnership + classify_pua_slot, TOOL_GLYPH_PREFIX ("thaipua_")
│   │   │   ├── map_validation.py     # validate_pua_map → list[PuaMapIssue], slot_context_from_font
│   │   │   ├── alternates.py         # GSUB discovery: find_glyph_substitutions
│   │   │   └── bounding_box.py       # BoundingBoxCache
│   │   ├── constants.py              # APP_DATA_DIR / ASSETS_DIR, PUA_RANGE_START/END (U+E000..U+F8FF), SARA_AM_REPLACEMENTS
│   │   ├── encoding.py               # Thai↔PUA encode/decode, normalize_sara_am, load_pua_map_dict
│   │   ├── pua_map.py                # Allocation: next_free_codepoint, allocate_consonant_block, ensure_pua_map, THAI_SUFFIXES
│   │   ├── profiles.py               # Tiered profile resolution (resolve_settings_profile)
│   │   ├── string_table.py           # Bethesda .STRINGS/.DLSTRINGS/.ILSTRINGS codec (StringTableError)
│   │   ├── text_encoding.py          # detect_text_encoding (BOM sniffing, utf-8 → cp1252 fallback)
│   │   └── file_codec.py             # encode_files / decode_files pipeline over text + string tables
│   ├── gui/                          # PySide6 frontend
│   │   ├── state.py                  # AppState (single mutable state), MarkCategory, current_*/apply_* helpers — PySide6-free
│   │   ├── font_service.py           # Only GUI→core facade, owns live generator, PySide6-free
│   │   ├── glyph_pen.py              # PathLike recorder, render_placed_components — PySide6-free
│   │   ├── main_window.py            # Single mutator of AppState, owns QTimer debounce, wiring of all panes
│   │   ├── theme.py / icons.py       # PySide6 allowed
│   │   └── widgets/                  # controls_pane, glyph_grid_pane, preview_pane, top_toolbar, status_footer, dialogs, pua_mapping_dialog
│   └── app.py + __main__.py          # Entry: uv run python -m thaipua → app.main
├── assets/fonts/Sarabun-Regular.ttf  # Sample font for tests
├── profiles/ + pua_mapping.json + settings.json  # Runtime data (repo root in dev)
├── pyproject.toml                    # src layout, ruff/mypy/pytest config
└── pysidedeploy.spec                 # Nuitka bundle config
```

## Architecture & Core Logic

### Layering (must follow)

- `FontService` is the **only** GUI→core facade. It owns the live `ThaiPuaFontGenerator`.
- `MainWindow` is the **single mutator** of `AppState`. Panes only emit signals — they never mutate state directly.
- Keep these layers **PySide6-free** (stdlib + fontTools only): `core/`, `gui/state.py`, `gui/font_service.py`, `gui/glyph_pen.py`. Only `app.py`, `main_window.py`, `theme.py`, `icons.py`, and `widgets/*` may import PySide6.
- This split keeps `core/` unit-testable without `QApplication`.

### PUA Mapping & Allocation Model

- `pua_mapping.json` maps `consonant+marks` Thai keys → single PUA chars. It's insertion-ordered; one consonant's variants occupy consecutive codepoints starting at `U+E000`. `CompositeSpec`s are derived via `iter_composite_specs` — glyph generation is driven entirely by this file.
- Allocation covers `THAI_CONSONANTS` (42 chars) × `THAI_SUFFIXES` (48 suffixes) in `core/pua_map.py`; `next_free_codepoint` scans forward skipping used chars.
- `FontService.ensure_pua_map` only allocates when the file is missing/empty (first-run bootstrap). A pre-existing mapping is **never mutated on load** — it belongs to the user. Fresh allocation reserves the live font's cmap PUA chars (`_occupied_pua_chars`). Collisions surface as validator badges (`map_validation.validate_pua_map` in the mapping dialog) and skipped installs, never silent repair.
- SARA AM: `U+0E33` is never stored in keys. `encoding.normalize_sara_am` converts it to `NIKHHIT U+0E4D + SARA AA U+0E32` everywhere; `constants.SARA_AM_REPLACEMENTS` handles the tone variants.
- THANTHAKHAT `U+0E4C` is treated as a tone mark (it stacks above vowels like the four true tone marks) — see `specs.py`.

### Install Model (slot ownership — no eviction step)

- `composer.install_composite(pua_code, ...)` classifies the target slot via `ownership.classify_pua_slot`: FREE / OWNED / REPLACEABLE proceed; LOCKED (unrecognized non-composite content, dangling cmap entries, non-glyf fonts) returns `InstallStatus.SKIPPED_LOCKED`; missing consonant glyph returns `SKIPPED_MISSING_CONSONANT`. Callers surface skip statuses instead of inferring from logs.
- Composites install under stable names `thaipua_XXXX`, replacing any existing glyph **in place** — glyph order entry and cmap mapping survive rebuilds, so live preview edits never need eviction or glyph-order churn. `_install_composite_glyph` invalidates the bbox cache per write.
- Nothing touches disk until *Save Font*.

### Rendering Paths (read-only vs. mutating)

- **Pure preview:** `compose_components` resolves substitutions and computes offsets/snaps read-only, returning `ComponentPlacement(glyph_name, affine-6-tuple)`. `font_service.render_composite_path` replays it into a `PathLike`. Grid cells use this path so edits show without touching the font.
- **Viewport:** rebuilds only the active composite per tick via `regenerate_composite` (which installs into the in-memory font). Grid refresh is debounced 300ms via `MainWindow._grid_refresh_timer` — never rebuild the whole grid per slider tick.

### Settings & Profile Resolution

Settings JSON shape: `{version, metadata, consonants: {U+XXXX: {base_offsets, mark_offsets, combo_offsets, snap_configs, glyph_substitutions}}}`. All codepoint keys use canonical `U+XXXX` notation; combo keys are ascending `U+XXXX+U+YYYY` (in-memory they normalize to char keys).

| Tier | Role |
|------|------|
| `base_offsets` | Per-role `{x,y}` for `tone_mark`, `above_vowel`, `below_vowel`, `tone_mark_on_above_vowel` |
| `mark_offsets` | Per-mark overrides grouped by `tone_marks` / `above_vowels` / `below_vowels` |
| `combo_offsets` | Per-combination `U+XXXX+U+YYYY` overrides for multi-mark combos |
| `snap_configs` | `tone_mark_to_above_vowel`, `above_vowel_to_consonant`, `below_vowel_to_consonant`, each `{enabled, gap}` |
| `glyph_substitutions` | Per-codepoint `[{replacement, conditions}]`; conditions are mark roles, AND semantics |

- Offset resolution (`ConsonantSettings.offset_for`): single marks read `mark_offsets[role][mark]`, multi-mark combos read `combo_offsets[combo][role]`; both add `(base_offsets[base_role or role] or 0)`. A tone mark stacked on an above vowel passes `base_role=ROLE_TONE_MARK_ON_ABOVE_VOWEL`.
- Profile tiers for `<stem>.ttf`, first match wins: `profiles/<stem>.json` → `profiles/<family>.json` (part before first hyphen) → `profiles/default.json` → in-source `default_placement_settings()`. A missing tier logs at debug and falls through; malformed JSON falls back to defaults rather than erroring.
- Substitution matching canonicalizes both sides via `settings.context_canonicalizer(codepoint)` (category-dependent family merging). Most specific rule (longest canonicalized conditions) wins; ties broken by list order.
- `state.py` helpers (`current_*` / `apply_offset` / `apply_base_offset` / `apply_glyph_substitution` / `apply_snap`) mutate `PlacementSettings` in place, clearing zero/disabled entries.

## Build, Test, and Development Commands

```bash
uv venv --python 3.12         # create venv
uv sync                       # sync all deps (app + dev)

uv run ruff format .          # format
uv run ruff check .           # lint
uv run mypy .                 # type-check (strict)
uv run pytest                 # tests (coverage via addopts)

uv run python -m thaipua      # launch GUI
uv run pyside6-deploy -c pysidedeploy.spec  # bundle → build/thaipua.dist/
```

## Runtime Data (dev writes to repo root)

`constants._runtime_root()` returns the repo root unless `is_standalone_build()` (Nuitka sets `__compiled__`, not just `sys.frozen`), then the exe dir. `ensure_app_data_dirs()` creates `profiles/` and seeds `default.json`; `app.main` calls it before opening the GUI. On load the app creates/mutates:

- `pua_mapping.json` — auto-allocated starting at `U+E000`
- `profiles/default.json` (seeded) and `profiles/<stem>.json` (written on Save Font)
- `settings.json` (theme)

Don't commit these unless intentional. Tests isolate them via explicit `base_dir` / `profiles_dir` params → `tmp_path`.

## Coding Style & Naming Conventions

- Python 3.12, 4-space indent, `snake_case` functions/modules, `PascalCase` classes. Ruff: `line-length 120`, double quotes, google docstring convention.
- Ruff `select`: `B, E, F, G, I, N, PT, UP, ERA, RUF, SIM`. `pyproject.toml` already extends `ignore-names` for Qt/fontTools camelCase (`paintEvent`, `addComponent`, `moveTo`, ...) — extend that list for new overrides instead of renaming.
- mypy: `strict` + `disallow_untyped_defs`; `PySide6.*`, `fontTools.*`, `qdarktheme.*`, `darkdetect.*` are `ignore_missing_imports`.
- Prefer typed exceptions (`StringTableError` subclasses) or `logging` over bare excepts; swallow errors only as an intentional fallback.
- Docstrings, comments, and test names describe **current behavior only** — never implementation history (no "previously", "no longer", "unlike the old ..."). When behavior changes, rewrite the wording instead of annotating the change.
- New placement feature checklist: role/constants in `fonttools/settings.py` (+ `specs.py` if categorization changes), handling in `composer.py`'s `_place_*` methods, UI in `widgets/controls_pane.py`, state glue following the `current_*` / `apply_*` pattern in `state.py`.

## Testing Guidelines

- Tests live under `tests/test_*.py`: `test_install_composite.py` (integration vs the real `assets/fonts/Sarabun-Regular.ttf`: classification, replace-in-place, locked skips, save/reload prefix persistence), `test_font_service.py` + `test_ownership.py` (duck-typed `_FakeFont`/`glyf` fakes typed with `cast`), plus `test_pua_map.py`, `test_settings.py`, `test_map_validation.py`.
- The PySide6-free layers are unit-testable without `QApplication` — keep it that way. `glyph_pen` uses the `PathLike` duck type so tests use a lightweight recorder.
- Helpers take explicit paths so tests never touch the repo root — use `tmp_path`.
- `pytest` already runs with `--cov=src --cov-report=term-missing` via `addopts` — don't add a second coverage invocation.

## Gotchas / Non-obvious Behaviors

- **Grid vs. viewport refresh:** grid cells lag 300ms behind slider changes (debounce timer); the viewport rebuilds immediately. Don't rebuild the grid per tick.
- **Pre-existing PUA maps are sacred:** loading never rewrites a user-edited `pua_mapping.json`; bad slots show up as validation issues and LOCKED-skip warnings at install time instead.
- **Consonant protrusion:** only `ฬ` is `"ascender"` in `CONSONANT_PROTRUSION`; every other consonant (including down-protruding descenders `ญ ฐ ฎ ฏ`) falls back to generic tone-within-vowel-family context canonicalization. Don't add descender entries without understanding that logic.
- **`pysidedeploy.spec`'s `python_path` is machine-specific** (currently a hardcoded absolute path): point it at `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (macOS/Linux) before building, or Nuitka uses the wrong interpreter and the bundle fails. Run it from the repo root — spec paths resolve relative to cwd.
- Prefer `InstallResult.status` over log scraping when reacting to installs; every install outcome, including skips, has an explicit status.

## Commit & Pull Request Guidelines

- Imperative subject ≤72 chars, conventional style: `feat: make combo offset exclusive to multi-mark combos`, `fix: preserve source encoding`.
- PR body: scope, linked issue, schema/API impact, screenshots/logs for UI changes.
- List commands run: `uv run ruff check <path>`, `uv run mypy <path>`, `uv run pytest <path>`.

## CI Mirrors Local Commands

`.github/workflows/release.yml` builds the Windows bundle on `v*.*.*` tags: Python 3.12, `uv sync`, `uv run pyside6-deploy -c pysidedeploy.spec`, zips `build/thaipua.dist/*` → `ThaiPUA-Windows.zip`, attaches to a GitHub Release. There's no lint/test CI yet — run those locally.
