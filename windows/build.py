"""Build NeuralLoop for Windows: `python windows/build.py`, on Windows, after
`pip install -r windows/requirements.txt`.

1. Draws the icons (NeuralLoop.ico, icon.png) from the iPad's 1024 px icon and the programs' version info, and
   gets espeak-ng (the official 64-bit installer, checked by SHA-256, unpacked into build/windows/espeak-ng).
2. Runs PyInstaller (windows/NeuralLoop.spec) into dist/windows/NeuralLoop: NeuralLoop.exe and nl-book.exe.
3. Checks the build like a download: nl-book.exe makes the sample book offline (practice model and voices).
4. Packs it: dist/NeuralLoop-<version>-setup.exe with Inno Setup when `iscc` is installed, and always
   dist/NeuralLoop-<version>-windows.zip.

`--icons` only draws the icons (it runs anywhere); `--espeak` only gets espeak-ng (CI runs the pipeline's
tests against it); `--no-check` skips step 3.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "build" / "windows"
DIST = ROOT / "dist"
APP = DIST / "windows" / "NeuralLoop"
ICON = ROOT / "apple" / "App" / "iPad" / "Assets.xcassets" / "AppIcon.appiconset" / "icon-1024.png"
ICO_SIZES = [(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)]
ESPEAK = ART / "espeak-ng"
ESPEAK_VERSION = "1.52.0"
ESPEAK_MSI = f"https://github.com/espeak-ng/espeak-ng/releases/download/{ESPEAK_VERSION}/espeak-ng.msi"
ESPEAK_SHA256 = "7f673c709ea5dd579d3b5ebb98688cc575328a6ab7438d2bc405b88cedaeafb9"
# Python packages that would put GPL code inside nl-book.exe: the build must never carry them.
GPL_PACKAGES = ("phonemizer", "espeakng_loader", "kokoro_onnx")


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


PROGRAMS = {  # file stem: what Task Manager and an installer's "in use" list call it
    "NeuralLoop": "NeuralLoop",
    "nl-book": "NeuralLoop book preparation",
}


def version_info(number: str, out: Path = ART) -> None:
    """Each program's Properties → Details (PyInstaller's version file format): version-NeuralLoop.txt and
    version-nl-book.txt."""
    for stem, description in PROGRAMS.items():
        _version_file(number, stem, description, out)


def _version_file(number: str, stem: str, description: str, out: Path) -> None:
    parts = [int(p) for p in [*number.split("."), "0", "0", "0"][:4]]
    out.mkdir(parents=True, exist_ok=True)
    fields = {
        "CompanyName": "NeuralLoop",
        "FileDescription": description,
        "FileVersion": number,
        "InternalName": stem,
        "LegalCopyright": "PolyForm Noncommercial License 1.0.0",
        "OriginalFilename": f"{stem}.exe",
        "ProductName": "NeuralLoop",
        "ProductVersion": number,
    }
    strings = ",\n".join(f"          StringStruct({k!r}, {v!r})" for k, v in fields.items())
    (out / f"version-{stem}.txt").write_text(
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


def fetch_espeak() -> None:
    """espeak-ng as its upstream developers ship it: espeak-ng.exe, libespeak-ng.dll, and espeak-ng-data, from
    the official installer, unmodified. It runs as its own program (GPL-3.0; see NOTICE.md)."""
    if (ESPEAK / "espeak-ng.exe").is_file() and (ESPEAK / "espeak-ng-data").is_dir():
        return
    ART.mkdir(parents=True, exist_ok=True)
    msi = ART / "espeak-ng.msi"
    if not msi.is_file() or hashlib.sha256(msi.read_bytes()).hexdigest() != ESPEAK_SHA256:
        with urllib.request.urlopen(ESPEAK_MSI, timeout=120) as answer:
            data = answer.read()
        if hashlib.sha256(data).hexdigest() != ESPEAK_SHA256:
            raise SystemExit(f"The espeak-ng installer from {ESPEAK_MSI} isn't the expected file.")
        msi.write_bytes(data)
    unpacked = ART / "espeak-msi"
    shutil.rmtree(unpacked, ignore_errors=True)
    run(["msiexec", "/a", str(msi), "/qn", f"TARGETDIR={unpacked}"], "Unpacking espeak-ng")
    found = next(unpacked.rglob("espeak-ng.exe"), None)
    if found is None or not (found.parent / "espeak-ng-data").is_dir():
        raise SystemExit("The espeak-ng installer didn't hold espeak-ng.exe and its data.")
    shutil.rmtree(ESPEAK, ignore_errors=True)
    shutil.copytree(found.parent, ESPEAK)
    (ESPEAK / "SOURCE.txt").write_text(
        f"eSpeak NG {ESPEAK_VERSION}, unmodified, from its official Windows installer:\n{ESPEAK_MSI}\n"
        f"SHA-256 {ESPEAK_SHA256}\n\n"
        "eSpeak NG is free software under the GNU General Public License, version 3 or later (../licenses/"
        "GPL-3.0.txt). Its source code:\n"
        f"https://github.com/espeak-ng/espeak-ng/archive/refs/tags/{ESPEAK_VERSION}.tar.gz\n"
        "NeuralLoop runs it as a separate program to turn narration into phonemes; see NOTICE.md.\n",
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
    bundled = APP / "_internal" / "espeak-ng"
    for need in ("espeak-ng.exe", "libespeak-ng.dll", "espeak-ng-data", "SOURCE.txt"):
        if not (bundled / need).exists():
            raise SystemExit(f"The build is missing espeak-ng's {need}.")
    carried = [name for name in GPL_PACKAGES if (APP / "_internal" / name).exists()]
    if carried:
        raise SystemExit(f"The build carries {', '.join(carried)}, which would put GPL code in nl-book.exe.")
    said = subprocess.run(
        [str(bundled / "espeak-ng.exe"), "-q", "--ipa", "-b", "1", "-v", "en-us", f"--path={bundled}"],
        input=b"Hello there", capture_output=True, timeout=60,
    ).stdout.decode("utf-8", "replace")  # fmt: skip
    if "həlˈoʊ" not in said:
        raise SystemExit(f"The bundled espeak-ng didn't speak as expected: {said!r}")
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
    parser.add_argument("--espeak", action="store_true", help="only get espeak-ng into build/windows")
    parser.add_argument("--no-check", action="store_true", help="skip running the built pipeline")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):  # the pipeline's lines (✓) print on a cp1252 console too
        stream.reconfigure(encoding="utf-8", errors="replace")
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
    fetch_espeak()
    if args.espeak:
        print(f"espeak-ng in {ESPEAK}")
        return 0
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
