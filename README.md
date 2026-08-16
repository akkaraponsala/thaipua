# ThaiPUA

ThaiPUA is a utility that converts Thai text into PUA Unicode and generates composite fonts mapped to Private Use Area (PUA) code points. It is designed to fix Thai text rendering issues in games that do not natively support complex script positioning.

## Features

- **Thai ↔ PUA encoding** of plain-text files and Bethesda Creation Engine string tables (`.STRINGS` / `.DLSTRINGS` / `.ILSTRINGS`), preserving the source byte encoding.
- **Composite PUA font generation**: opens a source font (`.ttf` / `.otf`) and assembles a PUA glyph for every consonant + vowel/tone combination.
- **Placement editor**: per-glyph offsets, per-consonant base offsets, bounding-box snap configs, and GSUB alternate-glyph substitutions, with a live glyph preview.
- **Dark / Light / System themes** via qdarktheme.

## Requirements

- Python 3.12+

## Install

```bash
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -e .[dev]
```

This installs the runtime dependencies (`PySide6`, `fonttools`, `pyqtdarktheme-fork`) along with the dev toolchain (`ruff`, `mypy`, `pytest`, `pytest-cov`, `nuitka`, `imageio`) used for linting, type-checking, testing, and building.

## Usage

```bash
python -m thaipua
```

Or, since the package installs a GUI entry point:

```bash
thaipua
```

Typical workflow:

1. **Open Font** — a `pua_mapping.json` is auto-created at the app data directory, allocating a PUA codepoint (starting at U+E000) for every consonant + suffix combination.
2. Select a consonant, then a variant from the glyph grid; tune offsets / substitutions / snaps in the right pane with live preview.
3. **Save Font** — writes `<stem>_pua.<ext>` next to the source and persists your settings to `profiles/<stem>.json`.
4. Use **Encode Thai → PUA** / **Decode PUA → Thai** to convert text files against the mapping.

### Runtime data

When run from source, the app data directory is the repository root — `pua_mapping.json`, `profiles/`, and `settings.json` are created and updated there. Standalone builds use the folder containing the executable instead. These files are generated; do not commit them.

## Development

```bash
ruff format .   # format
ruff check .    # lint
mypy .          # type-check
pytest          # run tests with coverage
```

See `AGENTS.md` for architecture conventions and repo-specific guidance.

## Build

ThaiPUA is packaged as a standalone app with [`pyside6-deploy`](https://doc.qt.io/qtforpython-6/deployment/deployment-nuitka.html) (Nuitka), using [`pysidedeploy.spec`](pysidedeploy.spec) in the repo root.

```bash
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pyside6-deploy -c pysidedeploy.spec
```

Run this from the repo root, since paths in the spec are resolved relative to it. Update `python_path` in the spec if it doesn't match your venv's interpreter.

The output is a standalone bundle at `build/thaipua.dist/`, containing `ThaiPUA.exe` plus all Python, Qt, and asset dependencies — the whole folder is needed to run the app. The spec targets Windows by default; for macOS/Linux, adjust `python_path` and check the Qt plugin list.
