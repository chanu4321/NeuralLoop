"""settings.json and runs.json: every change is one read, change and write under one lock."""

import threading

from neuralloop_desktop.app.store import JsonFile


def test_changes_from_many_threads_are_never_lost(tmp_path):
    store = JsonFile(tmp_path / "settings.json")

    def add(n):
        store.update(lambda data: data.setdefault("seen", []).append(n))

    threads = [threading.Thread(target=add, args=(n,)) for n in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(store.get("seen")) == list(range(40))


def test_set_keeps_other_keys_written_at_the_same_time(tmp_path):
    store = JsonFile(tmp_path / "settings.json")
    threads = [threading.Thread(target=store.set, args=(f"k{n}", n)) for n in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert store.read() == {f"k{n}": n for n in range(30)}


def test_update_returns_what_the_change_returns_and_reads_leniently(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("[1, 2]")  # valid JSON, not an object
    store = JsonFile(path)
    assert store.update(lambda data: data.setdefault("n", 1)) == 1
    assert store.read() == {"n": 1}
