[app]

# title of the thaipua desktop application.
title = ThaiPUA

# project root directory. empty defaults to the parent of `input_file`; we
# pin it to `.` (this spec file's folder, the repo root) so `pyside6-deploy`
# discovers the whole source tree (and resolves `assets/`, the bundled
# include-data-dir, against it -- run `pyside6-deploy -c pysidedeploy.spec`
# from this directory).
project_dir = .

# module entry point = `python -m thaipua` -> `thaipua.__main__:main` ->
# `thaipua.app = main`, which constructs the `QApplication` and `MainWindow`.
# resolved relative to `project_dir` (the repo root). point at the package
# directory (not `__main__.py` itself) so nuitka treats it as a package
# entry without emitting its `__main__` module warning.
input_file = src\thaipua

# directory where the standalone `.dist/` bundle is generated. default would
# drop it under `src/thaipua/deployment/`; we move it into `build/` at the
# repo root so the .dist folder, build artifacts, and intermediates stay
# out of the source tree.
exec_directory = build

# application icon, embedded into the .exe (windows = `--windows-icon-from-ico`).
# nuitka 4.0+ accepts this .png and converts it to ico; if a future nuitka
# version rejects png, convert `assets/images/logo.png` to `assets/images/logo.ico`
# and point `icon` at it. the running app's window icon is set separately by
# `_set_window_icon` in `thaipua.app` via `constants.assets_dir`.
project_file = 
icon = assets/images/logo.png

[python]

# python interpreter used to drive the build. empty lets `pyside6-deploy`
# default to the interpreter running the tool (the project's venv).
python_path = D:\ThaiPUA\venv\Scripts\python.exe

# python packages to install for the build host. `pyside6-deploy` runs
# nuitka to bundle pyside6; pin nuitka = =4.0 to match the spec the tool
# ships with.
packages = Nuitka==4.0

[qt]

# qml files to bundle. thaipua is a qtwidgets app (no qml), so leave empty.
qml_files = 

# excluded qml plugin binaries. no qml -- leave empty.
excluded_qml_plugins = 

# qt modules used. leave empty so `pyside6-deploy` auto-detects
# (core, gui, widgets, svg) from the source-tree imports.
modules = Core,Gui,Svg,Widgets

# qt plugins used by the application. empty = auto-detect.
plugins = accessiblebridge,egldeviceintegrations,generic,iconengines,imageformats,platforminputcontexts,platforms,platforms/darwin,platformthemes,styles,wayland-decoration-client,wayland-graphics-integration-client,wayland-shell-integration,xcbglintegrations

[android]

# thaipua is a desktop-only app; the [android] section is unused.
wheel_pyside = 
wheel_shiboken = 
plugins = 

[nuitka]

# nuitka standalone build = produces a `ThaiPUA.dist/` folder holding the
# .exe alongside all python/qt/dll dependencies -- the layout our
# `is_standalone_build()` path dispatch keys off (`<exe-dir>/assets/`,
# `<exe-dir>/settings.json`, `<exe-dir>/profiles/`, ...).
mode = standalone

# extra nuitka flags beyond what `pyside6-deploy` already passes
# (`--follow-imports`, `--enable-plugin = pyside6`, `--output-dir`, icon).
# `--include-data-dir = assets=assets` copies the source-tree `assets/` folder
# into `thaipua.dist/assets/` so `assets_dir` finds the bundled fonts,
# and logo next to the .exe. `--noinclude-qt-translations` trims unused i18n
# payloads; `--quiet` suppresses nuitka's verbose per-module progress log.
# `--assume-yes-for-downloads` auto-accepts nuitka's prompts to fetch its
# windowed helper tools (e.g. dependency walker for standalone/onefile on
# windows), since `pyside6-deploy` runs nuitka non-interactively and would
# otherwise answer "no" and abort the build.
# `--output-filename = ThaiPUA.exe` controls the exe name: nuitka names the
# executable after the entry script (`input_file` = `src/thaipua` directory ->
# its `__main__.py` -> `__main__.exe`), and `pyside6-deploy` does not rename
# it. since the app window title is also `thaipua`, pin the exe to match the
# bundle folder `build/thaipua.dist/`.
# `--output-folder-name = thaipua` fixes the `.dist/` folder name to `thaipua`
# instead of nuitka's default `__main__` (derived from `__main__.py`), so it
# matches the bundle `pyside6-deploy` looks for via `source_file.stem`.
extra_args = --quiet --noinclude-qt-translations --include-data-dir=assets=assets --assume-yes-for-downloads --output-filename=ThaiPUA.exe --output-folder-name=thaipua --windows-console-mode=disable

