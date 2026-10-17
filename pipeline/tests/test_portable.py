"""The operating-system differences (POSIX and Windows): the book's lock, process trees, memory, folders."""

import subprocess
import sys
import types

import pytest

from neuralloop_books import portable


def test_lock_is_exclusive_between_handles(tmp_path):
    path = tmp_path / ".running"
    first = open(path, "a+")  # noqa: SIM115
    second = open(path, "a+")  # noqa: SIM115
    try:
        portable.try_lock(first)
        with pytest.raises(portable.LockBusy):  # a second open file is refused, even in the same process
            portable.try_lock(second)
    finally:
        first.close()
        second.close()


def test_lock_is_released_when_the_handle_closes(tmp_path):
    path = tmp_path / ".running"
    with open(path, "a+") as first:
        portable.try_lock(first)
    with open(path, "a+") as again:
        portable.try_lock(again)


class FakeMsvcrt(types.ModuleType):
    LK_NBLCK = 2

    def __init__(self, busy: bool):
        super().__init__("msvcrt")
        self.busy = busy
        self.calls: list[tuple[int, int, int]] = []

    def locking(self, fd: int, mode: int, size: int) -> None:
        if self.busy:
            raise OSError(36, "Resource deadlock avoided")
        self.calls.append((fd, mode, size))


def test_windows_locks_one_byte_far_past_the_pid(tmp_path, monkeypatch):
    fake = FakeMsvcrt(busy=False)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(portable, "WINDOWS", True)
    with open(tmp_path / ".running", "a+") as handle:
        portable.try_lock(handle)
        assert fake.calls == [(handle.fileno(), fake.LK_NBLCK, 1)]
        assert handle.tell() == 0  # writing the pid starts at the beginning again


def test_windows_lock_held_elsewhere_is_busy(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt(busy=True))
    monkeypatch.setattr(portable, "WINDOWS", True)
    with open(tmp_path / ".running", "a+") as handle, pytest.raises(portable.LockBusy):
        portable.try_lock(handle)


def test_background_children_get_their_own_group(monkeypatch):
    monkeypatch.setattr(portable, "WINDOWS", False)
    assert portable.own_group() == {"start_new_session": True}
    assert portable.no_window() == {}
    monkeypatch.setattr(portable, "WINDOWS", True)
    flags = portable.own_group()["creationflags"]
    assert flags & portable.CREATE_NEW_PROCESS_GROUP
    assert flags & portable.CREATE_NO_WINDOW
    assert portable.no_window() == {"creationflags": portable.CREATE_NO_WINDOW}


def test_end_tree_on_windows_asks_taskkill_politely_then_firmly(monkeypatch):
    monkeypatch.setattr(portable, "WINDOWS", True)
    ran: list[list[str]] = []
    monkeypatch.setattr(portable.subprocess, "run", lambda argv, **kw: ran.append(argv))

    class Stubborn:
        pid = 4242

        def __init__(self):
            self.waits = 0

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("x", timeout)
            return 0

    portable.end_tree(Stubborn(), wait=0)
    assert ran[0] == ["taskkill", "/T", "/PID", "4242"]
    assert ran[1] == ["taskkill", "/T", "/F", "/PID", "4242"]


def test_end_tree_on_posix_ends_the_group():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **portable.own_group())
    portable.end_tree(process, wait=5)
    assert process.poll() is not None


def test_total_memory_is_plausible():
    assert 256 * 1024**2 < portable.total_memory() < 64 * 1024**4


def test_windows_memory_comes_from_the_kernel(monkeypatch):
    monkeypatch.setattr(portable, "WINDOWS", True)
    monkeypatch.setattr(portable, "_windows_memory", lambda: 16 * 1024**3)
    assert portable.total_memory() == 16 * 1024**3


def test_windows_app_data_is_under_appdata(monkeypatch):
    monkeypatch.setattr(portable, "WINDOWS", True)
    folder = portable.app_data({"APPDATA": "C:/Users/pip/AppData/Roaming"})
    assert folder.parts[-1] == "NeuralLoop" and "Roaming" in folder.parts


def test_windows_chrome_is_looked_for_in_program_files(monkeypatch):
    monkeypatch.setattr(portable, "WINDOWS", True)
    paths = portable.chrome_paths(
        {"PROGRAMFILES": "C:/Program Files", "LOCALAPPDATA": "C:/Users/pip/AppData/Local"}
    )
    assert [p.name for p in paths] == ["chrome.exe", "chrome.exe"]
    assert "Program Files" in paths[0].parts
