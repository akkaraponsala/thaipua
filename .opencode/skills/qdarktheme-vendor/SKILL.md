---
name: qdarktheme-vendor
description: Edit the vendored qdarktheme flat theme in src/qdarktheme that thaipua's theme.py wraps. Use when changing widget QSS globally, swapping SVG icons, or adjusting the dark/light palette.
---

# qdarktheme vendor

Vendored `PyQtDarkTheme 2.3.6` into `src/qdarktheme`. `src/thaipua/gui/theme.py` is the only integration point — it loads the vendored stylesheet/palette and appends app overrides.

## Layout

```
src/qdarktheme/
├── __init__.py          # re-exports setup_theme, load_stylesheet, load_palette
├── _main.py             # setup_theme / _apply_style + system-theme sync
├── _style_loader.py     # load_stylesheet / load_palette
├── _color.py            # Color, lighten/darken/transparent
├── _util.py             # get_cash_root_path → ~/.cache/qdarktheme/v2.3.6
├── _proxy_style.py      # QDarkThemeStyle proxy
├── _resources/
│   ├── colors.py        # THEME_COLOR_VALUES[dark|light] — source of truth
│   ├── stylesheets.py   # TEMPLATE_STYLESHEET with {{ var|filter }}
│   ├── palette.py       # q_palette → QPalette
│   ├── svg.py           # SVG_RESOURCES (Material icons)
│   └── standard_icons.py
├── _template/
│   ├── engine.py        # Template {{ var|filter }}
│   └── filter.py        # color, palette_format, url, env, corner
├── _icon/svg.py         # Svg(id).colored().rotate() → writes to cache
├── _os_appearance/      # darkdetect + mac accent
├── qtpy/                # PySide6 compat shims
└── LICENSE              # keep on every copy
```

`src/qdarktheme` is a top-level package under `src` so `import qdarktheme` resolves to the vendored copy. No pip `qdarktheme` dependency remains.

## Core flow

1. `theme.apply_theme(app, mode)` resolves `mode → effective`, picks `Palette`, then `app.setStyleSheet(qdarktheme.load_stylesheet(effective.value) + _local_overrides(palette))` and `app.setPalette(...)`.
2. `load_stylesheet` parses `colors.py` JSON, merges `custom_colors`, renders `TEMPLATE_STYLESHEET` via `Template`, and `url()` writes tinted SVGs to `~/.cache/qdarktheme/v2.3.6/`.
3. `load_palette` builds `QPalette` from the same color map.
4. Per-widget overrides bypass the app sheet: `GlyphCell` and `CollapsibleSection` use `widget.setStyleSheet` with `QFrame#Id` selectors for higher specificity.

## Editing recipes

### Remove or change a widget background globally

Append to `theme._local_overrides` instead of editing `TEMPLATE_STYLESHEET`:

```python
QComboBox { background: transparent; border: 1px solid {palette.BORDER}; }
QComboBox:focus { border-color: {palette.BORDER_FOCUS}; }
```

For card-scoped only, use a descendant selector in the widget's own sheet as in `collapsible_section.py`:

```css
QFrame#SectionBody QComboBox { background: #4A4D51; border: 1px solid #5F6368; }
```

An intermediate `QWidget` with its own `setStyleSheet` blocks ancestor descendant selectors — leave the intermediate `content` widget without a stylesheet so `QFrame#SectionBody QSpinBox` can reach the spin box.

### Swap a widget SVG icon

Icons are recolored via `filter.url`:

```
QComboBox::down-arrow { image: url({{ foreground|color(state="icon")|url(id="expand_less",rotate=180) }}) }
```

- Global override: add to `_local_overrides`:
  ```css
  QComboBox::down-arrow { image: url(path/to/custom.svg); }
  ```
- Edit source: add entry to `_resources/svg.py:SVG_RESOURCES`, then clear `~/.cache/qdarktheme` or bump `__version__`.

### Change palette or add a token

1. Edit `src/qdarktheme/_resources/colors.py:THEME_COLOR_VALUES`.
2. Reference it in `stylesheets.py` as `{{ myToken|color }}`.
3. Expose it in `thaipua/gui/theme.py:Palette` if needed in Python painting code.
4. Test both dark and light, then `rm -rf ~/.cache/qdarktheme` and `uv run python -m thaipua`.

### Prototype without file edits

```python
qdarktheme.load_stylesheet("dark", custom_colors={"input.background": "#4A4D51"})
```

## Gotchas

- `QWidget` needs `WA_StyledBackground` to paint `background-color`; `QFrame` does not. `CollapsibleSection` is a `QFrame` for this reason.
- App sheet `QComboBox { }` loses to per-widget `QFrame#Id QComboBox { }` due to ID specificity. Use per-widget for card scope, `_local_overrides` for global.
- `url()` SVGs are cached. After editing `svg.py` or a tinting color, delete the cache or bump `__version__`.
- `QPalette` affects `QPainter` code; QSS `background:` affects `QWidget` painting. Keep `theme.Palette` and `colors.py` in sync.
- `widget_gallery/` is demo only — safe to delete.

## Maintenance

- Keep `src/qdarktheme/LICENSE`. Icons are Apache 2.0, stylesheet is MIT fork of QDarkStyleSheet.
- To sync upstream fixes, copy the core dirs (`_resources`, `_template`, `_icon`, `_color.py`, `_style_loader.py`) into `src/qdarktheme` and run `ruff check`, `mypy`, `pytest`.
- Verify visually: `uv run python -m thaipua` at `1520x855` and maximized, check `Controls` cards, `Glyph Grid` cells, and `Preview` in both dark and light modes.
