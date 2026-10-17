"""The person's API keys, in Windows Credential Manager (through `keyring`); never in ai.json, logs, or argv.

Elsewhere (developing on Linux or macOS) keyring uses that system's own store. With no store at all, keys
live only
in memory for this session, and Settings says so."""

import contextlib
import threading

from ..core.pipeline_run import KEY_NAMES

SERVICE = "NeuralLoop"
_memory: dict[str, str] = {}
_lock = threading.Lock()


def _keyring():
    try:
        import keyring
        from keyring.backends import fail

        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def persistent() -> bool:
    return _keyring() is not None


def read(name: str) -> str:
    store = _keyring()
    if store is None:
        return _memory.get(name, "")
    try:
        return store.get_password(SERVICE, name) or ""
    except Exception:
        return ""


def save(name: str, value: str) -> None:
    if name not in KEY_NAMES:
        raise ValueError(f"Not a key NeuralLoop keeps: {name}")
    value = value.strip()
    with _lock:
        store = _keyring()
        if store is None:
            if value:
                _memory[name] = value
            else:
                _memory.pop(name, None)
            return
        if value:
            store.set_password(SERVICE, name, value)
        else:
            with contextlib.suppress(Exception):
                store.delete_password(SERVICE, name)


def all_keys() -> dict[str, str]:
    return {name: read(name) for name in KEY_NAMES}
