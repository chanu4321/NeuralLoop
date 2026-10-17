"""Build NeuralLoop for Windows: `python windows/build.py`, on Windows, after
`pip install -r windows/requirements.txt`.

1. Draws the icons (NeuralLoop.ico, icon.png) from the iPad's 1024 px icon, and the programs' version info.
2. Runs PyInstaller (windows/NeuralLoop.spec) into dist/windows/NeuralLoop: NeuralLoop.exe and nl-book.exe.
3. Checks the build like a download: nl-book.exe makes the sample book offline (practice model and voices).
4. Packs it: dist/NeuralLoop-<version>-setup.exe with Inno Setup when `iscc` is installed, and always
   dist/NeuralLoop-<version>-windows.zip.

`--icons` stops after step 1 (it runs anywhere); `--no-check` skips step 3.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "build" / "windows"
DIST = ROOT / "dist"
APP = DIST / "windows" / "NeuralLoop"
ICON = ROOT / "apple" / "App" / "iPad" / "Assets.xcassets" / "AppIcon.appiconset" / "icon-1024.png"
ICO_SIZES = [(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)]


def version() -> str:
    sys.path.insert(0, str(ROOT / "pipeline"))
    from neuralloop_books import __version__

    return __version__


def draw_icons(out: Path = ART) -> None:
    """The ICO (every size Windows asks for) and a 256 px PNG for the notification area and toasts."""
    from PIL import Image

    out.mkdir(parents=True, exist_ok=True)
    picture = Image.open(ICON).convert("RGBA")
    picture.save(out / "NeuralLoop.ico", sizes=ICO_SIZES)
    picture.resize((256, 256), Image.LANCZOS).save(out / "icon.png")


def version_info(number: str, out: Path = ART) -> None:
    """The programs' Properties → Details (PyInstaller's version file format)."""
    parts = [int(p) for p in [*number.split("."), "0", "0", "0"][:4]]
    out.mkdir(parents=True, exist_ok=True)
    fields = {
        "CompanyName": "NeuralLoop",
        "FileDescription": "NeuralLoop",
        "FileVersion": number,
        "InternalName": "NeuralLoop",
        "LegalCopyright": "PolyForm Noncommercial License 1.0.0",
        "OriginalFilename": "NeuralLoop.exe",
        "ProductName": "NeuralLoop",
        "ProductVersion": number,
    }
    strings = ",\n".join(f"          StringStruct({k!r}, {v!r})" for k, v in fields.items())
    (out / "version.txt").write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(parts)}, prodvers={tuple(parts)}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
{strings}
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def run(argv: list[str], what: str, **kwargs) -> None:
    """A build step; when it fails, its last lines become the error (CI shows them as an annotation)."""
    done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)
    print(done.stdout, done.stderr, sep="\n")
    if done.returncode != 0:
        tail = "\n".join((done.stdout + "\n" + done.stderr).strip().splitlines()[-25:])
        raise SystemExit(f"{what} failed (exit {done.returncode}):\n{tail}")


def pyinstaller() -> None:
    run(
        [
            sys.executable, "-m", "PyInstaller", str(ROOT / "windows" / "NeuralLoop.spec"), "--noconfirm",
            "--distpath", str(DIST / "windows"), "--workpath", str(ART / "pyinstaller"),
        ],
        "PyInstaller",
        cwd=ROOT,
    )  # fmt: skip


def check_build() -> None:
    """The built pipeline makes the sample book offline, and the app's files are where it looks."""
    for need in ("NeuralLoop.exe", "nl-book.exe", "_internal/neuralloop_desktop/ui/index.html",
                 "_internal/neuralloop_books/assets/pip-poses.js", "_internal/sample/sample-book.epub",
                 "_internal/NeuralLoop.ico", "_internal/icon.png"):  # fmt: skip
        if not (APP / need).exists():
            raise SystemExit(f"The build is missing {need}.")
    if not list((APP / "_internal" / "sounds").glob("*.caf")):
        raise SystemExit("The build is missing Silly mode's sounds.")
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, NEURALLOOP_HOME=home, NEURALLOOP_VIDEO="0", PYTHONIOENCODING="utf-8")
        out = Path(home) / "sample"
        done = subprocess.run(
            [str(APP / "nl-book.exe"), "--dry-run", "--out", str(out), "--speech", "fake"],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
        )  # fmt: skip
        print(done.stdout[-2000:])
        if done.returncode != 0 or not (out / "book.json").exists():
            tail = "\n".join((done.stdout + "\n" + done.stderr).strip().splitlines()[-25:])
            raise SystemExit(f"nl-book.exe couldn't make the sample book (exit {done.returncode}):\n{tail}")


def pack(number: str) -> None:
    archive = DIST / f"NeuralLoop-{number}-windows.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as out:
        for path in sorted(APP.rglob("*")):
            if path.is_file():
                out.write(path, Path("NeuralLoop") / path.relative_to(APP))
    print(f"Wrote {archive}")
    programs = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
    iscc = shutil.which("iscc") or next((str(p) for p in programs.glob("Inno Setup */ISCC.exe")), None)
    if not iscc:
        print("Inno Setup isn't installed, so there's no installer (the zip has everything).")
        return
    run(
        [
            iscc,
            f"/DVersion={number}",
            f"/DSource={APP}",
            f"/DOut={DIST}",
            str(ROOT / "windows" / "installer.iss"),
        ],
        "Inno Setup",
    )
    print(f"Wrote {DIST / f'NeuralLoop-{number}-setup.exe'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build NeuralLoop for Windows.")
    parser.add_argument("--icons", action="store_true", help="only draw the icons and version info")
    parser.add_argument("--no-check", action="store_true", help="skip running the built pipeline")
    args = parser.parse_args()
    number = version()
    draw_icons()
    version_info(number)
    if args.icons:
        print(f"Icons and version info in {ART}")
        return 0
    if sys.platform != "win32":
        raise SystemExit(
            "PyInstaller builds for the system it runs on: build NeuralLoop for Windows on Windows"
        )
    pyinstaller()
    if not args.no_check:
        check_build()
    pack(number)
    return 0


def annotate(message: str) -> None:
    """CI shows this as an error on the run (its log can't always be read)."""
    if os.environ.get("GITHUB_ACTIONS"):
        text = message.replace("%", "%25").replace("\n", "%0A")
        print(f"::error title=windows/build.py::{text}", flush=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as stop:
        if isinstance(stop.code, str):
            annotate(stop.code)
        raise
    except BaseException:
        import traceback

        annotate("\n".join(traceback.format_exc().splitlines()[-30:]))
        raise
