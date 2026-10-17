"""How Pip reaches you: notifications, the big on-screen Pip, and the nudge and chapter-ready looks."""

import json

import pytest
from neuralloop_desktop.app import moment, notify
from neuralloop_desktop.app.library import Library
from neuralloop_desktop.core import nudges


def test_what_windows_says_maps_to_the_moment():
    assert moment.from_state(None, False) == {
        "screenLocked": False,
        "fullScreenInFront": False,
        "microphoneInUse": False,
    }
    assert moment.from_state(moment.QUNS_NOT_PRESENT, False)["screenLocked"]
    for busy in (moment.QUNS_BUSY, moment.QUNS_RUNNING_D3D_FULL_SCREEN, moment.QUNS_PRESENTATION_MODE):
        assert moment.from_state(busy, False)["fullScreenInFront"]
    assert moment.from_state(5, True)["microphoneInUse"]


class Recorder:
    def __init__(self, shows=True):
        self.shown, self.toasts, self.played = [], [], []
        self.shows = shows

    def big_pip(self, nudge):
        self.shown.append(nudge["mood"])
        return self.shows


def notifier(monkeypatch, settings=None, now=None):
    rec = Recorder()
    n = notify.Notifier(
        lambda: settings or nudges.default_settings(), lambda _id: None, rec.big_pip, lambda _m: None
    )
    n.toast = lambda title, body, book_id="", silent=False: rec.toasts.append((title, silent))
    n.play = lambda mood: rec.played.append(mood) or True
    monkeypatch.setattr(moment, "now", lambda: now or {})
    return n, rec


def test_a_silly_nudge_shows_the_big_pip_and_its_toast_stays_silent(monkeypatch):
    n, rec = notifier(monkeypatch)
    n.post("🎻 Pip is playing a tiny sad violin", "4 cards are ready.", nudge=nudges.sample("sadViolin"))
    assert rec.shown == ["sadViolin"] and rec.toasts == [("🎻 Pip is playing a tiny sad violin", True)]


def test_during_a_call_or_a_game_it_stays_a_notification(monkeypatch):
    n, rec = notifier(monkeypatch, now={"microphoneInUse": True})
    n.post("😱 FAHHH!", "", nudge=nudges.sample("shocked"))
    assert rec.shown == [] and rec.toasts == [("😱 FAHHH!", False)]
    n, rec = notifier(monkeypatch, now={"fullScreenInFront": True})
    n.post("😿", "", nudge=nudges.sample("sadMeow"), test=True)  # a test from Settings is still heard
    assert rec.played == ["sadMeow"] and rec.toasts[0][1] is True


def test_a_gentle_nudge_or_chapter_ready_is_just_a_toast(monkeypatch):
    n, rec = notifier(monkeypatch)
    n.post("🐾 4 cards are ready", "About 1 min", nudge=nudges.sample("gentle"))
    n.post("Chapter 2 is ready to study", "…", book_id="caching")
    assert rec.shown == [] and rec.played == [] and len(rec.toasts) == 2 and not rec.toasts[0][1]


def test_without_toasts_the_tray_balloon_carries_it(monkeypatch):
    n = notify.Notifier(nudges.default_settings, lambda _id: None, lambda _n: False, lambda _m: None)
    n._toaster = None
    seen = []
    n.tray_notify = lambda title, body: seen.append((title, body))
    n.toast("Hi", "there")
    assert seen == [("Hi", "there")]


def test_the_library_sends_a_nudge_and_remembers_it(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURALLOOP_HOME", str(tmp_path))
    told = []
    library = Library(notify=lambda **kw: told.append(kw))
    library.settings.set("nudgeSettings", {**nudges.default_settings(), "quietStart": 0, "quietEnd": 0})
    library.send_nudge(nudges.sample("gentle"), day="2026-10-17")
    history = nudges.parse_history(library.settings.get("nudgeHistory"))
    assert told and told[0]["nudge"]["mood"] == "gentle" and history["lastSentDay"] == "2026-10-17"
    library.send_nudge(nudges.sample("shocked"), test=True)  # tests from Settings aren't remembered
    assert nudges.parse_history(library.settings.get("nudgeHistory"))["lastSentDay"] == "2026-10-17"
    library.engaged()
    assert nudges.parse_history(library.settings.get("nudgeHistory"))["lastEngaged"] > 0
    library.pause_until_tomorrow()
    assert library.nudge_settings()["pausedUntil"] > 0
    assert json.loads((tmp_path / "settings.json").read_text())["nudgeHistory"]["lastMood"] == "gentle"


def test_a_tick_with_nothing_to_say_sends_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURALLOOP_HOME", str(tmp_path))
    told = []
    library = Library(notify=lambda **kw: told.append(kw))
    library.nudge_tick()
    assert told == []


def test_the_tray_menu_offers_what_pip_can_do(monkeypatch, tmp_path):
    """pystray is replaced by a stand-in that records the menu (a test machine has no notification area)."""
    pytest.importorskip("PIL", reason="the tray icon is drawn with Pillow")
    import sys
    import types

    from neuralloop_desktop.app import tray

    built = {}

    class Item:
        def __init__(self, text, action, default=False, enabled=True):
            self.text, self.action, self.enabled = text, action, enabled

    class Menu:
        SEPARATOR = None

        def __init__(self, *items):
            built["items"] = [i for i in items if i is not None]

    class Icon:
        def __init__(self, name, image, title, menu):
            built["title"] = title

        def run_detached(self):
            built["running"] = True

        def notify(self, body, title):
            built["notified"] = (title, body)

        def stop(self):
            built["running"] = False

    monkeypatch.setitem(sys.modules, "pystray", types.SimpleNamespace(Menu=Menu, MenuItem=Item, Icon=Icon))
    monkeypatch.setenv("NEURALLOOP_HOME", str(tmp_path))
    library = Library()
    calls = []
    actions = {
        name: (lambda name=name: calls.append(name))
        for name in ("open", "panel", "settings", "resume", "review", "quit")
    }
    t = tray.Tray(library, actions)
    assert t.start() and built["running"] and built["title"] == "NeuralLoop"
    labels = [i.text if isinstance(i.text, str) else i.text(i) for i in built["items"]]
    assert labels[:2] == ["Open NeuralLoop", "Pip's panel"]
    assert "Nothing to continue yet" in labels and "No cards due" in labels and "Quit NeuralLoop" in labels
    for item in built["items"]:
        if item.text in ("Open NeuralLoop", "Quit NeuralLoop"):
            item.action()
    assert calls == ["open", "quit"]
    t.notify("Chapter 1 is ready", "…")
    assert built["notified"] == ("Chapter 1 is ready", "…")
    t.stop()
    assert built["running"] is False


def test_the_big_pips_window_closes_when_pip_is_done(monkeypatch, tmp_path):
    """It's made for each nudge (a hidden one made at launch showed up empty), so done means closed."""
    from neuralloop_desktop.app.api import Api

    monkeypatch.setenv("NEURALLOOP_HOME", str(tmp_path))
    api = Api(Library(), "http://127.0.0.1:1/token")

    class Window:
        closed = 0

        def destroy(self):
            Window.closed += 1

    api._attach("pip", Window())
    api.hide_big_pip()
    api.hide_big_pip()  # nothing left to close
    assert Window.closed == 1 and "pip" not in api._windows


def test_signing_in_shows_the_allowance_without_waiting(monkeypatch, tmp_path):
    """The allowance was read at launch (signed out) and then only every five minutes; the account page and
    a sign-in now ask for it fresh."""
    from neuralloop_desktop.app import runner
    from neuralloop_desktop.app.api import Api

    monkeypatch.setenv("NEURALLOOP_HOME", str(tmp_path))
    report = {"known": True, "available": True, "fiveHour": {"remaining": 80, "resetsAt": ""},
              "weekly": {"remaining": 95, "resetsAt": ""}, "podcast": True, "video": False}  # fmt: skip
    asked = []

    def once(arguments, timeout=60, stdin=None):
        asked.append(arguments[0])
        if arguments[0] == "--usage":
            return 0, ["NotebookLM usage: " + json.dumps(report)]
        if arguments[0] == "--signin":
            return 0, []
        return 0, ['Account: {"signedIn": true, "email": "a@b.c"}']

    monkeypatch.setattr(runner, "once", once)
    monkeypatch.setattr(runner, "stream", lambda arguments, heard, cancel=None: 0)
    library = Library()
    library.usage, library.usage_checked = {"known": False}, __import__("time").time()  # read at launch
    api = Api(library, "http://127.0.0.1:1/token")
    assert api.usage(fresh=True)["fiveHour"]["remaining"] == 80

    library.usage = {"known": False}
    api.sign_in()
    assert library.usage["known"] is True and asked.count("--usage") == 2


def test_a_fresh_allowance_check_still_waits_while_a_book_is_being_prepared(monkeypatch, tmp_path):
    """Every NotebookLM command rotates Google's session cookie; one alongside a run can sign it out."""
    from neuralloop_desktop.app import runner

    monkeypatch.setenv("NEURALLOOP_HOME", str(tmp_path))
    asked = []
    monkeypatch.setattr(
        runner, "once", lambda arguments, timeout=60, stdin=None: asked.append(arguments) or (0, [])
    )
    library = Library()
    library.usage = {"known": True}
    monkeypatch.setattr(library, "entries", lambda: [{"preparing": True}])
    assert library.refresh_usage(force=True) == {"known": True} and asked == []
    monkeypatch.setattr(library, "entries", lambda: [{"preparing": False}])
    library.refresh_usage(force=True)
    assert asked == [["--usage"]]


def test_an_expired_sign_in_comes_through_from_the_allowance_check():
    from neuralloop_desktop.core import prep

    line = 'NotebookLM usage: {"known": false, "problem": "expired (AUTH_ERROR)", "needsSignIn": true}'
    assert prep.parse_usage(line)["needsSignIn"] is True
    assert prep.parse_usage('NotebookLM usage: {"known": true}')["needsSignIn"] is False
