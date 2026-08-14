# ThaiPUA
ThaiPUA is a utility that converts Thai text into PUA Unicode and generates composite fonts mapped to Private Use Area (PUA) code points. It is designed to fix Thai text rendering issues in software and games that do not natively support complex script positioning.

## Requirements

- Python 3.12+

## Installation

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e .[dev]
```

This installs the runtime dependencies (`PySide6`, `fonttools`, `pyqtdarktheme-fork`) along with the dev toolchain (`ruff`, `mypy`, `pytest`, `pytest-cov`, `nuitka`, `imageio`) used for linting, type-checking, testing, and building.

## Usage

```bash
python -m thaipua.app
```

Or, since the package installs a GUI entry point:

```bash
thaipua
```

## Development

```bash
ruff check .    # lint
ruff format .   # format
mypy .          # type-check
pytest          # run tests with coverage
```

## Build

ThaiPUA is packaged as a standalone app with [`pyside6-deploy`](https://doc.qt.io/qtforpython-6/deployment/deployment-nuitka.html) (Nuitka), using [`pysidedeploy.spec`](pysidedeploy.spec) in the repo root.

```bash
source venv/bin/activate  # Windows: venv\Scripts\activate
pyside6-deploy -c pysidedeploy.spec
```

Run this from the repo root, since paths in the spec are resolved relative to it. Update `python_path` in the spec if it doesn't match your venv's interpreter.

The output is a standalone bundle at `build/thaipua.dist/`, containing `ThaiPUA.exe` plus all Python, Qt, and asset dependencies — the whole folder is needed to run the app. The spec targets Windows by default; for macOS/Linux, adjust `python_path` and check the Qt plugin list.
