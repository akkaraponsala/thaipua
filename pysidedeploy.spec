[app]

title = ThaiPUA

# Repo root: lets pyside6-deploy discover the source tree and resolve assets/.
project_dir = .

# Package entry (python -m thaipua → thaipua.app.main); a directory avoids
# nuitka's __main__-module warning.
input_file = src\thaipua

# .dist/ bundle lands under build/ at the repo root, out of the source tree.
exec_directory = build
project_file =
icon = assets/images/logo.png

[python]

# Must stay empty: uses the interpreter running pyside6-deploy (the project
# venv via uv run, local and CI); a hardcoded path breaks other machines.
python_path =

packages = Nuitka==4.1.1

[qt]

qml_files =
excluded_qml_plugins =

# QtWidgets app: no QML; modules listed explicitly instead of auto-detect.
modules = Core,Gui,Svg,Widgets
plugins = accessiblebridge,egldeviceintegrations,generic,iconengines,imageformats,platforminputcontexts,platforms,platforms/darwin,platformthemes,styles,wayland-decoration-client,wayland-graphics-integration-client,wayland-shell-integration,xcbglintegrations

[android]

# Desktop-only app; section unused.
wheel_pyside =
wheel_shiboken =
plugins =

[nuitka]

# Standalone build: thaipua.dist/ holds the .exe plus all runtime deps;
# runtime-data dispatch keys off <exe-dir>/assets, settings.json, profiles/.
mode = standalone

# --include-data-dir bundles assets/ next to the .exe;
# --output-filename/--output-folder-name pin ThaiPUA.exe/thaipua.dist/
# (nuitka would default to __main__.exe/__main__); the rest trims unused
# payloads and keeps the non-interactive build quiet.
extra_args = --quiet --noinclude-qt-translations --noinclude-dlls=Qt6Qml*.dll --include-data-dir=assets=assets --assume-yes-for-downloads --output-filename=ThaiPUA.exe --output-folder-name=thaipua --windows-console-mode=disable
