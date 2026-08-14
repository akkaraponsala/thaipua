# AGENTS.md

This file provides context for AI coding agents working with the ThaiPUA codebase.

## Project Structure

```
ThaiPUA/
├── assets/
│   ├── fonts/
│   ├── icons/
│   └── images/
├── src/
│   └── thaipua/
│       ├── core/
│       │   ├── fonttools/
│       │   │   ├── __init__.py
│       │   │   ├── alternates.py
│       │   │   ├── bounding_box.py
│       │   │   ├── common.py
│       │   │   ├── composer.py
│       │   │   ├── settings.py
│       │   │   └── specs.py
│       │   ├── __init__.py
│       │   ├── constants.py
│       │   ├── creation_engine.py
│       │   ├── encoding.py
│       │   ├── file_codec.py
│       │   ├── profiles.py
│       │   └── pua_allocator.py
│       ├── gui/
│       │   ├── widgets/
│       │   │   ├── __init__.py
│       │   │   ├── dialogs.py
│       │   │   ├── left_pane.py
│       │   │   ├── middle_pane.py
│       │   │   ├── right_pane.py
│       │   │   ├── status_footer.py
│       │   │   └── top_toolbar.py
│       │   ├── __init__.py
│       │   ├── font_service.py
│       │   ├── glyph_pen.py
│       │   ├── main_window.py
│       │   ├── state.py
│       │   └── theme.py
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py
│       └── py.typed
├── tests/
├── pyproject.toml
└── pysidedeploy.spec
```

## Initial Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -e .[dev]
```

## Activate Environment

Before running development tasks (`ruff`, `mypy`, `pytest`), activate the virtual environment:

```bash
source venv/bin/activate
```

## Quality Checks and Testing

```bash
ruff format .
ruff check .
mypy .
pytest
```
