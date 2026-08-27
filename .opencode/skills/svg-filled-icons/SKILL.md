---
name: svg-filled-icons
description: Convert stroke-based SVG icons (Lucide/Material line style) into high-quality filled outline paths and verify renders side by side. Use when asked to rewrite icons as filled paths, fix stroke-join spikes/artifacts at corner intersections, or add new icons to assets/icons in this project.
---

# SVG filled icons

Convert stroke-based icon SVGs into single-color filled outline geometry so rendering never produces stroke-join artifacts, then verify visually against the originals before touching the repo.

## Layout

```
svg-filled-icons/
├── SKILL.md          # this file
├── convert.py        # stroke → filled-outline converter (ICONS dict = source of truth)
├── render.py         # contact sheet: orig column vs converted column
└── render_one.py     # large single-icon render for debugging
```

## Workflow

1. Get the exact original from unpkg, never hand-reconstruct: `https://unpkg.com/lucide-static@latest/icons/<name>.svg`
2. Add the icon's inner elements to `convert.py` → `ICONS[name]` (body only, no `<svg>` wrapper). Run conversion — it writes originals to `orig/` and converted files to `out/` next to the script: `uv run --with svgpathtools --with shapely python convert.py` (run with workdir = project root so `uv run` finds the venv)
3. Verify before copying anything: `uv run python render.py` builds `sheet.png` (orig | converted per row); read the image. For a single icon zoomed: `uv run python render_one.py <name> 512`.
4. Only after visual confirmation, copy `out/*.svg` into `assets/icons/`.

## Hard-won invariants (do not violate)

- **rect/circle are stroked shapes**, not fills. Build their centerline as a point ring and CLOSE it exactly (append first point at end) before buffering; an unclosed ring buffers into a capped horseshoe whose self-overlap renders bites under evenodd.
- **Never boolean-union across shapes**: slivers where strokes cross produce broken borders after simplify. Emit one `<path>` per source element instead; same-color overdraw merges them invisibly.
- **All rings of one buffered geometry** (exterior + holes) must share ONE `<path fill-rule="evenodd">` element — a hole emitted standalone renders as a solid disc.
- Output uses `fill="currentColor"`; runtime tinting (`gui/icons.py`) replaces that token with the palette color.
- If a verification render looks wrong, re-run it once before debugging geometry — reading a PNG while it is still being written can mimic real artifacts.
- Converter deps are injected ad hoc (`--with svgpathtools --with shapely`), they are not project dependencies; the renderer uses the project's PySide6.

## Adding a new icon name to the app

Extend the `IconName` Literal in `src/thaipua/gui/icons.py`, then set the icon on the button/widget in both its constructor and its `refresh_icons`-style method. Check `ruff check` + `mypy` on touched files afterwards.
