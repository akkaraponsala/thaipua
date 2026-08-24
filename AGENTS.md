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
│   │   │   ├── cff_convert.py        # CFF (.otf) → TrueType in-memory working-copy conversion at load
│   │   │   ├── map_validation.py     # validate_pua_map → list[PuaMapIssue], slot_context_from_font
│   │   │   ├── occupancy.py          # scan_pua_occupants → PuaOccupant (font-wide PUA slot report)
│   │   │   ├── alternates.py         # GSUB discovery: find_glyph_substitutions
│   │   │   └── bounding_box.py       # BoundingBoxCache
│   │   ├── constants.py              # APP_DATA_DIR / ASSETS_DIR, PUA_RANGE_START/END (U+E000..U+F8FF), SARA_AM_REPLACEMENTS
│   │   ├── bootstrap.py              # ensure_app_data_dirs (mkdir-only, no domain imports)
│   │   ├── encoding.py               # Thai↔PUA encode/decode, normalize_sara_am, load_pua_map_dict
│   │   ├── pua_map.py                # Cluster constants, map-file persistence, free-slot search
│   │   ├── layout.py                 # Deterministic PUA layout: canonical base + relocations + overrides + conflict detection
│   │   ├── profiles.py               # Tiered profile resolution (resolve_settings_profile) + seed_default_profile
│   │   ├── string_table.py           # Bethesda .STRINGS/.DLSTRINGS/.ILSTRINGS codec (StringTableError)
│   │   ├── text_encoding.py          # detect_text_encoding (BOM sniffing, utf-8 → cp1252 fallback)
│   │   └── file_codec.py             # encode_files / decode_files pipeline over text + string tables
│   ├── gui/                          # PySide6 frontend
│   │   ├── state.py                  # AppState (single mutable state), MarkCategory, current_*/apply_* helpers — PySide6-free
│   │   ├── font_service.py           # Only GUI→core facade, owns live generator, PySide6-free
│   │   ├── glyph_pen.py              # PathLike recorder, render_placed_components — PySide6-free
│   │   ├── main_window.py            # Single mutator of AppState, owns QTimer debounce, wiring of all panes
│   │   ├── theme.py / icons.py       # PySide6 allowed
│   │   └── widgets/                  # controls_pane, glyph_grid_pane, preview_pane, top_toolbar, status_footer, dialogs, pua_mapping_dialog, occupancy_dialog
│   └── app.py + __main__.py          # Entry: uv run python -m thaipua → app.main
├── assets/fonts/Sarabun-Regular.ttf  # Sample font for tests
├── data/                               # Runtime data (repo root in dev): layout.json + pua_mapping.json + profiles/ + config.json + logs/
├── pyproject.toml                    # src layout, ruff/mypy/pytest config
└── pysidedeploy.spec                 # Nuitka bundle config
```

## Architecture & Core Logic

### Layering (must follow)

- `FontService` is the **only** GUI→core facade. It owns the live `ThaiPuaFontGenerator`.
- `MainWindow` is the **single mutator** of `AppState`. Panes only emit signals — they never mutate state directly.
- Keep these layers **PySide6-free** (stdlib + fontTools only): `core/`, `gui/state.py`, `gui/font_service.py`, `gui/glyph_pen.py`. Only `app.py`, `main_window.py`, `theme.py`, `icons.py`, and `widgets/*` may import PySide6.
- This split keeps `core/` unit-testable without `QApplication`.

### PUA Mapping & Layout Model

- The layout is **deterministic**: `codepoint = base + ordinal` (`core/layout.py`), ordinal = consonant index × 48 suffixes. Every install gets the same mapping regardless of font load order, so encoded text stays portable. `base` is user-configurable (`layout.json`, default `U+E000`; Settings dialog).
- `layout.json` stores `{base, relocations, overrides}`; `pua_mapping.json` is a **derived cache** of the effective map consumed by the encode/decode pipeline — safe to regenerate anytime.
- Divergence from canonical exists only as explicit relocations: editor hex edits fold into deltas via `FontService.apply_manual_edits`; `relocate_key` picks the first free tail-zone slot past the canonical block.
- Conflicts (effective-map slots occupied by foreign LOCKED/REPLACEABLE content — see `scan_pua_occupants`) never prompt modally: the footer shows `⚠ N mapped slot(s) conflict` and the toolbar's PUA Slots report (`occupancy_dialog.py`) resolves them via per-row Override/Relocate/Remap or the bulk *All* buttons. Overwrite → overrides in `layout.json`; Relocate → tail zone. Unresolved conflicts still block Save through `validate_pua_map`.
- SARA AM: `U+0E33` is never stored in keys. `encoding.normalize_sara_am` converts it to `NIKHHIT U+0E4D + SARA AA U+0E32` everywhere; `constants.SARA_AM_REPLACEMENTS` handles the tone variants.
- THANTHAKHAT `U+0E4C` is treated as a tone mark (it stacks above vowels like the four true tone marks) — see `specs.py`.

### Install Model (slot ownership)

- CFF sources (.otf) are converted to a TrueType working copy **in memory at load** (`cff_convert.py`, cu2qu); the source file is untouched and Save-Font defaults to `<stem>_pua.ttf`. Installs therefore always target `glyf`.
- `composer.install_composite(pua_code, ...)` classifies the target slot via `ownership.classify_pua_slot`: FREE / OWNED / REPLACEABLE proceed; LOCKED (unrecognized non-composite content or dangling cmap entries) returns `InstallStatus.SKIPPED_LOCKED` unless listed in the `allowed_locked` frozenset, which installs with `OVERRIDDEN_LOCKED`; missing consonant glyph returns `SKIPPED_MISSING_CONSONANT`. Callers surface skip statuses instead of inferring from logs. Overrides persist in `layout.json`; `validate_pua_map(allowed_locked=...)` downgrades overridden slots ERROR→WARNING so the save gate passes.
- Composites install under stable names `thaipua_XXXX`, replacing any existing glyph **in place** — glyph order entry and cmap mapping survive rebuilds, so live preview edits never need eviction or glyph-order churn. `_install_composite_glyph` invalidates the bbox cache per write.
- Two persistence policies by design: layout state (`layout.json` + `pua_mapping.json`) writes **eagerly** on every resolution/edit; the **font binary** stays in memory until *Save Font*.

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

## Runtime Data (dev writes to `data/` at repo root)

`constants.APP_DATA_DIR` = `_runtime_root()/data`; `_runtime_root()` returns the repo root unless `is_standalone_build()` (Nuitka sets `__compiled__`, not just `sys.frozen`), then the exe dir. `ensure_app_data_dirs()` (`core/bootstrap.py`, mkdir-only) creates the tree; `seed_default_profile()` (`core/profiles.py`) seeds `default.json` when missing; `app.main` calls both before opening the GUI. On load the app creates/mutates under `data/`:

- `layout.json` — `{base, relocations, overrides}`; the authoritative layout state (auto-bootstrapped to the canonical default)
- `pua_mapping.json` — materialized cache of the effective map, regenerated on every layout change
- `profiles/default.json` (seeded) and `profiles/<stem>.json` (written on Save Font)
- `config.json` (theme; `DEFAULT_CONFIG_PATH`)
- `logs/thaipua.log` (+ `.1`–`.5` rotating backups)

Don't commit these unless intentional. Tests isolate them via explicit path params (`set_layout_path`, `base_dir`, ...) → `tmp_path`.

## Coding Style & Naming Conventions

- Python 3.12, 4-space indent, `snake_case` functions/modules, `PascalCase` classes. Ruff: `line-length 120`, double quotes.
- Ruff `select`: `B, E, F, G, I, N, PT, UP, ERA, RUF, SIM`. `pyproject.toml` already extends `ignore-names` for Qt/fontTools camelCase (`paintEvent`, `addComponent`, `moveTo`, ...) — extend that list for new overrides instead of renaming.
- mypy: `strict` + `disallow_untyped_defs`; `PySide6.*`, `fontTools.*`, `qdarktheme.*`, `darkdetect.*` are `ignore_missing_imports`.
- Prefer typed exceptions (`StringTableError` subclasses) or `logging` over bare excepts; swallow errors only as an intentional fallback.
- Docstring/comment style (house style, applies to all Python incl. tests):
  - Module docstring = exactly **1 line** summarizing responsibility.
  - Function/method docstrings start with an **imperative verb** (`Return`, `Resolve`, `Load`, `Install`, ...); state the contract — return semantics, fallbacks, side effects visible to callers — not internal mechanics.
  - **Omit** when code/naming is already clear: trivial getters, enum members, protocol methods, tests whose name states the scenario. No Args/Returns/Raises boilerplate unless genuinely non-obvious.
  - Inline comments only for non-obvious invariants; delete restating ones.
  - Present tense, **current behavior only** — never implementation history (no "previously", "no longer", "unlike the old ..."). When behavior changes, rewrite the wording instead of annotating the change.
- New placement feature checklist: role/constants in `fonttools/settings.py` (+ `specs.py` if categorization changes), handling in `composer.py`'s `_place_*` methods, UI in `widgets/controls_pane.py`, state glue following the `current_*` / `apply_*` pattern in `state.py`.

## Testing Guidelines

- Tests live under `tests/test_*.py`; notable: `test_install_composite.py` (integration vs the real `assets/fonts/Sarabun-Regular.ttf`), `test_cff_convert.py` (builds a real `.otf` via fontTools `FontBuilder`), `test_layout.py` (deterministic layout + storage + conflicts), `test_font_service.py` / `test_ownership.py` (duck-typed `_FakeFont`/`glyf` fakes typed with `cast`).
- `glyph_pen` uses the `PathLike` duck type so tests use a lightweight recorder.
- Helpers take explicit paths so tests never touch the repo root — use `tmp_path`.
- `pytest` already runs with `--cov=src --cov-report=term-missing` via `addopts` — don't add a second coverage invocation.

## Gotchas / Non-obvious Behaviors

- **The layout is stable by determinism, not by immutability:** assignments never drift silently, but `layout.json`/`pua_mapping.json` are regenerable state — user intent lives in relocations and overrides, not in the cache file.
- **Consonant protrusion:** only `ฬ` is `"ascender"` in `CONSONANT_PROTRUSION`; every other consonant (including descender-protruding `ญ ฐ ฎ ฏ`) falls back to generic tone-within-vowel-family context canonicalization. Don't add descender entries without understanding that logic.
- Prefer `InstallResult.status` over log scraping when reacting to installs; every install outcome, including skips, has an explicit status.

## Commit & Pull Request Guidelines

- Imperative subject ≤72 chars, conventional style: `feat: make combo offset exclusive to multi-mark combos`, `fix: preserve source encoding`.
- PR body: scope, linked issue, schema/API impact, screenshots/logs for UI changes.
- List commands run: `uv run ruff check <path>`, `uv run mypy <path>`, `uv run pytest <path>`.

## CI Mirrors Local Commands

`.github/workflows/release.yml` builds the Windows bundle on `v*.*.*` tags: Python 3.12, `uv sync`, `uv run pyside6-deploy -c pysidedeploy.spec`, zips `build/thaipua.dist/*` → `ThaiPUA-Windows.zip`, attaches to a GitHub Release. There's no lint/test CI yet — run those locally.
