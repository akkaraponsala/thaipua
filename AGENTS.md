## Repository Guidelines

This document is for AI coding agents. It explains how `thaipua` is organized, how to build and test it, and the non-obvious invariants that will break the app if violated.

> **Maintenance rule:** Keep this file concise. Only add invariants. Prefer 1 line over 3. Remove outdated notes immediately.

## Project Structure & Module Organization

```
thaipua/
├── src/thaipua/
│   ├── core/                         # PySide6-free backend (stdlib + fontTools + pydantic only)
│   │   ├── domain/                   # Pure Pydantic models (no fontTools/Qt/IO): thai, cluster, grid, pua_map, slots, settings, layout, resolution, errors
│   │   ├── font/                     # fontTools adapter layer
│   │   │   ├── workspace.py          # FontWorkspace: live TTFont lifecycle + output paths
│   │   │   ├── composer.py           # ThaiPuaFontGenerator: compose_components (read-only) + install_composite (mutating)
│   │   │   ├── specs.py              # CompositeSpec + Thai sets (thin over domain.thai / domain.cluster)
│   │   │   ├── ownership.py          # SlotOwnership + classify_pua_slot, TOOL_GLYPH_PREFIX ("thaipua_")
│   │   │   ├── cff_convert.py        # CFF (.otf) → TrueType in-memory working-copy conversion at load
│   │   │   ├── map_validation.py     # validate_pua_map → list[PuaMapIssue], slot_context_from_font
│   │   │   ├── occupancy.py          # scan_pua_occupants → PuaOccupant (font-wide PUA slot report)
│   │   │   ├── alternates.py         # GSUB discovery: find_glyph_substitutions
│   │   │   └── bounding_box.py       # BoundingBoxCache
│   │   ├── text/                     # Encode/decode pipeline (pure; file IO at the edges)
│   │   │   ├── encoding.py           # Thai↔PUA encode/decode transforms + normalize_sara_am (pure, no map-file IO)
│   │   │   ├── file_codec.py         # encode_files / decode_files pipeline over text + string tables
│   │   │   ├── string_table.py       # Bethesda .STRINGS/.DLSTRINGS/.ILSTRINGS codec (StringTableError)
│   │   │   └── text_encoding.py      # detect_text_encoding (BOM sniffing, utf-8 → cp1252 fallback)
│   │   ├── fonttools/                # Settings file IO only (`load/save_placement_settings`); schema lives in `core/domain/settings.py`
│   │   │   └── settings.py           # load/save_placement_settings only
│   │   ├── store/                    # Persistence ports (G8): JsonStore protocol + disk/memory backends
│   │   │   ├── ports.py              # JsonStore (load/save verbs; missing documents raise FileNotFoundError)
│   │   │   └── json_store.py         # DiskJsonStore (uniform UTF-8/indent-4) + MemoryJsonStore (tests, zero disk IO)
│   │   ├── session.py                # ProjectSession: undoable document (layout + settings + history), PySide6-free
│   │   ├── commands.py               # DocumentSnapshot / DocumentCommand + coalesce-key merging
│   │   ├── constants.py              # Domain constants: PUA_RANGE_START/END (U+E000..U+F8FF), SARA_AM_REPLACEMENTS, THAI_CONSONANT_CHARS
│   │   ├── paths.py                  # Filesystem roots: APP_DATA_DIR / ASSETS_DIR, DEFAULT_*_PATH, standalone-build detection
│   │   ├── bootstrap.py              # ensure_app_data_dirs (mkdir-only, no domain imports)
│   │   ├── pua_map.py                # Thai suffix list, PUA-map load/save, free-slot search
│   │   └── layout.py                 # Deterministic PUA layout: canonical base + relocations + approvals + conflict detection; accepts layout versions 1–2
│   ├── gui/                          # PySide6 frontend
│   │   ├── state.py                  # AppState (view state only), MarkCategory, current_*/apply_* helpers — PySide6-free
│   │   ├── font_service.py           # Only GUI→core facade, owns workspace + renderer + session, PySide6-free
│   │   ├── rendering.py              # FontRenderer over the workspace (preview + install); PySide6-free, stays in gui/
│   │   ├── glyph_pen.py              # PathLike recorder, render_placed_components — PySide6-free
│   │   ├── main_window.py            # Single mutator of AppState, owns QTimer debounce, wiring of all panes
│   │   ├── theme.py / icons.py       # PySide6 allowed
│   │   └── widgets/                  # controls_pane, glyph_grid_pane, preview_pane, top_toolbar, status_footer, dialogs, pua_mapping_dialog, occupancy_dialog, anchored_tooltip (app-wide widget-anchored tooltips)
│   └── app.py + __main__.py          # Entry: uv run python -m thaipua → app.main
├── assets/fonts/Sarabun-Regular.ttf  # Sample font for tests
├── data/                             # Runtime data (repo root in dev): layout.json + pua_mapping.json + profiles/ + config.json + logs/
├── pyproject.toml                    # src layout, ruff/mypy/pytest config
└── pysidedeploy.spec                 # Nuitka bundle config
```

## Architecture & Core Logic

### Layering (must follow)

- `FontService` is the **only** GUI→core facade. It owns the workspace, the renderer, and the `ProjectSession`.
- `MainWindow` is the **single mutator** of `AppState` (view state: selection, pagination, dirty). Document mutations (layout + settings) go through `FontService.execute*` as undoable commands — panes only emit signals, they never mutate state directly.
- Keep these layers **PySide6-free** (stdlib + fontTools + pydantic only): `core/`, `gui/state.py`, `gui/font_service.py`, `gui/glyph_pen.py`. Only `app.py`, `main_window.py`, `theme.py`, `icons.py`, and `widgets/*` may import PySide6.
- This split keeps `core/` unit-testable without `QApplication`.
- Thai character sets have one source of truth: `core/domain/thai.py` (`CONSONANTS`, `THAI_CONSONANTS`, `CONSONANT_INDEX`, `*_VOWELS`, `TONE_MARKS`). `constants.THAI_CONSONANT_CHARS` and the public sets in `font/specs.py` derive from it — never re-list consonant codepoints.

### PUA Mapping & Layout Model

- The layout is **deterministic**: `codepoint = base + ordinal` (`core/layout.py`), ordinal = consonant index × 60-combo stride (48 materialized). 60 is closed by orthography (bare + tone-only + above + above×tone + below + below×tone), so materializing the remaining 12 shifts zero ordinals. Every install gets the same mapping regardless of font load order, so encoded text stays portable. `base` is user-configurable (`layout.json`, default `U+E000`; Settings dialog).
- `layout.json` stores `{version, base, relocations, approvals}`; `pua_mapping.json` is a **derived cache** of the effective map consumed by the encode/decode pipeline — safe to regenerate anytime.
- Divergence from canonical exists only as explicit relocations: editor hex edits fold into deltas via `FontService.apply_manual_edits`; `relocate_key` picks the first free tail-zone slot past the canonical block.
- Conflicts (effective-map slots occupied by foreign LOCKED/REPLACEABLE content — see `scan_pua_occupants`) never prompt modally: the footer shows `⚠ N mapped slot(s) conflict` and the toolbar's PUA Slots report (`occupancy_dialog.py`) resolves them via per-row Override/Relocate/Remap or the bulk *All* buttons. Overwrite → overrides in `layout.json`; Relocate → tail zone. Unresolved conflicts still block Save through `validate_pua_map`.
- SARA AM: `U+0E33` is never stored in keys. `text.encoding.normalize_sara_am` converts it to `NIKHHIT U+0E4D + SARA AA U+0E32` everywhere; `constants.SARA_AM_REPLACEMENTS` handles the tone variants.
- THANTHAKHAT `U+0E4C` is treated as a tone mark (it stacks above vowels like the four true tone marks) — see `core/font/specs.py`.
- Canonical key form is grid construction order (below→above→tone); entry boundaries (`canonical_cluster_key`/`canonical_cluster_text`, encoder, `cluster_ordinal`, layout load, relocate) normalize arbitrary mark order — see `tests/test_canonical_key_form.py`.
- Holes (11 excluded combos) partial-match by longest-match in the encoder yet round-trip losslessly; accepted behavior, not a bug — see `test_hole_clusters_partial_match_but_roundtrip_losslessly`.
- Cluster parsing has one home (`try_key` in `domain/cluster.py`); `decompose_thai_cluster` delegates to it and rejects duplicate roles / below+above stacks — see `tests/test_cluster_parsing.py`.
- `LayoutState` holds one domain `LayoutEngine` built once at load/mutation (`_rebuild`); `effective_map()` serves a cached render copy (~0.04ms vs ~12.7ms per-call rebuild before), and mutations go through `set_base`/`pin_relocations`/`apply_edits`/`apply_resolutions`/`gc_approvals`. Out-of-range pins overlay afterwards so the validator still flags them — see `tests/test_layout_backend.py`.

### Install Model (slot ownership)

- CFF sources (.otf) are converted to a TrueType working copy **in memory at load** (`cff_convert.py`, cu2qu); the source file is untouched and Save-Font defaults to `<stem>_pua.ttf`. Installs therefore always target `glyf`.
- `composer.install_composite(pua_code, ...)` classifies the target slot via `ownership.classify_pua_slot`: FREE / OWNED / REPLACEABLE proceed; LOCKED (unrecognized non-composite content or dangling cmap entries) returns `InstallStatus.SKIPPED_LOCKED` unless listed in the `allowed_locked` frozenset, which installs with `OVERRIDDEN_LOCKED`; missing consonant glyph returns `SKIPPED_MISSING_CONSONANT`. Callers surface skip statuses instead of inferring from logs. Overrides persist in `layout.json`; `validate_pua_map(allowed_locked=...)` downgrades overridden slots ERROR→WARNING so the save gate passes.
- Composites install under stable names `thaipua_XXXX`, replacing any existing glyph **in place** — glyph order entry and cmap mapping survive rebuilds, so live preview edits never need eviction or glyph-order churn. `_install_composite_glyph` invalidates the bbox cache per write.
- Slot decisions share one entry point: `FontService.resolve_commands` → `LayoutState.apply_resolution(s)` → `domain.resolve` (`OverrideApproval` / `OverrideRevocation` / `RelocatePin`); remap edits converge on the same path via `apply_edits`. Out-of-range pins stay raw so the validator flags them; `relocations` keeps delta-only semantics (fold-back preserves overlay + malformed entries).
- Two persistence policies by design: layout state (`layout.json` + `pua_mapping.json`) writes **eagerly** on every resolution/edit; the **font binary** stays in memory until *Save Font*.

### Rendering Paths (read-only vs. mutating)

- **Pure preview:** `compose_components` resolves substitutions and computes offsets/snaps read-only, returning `ComponentPlacement(glyph_name, (dx, dy))`. `font_service.render_composite_path` replays it into a `PathLike`. Grid cells use this path so edits show without touching the font.
- **Viewport:** rebuilds only the active composite per tick via `regenerate_composite` (which installs into the in-memory font). Grid refresh is debounced 300ms via `MainWindow._grid_refresh_timer` — never rebuild the whole grid per slider tick.

### Settings & Profiles

Settings JSON shape: `{version, metadata, marks: {tone_marks/above_vowels/below_vowels: {U+XXXX: {x,y}}}, consonants: {U+XXXX: {base_offsets, mark_offsets, combo_offsets, snap_configs, glyph_substitutions}}}`. All codepoint keys use canonical `U+XXXX` notation; combo keys are ascending `U+XXXX+U+YYYY` (in-memory they normalize to char keys).

| Tier | Role |
|------|------|
| `base_offsets` | Per-role `{x,y}` for `tone_mark`, `above_vowel`, `below_vowel`, `tone_mark_on_above_vowel` |
| `mark_offsets` | Per-mark overrides grouped by `tone_marks` / `above_vowels` / `below_vowels` |
| `combo_offsets` | Per-combination `U+XXXX+U+YYYY` overrides for multi-mark combos |
| `snap_configs` | `tone_mark_to_above_vowel`, `above_vowel_to_consonant`, `below_vowel_to_consonant`, each `{enabled, gap}` |
| `glyph_substitutions` | Per-codepoint `[{replacement, conditions}]`; conditions are mark roles, AND semantics |

- Strict loads: settings recognize version 1 only and any malformed entry raises `SettingsError` (never warn-and-skip); `layout.json` accepts versions 1–2 (identical shape, absolute pins) and rejects the rest with `LayoutError`. No version migration exists anywhere — unknown versions raise instead of migrating.

- Offset resolution (`PlacementSettings.mark_offset_for`): single marks read `mark_offsets[role][mark]`, multi-mark combos read `combo_offsets[combo][role]`; both stack with the font-global `marks[role][mark]` tier (per-mark, consonant-independent — fixes font-wide mark-origin defects once) and `(base_offsets[base_role or role] or 0)`. A tone mark stacked on an above vowel passes `base_role=ROLE_TONE_MARK_ON_ABOVE_VOWEL`.
- Profiles are **user-driven but auto-resumed**: opening a font auto-loads `<profiles_dir>/<stem>.json` only when its stamped `family_name` (plus `units_per_em` when both known) identifies the live font; otherwise it starts from in-code `default_placement_settings()`. `FontService.save_profile` stamps the live font's identity into the file copy (live settings untouched); legacy unstamped profiles load manually once, then re-save to stamp. Manual Load Profile always applies unconditionally; corrupt profiles warn and fall back without blocking the open. The toolbar's Load/Save Profile (file dialogs via `FontService.load_profile`/`save_profile`) and the Controls pane's Reset Defaults are the sole profile IO. `default_profile_path()` suggests `<profiles_dir>/<stem>.json`.
- Substitution matching canonicalizes both sides via `domain.settings.context_canonicalizer(codepoint)` (category-dependent family merging). Most specific rule (longest canonicalized conditions) wins; ties broken by list order.
- `state.py` helpers are pure: `current_*` readers plus `apply_*` transforms (`settings` → new `settings` via domain `with_*`, clearing zero/disabled entries). `FontService.execute_settings` takes a transform and swaps it in as one undo step; panes never mutate settings directly.

### Undo Model (ProjectSession)

- `ProjectSession` (`core/session.py`) owns the undoable document: `LayoutState` + `PlacementSettings` + undo/redo stacks of `DocumentCommand` (before/after `DocumentSnapshot`, cap 100). It lives in `core/` — not `app/` — because `app.py` already occupies the entry-module name.
- Every document mutation goes through `session.execute(label, mutate, coalesce_key=...)`; no-ops push nothing. Consecutive same-key edits (slider ticks share `offset:<key>:<category>` etc.) merge into one step; profile load/reset push uncoalesced steps.
- Undo covers the document only — the in-memory font binary is a derived artifact (previews install into it per render); undo restores document state and the UI re-renders, with Save rebuilding all composites. Font open/close, layout reload, and approval GC are session boundaries that clear history outside it.
- `FontService.undo()/redo()` persist layout files only when the layout part moved; settings-only undos touch no files.

## Build, Test, and Development Commands

```bash
uv venv --python 3.14         # create venv
uv sync                       # sync all deps (app + dev)

uv run ruff format .          # format
uv run ruff check .           # lint
uv run mypy .                 # type-check (strict)
uv run pytest                 # tests (coverage via addopts)

uv run python -m thaipua      # launch GUI
uv run pyside6-deploy -c pysidedeploy.spec  # bundle → build/thaipua.dist/
```

## Runtime Data (dev writes to `data/` at repo root)

`paths.APP_DATA_DIR` = `_runtime_root()/data`; `_runtime_root()` returns the repo root unless `is_standalone_build()` (Nuitka sets `__compiled__`, not just `sys.frozen`), then the exe dir. `ensure_app_data_dirs()` (`core/bootstrap.py`, mkdir-only) creates the tree; `app.main` calls it before opening the GUI. On load the app creates/mutates under `data/`:

- `layout.json` — `{version, base, relocations, approvals}` (v1 loads; unknown versions raise); the authoritative layout state (auto-bootstrapped to the canonical default)
- `pua_mapping.json` — materialized cache of the effective map, regenerated on every layout change
- `profiles/<name>.json` — written/read only via the toolbar's Save/Load Profile actions
- `config.json` (theme; `DEFAULT_CONFIG_PATH`)
- `logs/thaipua.log` (+ `.1`–`.5` rotating backups)

Don't commit these unless intentional. Tests isolate them via explicit path params (`set_layout_path`, `base_dir`, ...) → `tmp_path`.

## Coding Style & Naming Conventions

- Python 3.14, 4-space indent, `snake_case` functions/modules, `PascalCase` classes. Ruff: `line-length 120`, double quotes.
- Ruff `select`: `B, E, F, G, I, N, PT, UP, ERA, RUF, SIM`. `pyproject.toml` already extends `ignore-names` for Qt/fontTools camelCase (`paintEvent`, `addComponent`, `moveTo`, ...) — extend that list for new overrides instead of renaming.
- mypy: `strict` + `disallow_untyped_defs`; `PySide6.*`, `fontTools.*`, `pydantic.*`, `qdarktheme.*`, `darkdetect.*` are `ignore_missing_imports`.
- Prefer typed exceptions (`StringTableError` subclasses) or `logging` over bare excepts; swallow errors only as an intentional fallback.
- Docstring/comment style (house style, applies to all Python incl. tests):
  - Module docstring = exactly **1 line** summarizing responsibility.
  - Function/method docstrings start with an **imperative verb** (`Return`, `Resolve`, `Load`, `Install`, ...); state the contract — return semantics, fallbacks, side effects visible to callers — not internal mechanics.
  - **Omit** when code/naming is already clear: trivial getters, enum members, protocol methods, tests whose name states the scenario. No Args/Returns/Raises boilerplate unless genuinely non-obvious.
  - Inline comments only for non-obvious invariants; delete restating ones.
  - Present tense, **current behavior only** — never implementation history (no "previously", "no longer", "unlike the old ..."). When behavior changes, rewrite the wording instead of annotating the change.
- New placement feature checklist: role/constants in `core/domain/settings.py` (+ `core/font/specs.py` if categorization changes; `core/fonttools/settings.py` holds only `load/save_placement_settings`), handling in `core/font/composer.py`'s `_place_*` methods, UI in `widgets/controls_pane.py`, state glue following the `current_*` / `apply_*` pattern in `state.py`.

## Testing Guidelines

- Tests live under `tests/test_*.py`; notable: `test_install_composite.py` (integration vs the real `assets/fonts/Sarabun-Regular.ttf`), `test_cff_convert.py` (builds a real `.otf` via fontTools `FontBuilder`), `test_layout.py` (deterministic layout + storage + conflicts), `test_layout_backend.py` (engine-computed maps + strict document gate), `test_domain_settings.py` (strict Pydantic codec + `with_*`/`resolve`), `test_profile_autoload.py` (per-font auto-load), `test_memory_store.py` (JsonStore without disk), `test_font_service.py` / `test_ownership.py` (duck-typed `_FakeFont`/`glyf` fakes typed with `cast`), `test_gui_smoke.py` (offscreen Qt flows with stubbed file dialogs; never `exec()` a modal dialog — it hangs headless), `test_project_session.py` (undo/redo incl. coalescing, cap, snapshot isolation — Qt-free).
- `glyph_pen` uses the `PathLike` duck type so tests use a lightweight recorder.
- Helpers take explicit paths so tests never touch the repo root — use `tmp_path`.
- `pytest` already runs with `--cov=src --cov-report=term-missing` via `addopts` — don't add a second coverage invocation.

## Gotchas / Non-obvious Behaviors

- **The layout is stable by determinism, not by immutability:** assignments never drift silently, but `layout.json`/`pua_mapping.json` are regenerable state — user intent lives in relocations and approvals, not in the cache file.
- **Consonant protrusion:** only `ฬ` is `"ascender"` in `domain.thai.CONSONANT_PROTRUSION`; every other consonant (including descender-protruding `ญ ฐ ฎ ฏ`) falls back to generic tone-within-vowel-family context canonicalization. Don't add descender entries without understanding that logic.
- Prefer `InstallResult.status` over log scraping when reacting to installs; every install outcome, including skips, has an explicit status.

## Commit & Pull Request Guidelines

- Imperative subject ≤72 chars, conventional style: `feat: make combo offset exclusive to multi-mark combos`, `fix: preserve source encoding`.
- PR body: scope, linked issue, schema/API impact, screenshots/logs for UI changes.
- List commands run: `uv run ruff check <path>`, `uv run mypy <path>`, `uv run pytest <path>`.

## CI Mirrors Local Commands

`.github/workflows/ci.yml` runs `ruff check` + `ruff format --check`, `mypy`, and `pytest` on pushes to `main` and PRs. `.github/workflows/release.yml` builds the Windows bundle on `v*.*.*` tags: Python 3.14, `uv sync`, `uv run pyside6-deploy -c pysidedeploy.spec`, zips `build/thaipua.dist/*` → `ThaiPUA-Windows.zip`, attaches to a GitHub Release.
