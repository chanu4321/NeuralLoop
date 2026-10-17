"""CI (Windows): which packages can't be imported together with onnxruntime. Each pair runs in a fresh Python;
a crash or error becomes a warning annotation. `python scripts/ci_import_check.py`"""

import subprocess
import sys

BEFORE = [
    "numpy", "PIL", "pydantic", "openai", "anthropic", "av", "webview", "pypdfium2", "playwright", "pystray",
    "keyring", "windows_toasts", "espeakng_loader", "phonemizer", "kokoro_onnx", "notebooklm", "setuptools",
]  # fmt: skip


def attempt(code: str) -> tuple[int, str]:
    done = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", code], capture_output=True, text=True, timeout=300
    )
    return done.returncode, (done.stdout + done.stderr).strip()[-600:]


def note(title: str, text: str) -> None:
    print(f"::warning title={title.replace(':', '%3A')}::{text.replace('%', '%25').replace(chr(10), '%0A')}")


def main() -> int:
    code, out = attempt("import onnxruntime as o; print(o.__version__, o.__file__, o.get_device())")
    note("onnxruntime alone" if code == 0 else f"onnxruntime alone fails ({code})", out)
    for name in BEFORE:
        code, out = attempt(f"import {name}\nimport onnxruntime")
        if code != 0:
            note(f"onnxruntime after {name} fails ({code})", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
