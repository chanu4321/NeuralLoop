# PyInstaller spec for NeuralLoop for Windows: `python windows/build.py` runs it (after drawing the icons).
#
# One folder, two programs sharing every file:
#   NeuralLoop.exe  the app (no console window)
#   nl-book.exe     the book pipeline, a console program (the app runs it for every book; its output is read)
# The app's own files go next to them: the window (neuralloop_desktop/ui), Pip's poses and fonts (inside
# neuralloop_books/assets), Silly mode's sounds, the sample book, the icon, and the licenses. espeak-ng (GPL-3.0)
# ships as its own unmodified program in `espeak-ng/`, run by the pipeline as a separate process; no GPL
# library is ever bundled into the programs themselves (`GPL_PACKAGES`, refused below).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata
import PyInstaller.building.build_main as build_main

# On Windows, PyInstaller imports every collected package in one helper process to learn the DLL folders they add.
# onnxruntime crashes (an access violation) when it's imported after WinRT, the toasts' bindings; no NeuralLoop
# process ever loads both (the toasts live in NeuralLoop.exe, Kokoro in nl-book.exe). WinRT adds no DLL folders,
# so it's left out of that one step.
_find_binary_dependencies = build_main.find_binary_dependencies


def _without_winrt(binaries, import_packages, *rest):
    kept = [p for p in import_packages if p.split(".")[0] not in ("winrt", "windows_toasts")]
    return _find_binary_dependencies(binaries, kept, *rest)


build_main.find_binary_dependencies = _without_winrt

ROOT = Path(SPECPATH).parent
GPL_PACKAGES = ["phonemizer", "espeakng_loader", "kokoro_onnx"]  # kokoro_onnx imports the other two
ART = ROOT / "build" / "windows"

datas = [
    (str(ROOT / "windows" / "neuralloop_desktop" / "ui"), "neuralloop_desktop/ui"),
    (str(ROOT / "pipeline" / "sample" / "sample-book.epub"), "sample"),
    (str(ART / "NeuralLoop.ico"), "."),
    (str(ART / "icon.png"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "NOTICE.md"), "."),
    (str(ROOT / "licenses"), "licenses"),
]
datas.append((str(ART / "espeak-ng"), "espeak-ng"))  # `python windows/build.py` puts it there
datas += [(str(sound), "sounds") for sound in sorted((ROOT / "apple" / "App" / "Resources").glob("NeuralLoop-*.caf"))]
binaries = []
hiddenimports = [
    *collect_submodules("neuralloop_books"),
    *collect_submodules("neuralloop_desktop"),
    "pystray._win32",
    "keyring.backends.Windows",
]

# Packages with data files, native libraries, or plugins found at run time. (Not onnxruntime: PyInstaller's own
# hook takes its DLLs, and importing all of it crashes on its quantization and training tools.)
for package in (
    "neuralloop_books",
    "webview",
    "notebooklm",
    "playwright",
    "pypdfium2",
    "pypdfium2_raw",
    "windows_toasts",
    "winrt",
    "av",
    "anthropic",
    "openai",
    "tiktoken_ext",
):
    try:
        found = collect_all(package)
    except Exception as error:  # a package this build doesn't have (winrt on Linux): say so, carry on
        print(f"NeuralLoop.spec: skipping {package}: {error}", file=sys.stderr)
        continue
    datas += found[0]
    binaries += found[1]
    hiddenimports += found[2]

# Packages that read their own version from their metadata.
for distribution in ("notebooklm-py", "anthropic", "openai", "pywebview", "keyring", "httpx"):
    try:
        datas += copy_metadata(distribution)
    except Exception:  # not installed in this build: the package that needs it isn't either
        pass

a = Analysis(
    [str(ROOT / "windows" / "launcher.py")],
    pathex=[str(ROOT / "windows"), str(ROOT / "pipeline")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "tkinter", "mlx", "mlx_audio", "pytest", "IPython", "matplotlib",
        "onnxruntime.quantization", "onnxruntime.tools", "onnxruntime.transformers", "onnxruntime.training",
        *GPL_PACKAGES,
    ],  # fmt: skip
    noarchive=False,
)
pyz = PYZ(a.pure)
# Both programs run in Python's UTF-8 mode: files, pipes and the console are UTF-8 whatever Windows' code page
# (a frozen program may not read PYTHONUTF8 from the environment).
UTF8_MODE = [("X utf8_mode=1", None, "OPTION")]

app = EXE(
    pyz,
    a.scripts,
    UTF8_MODE,
    exclude_binaries=True,
    name="NeuralLoop",
    console=False,
    icon=str(ART / "NeuralLoop.ico"),
    version=str(ART / "version-NeuralLoop.txt"),
)
pipeline = EXE(
    pyz,
    a.scripts,
    UTF8_MODE,
    exclude_binaries=True,
    name="nl-book",
    console=True,
    icon=str(ART / "NeuralLoop.ico"),
    version=str(ART / "version-nl-book.txt"),
)
COLLECT(app, pipeline, a.binaries, a.datas, strip=False, upx=False, name="NeuralLoop")
