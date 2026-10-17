"""NeuralLoop for Windows: the app, and (installed) its own pipeline.

NeuralLoop.exe                      the app: library window, Pip in the notification area
nl-book.exe ARGS                    the book pipeline (what the app runs for every book; a console program, so
                                    its output reaches the app and a terminal)
nl-book.exe -m notebooklm ...       the tools the pipeline runs as modules of this same Python
NeuralLoop.exe --background         started with Windows: just Pip in the notification area, no window
"""

import contextlib
import json
import os
import runpy
import sys
import threading
import urllib.request
from pathlib import Path

RUNNABLE_MODULES = {"notebooklm", "playwright"}
PIPELINE_PROGRAM = "nl-book"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if is_pipeline_program() and argv[:1] not in (["-m"], ["--pipeline"]):
        argv = ["--pipeline", *argv]
    if argv[:1] == ["--pipeline"]:
        from neuralloop_books.cli import main as pipeline

        utf8_output()

        sys.argv = ["neuralloop", *argv[1:]]
        return pipeline() or 0
    if argv[:1] == ["-m"] and len(argv) > 1 and argv[1].split(".")[0] in RUNNABLE_MODULES:
        sys.argv = [argv[1], *argv[2:]]
        runpy.run_module(argv[1], run_name="__main__", alter_sys=True)
        return 0
    if argv[:1] == ["--browser"]:
        return run_browser()
    return run_app(background=argv[:1] == ["--background"])


def utf8_output() -> None:
    """The pipeline's lines are UTF-8 whatever the console's code page (the app reads them as UTF-8, and
    cp1252 has no ✓). The installed programs may not read PYTHONIOENCODING, so it's set here."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            with contextlib.suppress(ValueError, OSError):  # a stream that can't change: leave it as it is
                stream.reconfigure(encoding="utf-8", errors="replace")


def is_pipeline_program() -> bool:
    """Installed, `nl-book.exe` is the pipeline: the same files as the app, built as a console program."""
    return bool(getattr(sys, "frozen", False)) and Path(sys.executable).stem.lower() == PIPELINE_PROGRAM


def run_browser() -> int:
    """Development: the app in an ordinary browser (no tray, no native dialogs), for working on the window."""
    import time
    import webbrowser

    from .app.api import Api
    from .app.library import Library
    from .app.server import Server

    server = Server()
    library = Library()
    api = Api(library, server.base)
    api._events = server.events
    library.emit = api._emit
    server.rpc = api
    server.start()
    library.start()
    url = f"{server.base}/ui/index.html?browser=1"
    print(f"NeuralLoop is at {url}", flush=True)
    webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


def run_app(background: bool = False) -> int:
    import webview
    from neuralloop_books import portable

    from .app import paths
    from .app.api import Api
    from .app.library import Library
    from .app.notify import Notifier
    from .app.server import Server
    from .app.tray import Tray

    if another_instance():
        return 0
    server = Server()
    holder: dict = {}

    def emit(name: str, data) -> None:
        api = holder.get("api")
        if api:
            api._emit(name, data)

    library = Library(emit=emit)
    api = Api(library, server.base)
    holder["api"] = api
    base = server.base
    quiet = background
    background = "#1D1716" if dark_mode() else "#FFF7F2"
    main_window = webview.create_window(
        "NeuralLoop",
        f"{base}/ui/index.html",
        js_api=api,
        width=1240,
        height=860,
        min_size=(900, 640),
        background_color=background,
        text_select=True,
        hidden=quiet,
    )
    panel = webview.create_window(
        "Pip",
        f"{base}/ui/index.html#panel",
        js_api=api,
        width=380,
        height=540,
        hidden=True,
        frameless=True,
        on_top=True,
        resizable=False,
        background_color=background,
        easy_drag=False,
    )
    api._attach("main", main_window)
    api._attach("panel", panel)

    def show_main(book_id: str | None = None, page: str | None = None) -> None:
        panel.hide()
        main_window.show()
        main_window.restore()
        if book_id:
            api._emit("open", book_id)
        if page:
            api._emit("page", page)

    def show_panel() -> None:
        screen = webview.screens[0]
        panel.move(screen.width - 380 - 16, screen.height - 540 - 64)
        panel.show()
        api._emit("panel", True)

    def big_pip(nudge: dict) -> bool:
        """The big Pip's window is made for one nudge and closed when it ends (`Api.hide_big_pip`): a hidden
        window made at launch showed up empty on some PCs. Windows can't make a WebView2 window see-through,
        so there it has the app's background."""
        settings = library.nudge_settings()
        payload = json.dumps(
            {**nudge, "volume": settings["volume"], "sound": f"{base}/sound/{nudge['mood']}.wav"}
        )
        api.hide_big_pip()
        screen = webview.screens[0]
        big = webview.create_window(
            "Pip says hi",
            f"{base}/ui/pip.html",
            js_api=api,
            width=440,
            height=480,
            x=(screen.width - 440) // 2,
            y=(screen.height - 480) // 2,
            frameless=True,
            on_top=True,
            transparent=not portable.WINDOWS,
            background_color=background,
            focus=False,
            resizable=False,
            easy_drag=False,
        )
        big.events.loaded += lambda: big.evaluate_js(f"window.BigPip && window.BigPip.show({payload})")
        api._attach("pip", big)
        return True

    notifier = Notifier(
        library.nudge_settings, lambda book_id: show_main(book_id or None), big_pip, server.sound
    )
    library.notify = lambda **kw: notifier.post(**kw)
    tray = Tray(
        library,
        {
            "open": show_main,
            "panel": show_panel,
            "settings": lambda: show_main(page="settings"),
            "resume": lambda: show_main(page="resume"),
            "review": lambda: show_main(page="review"),
            "quit": lambda: quit_app(),
        },
    )
    quitting = threading.Event()

    def quit_app() -> None:
        quitting.set()
        api._flush_all()
        library.stop()
        tray.stop()
        api.hide_big_pip()
        for window in (panel, main_window):
            with contextlib.suppress(Exception):
                window.destroy()

    def closing() -> bool:
        """Closing the window keeps Pip in the notification area, like the Mac's menu bar."""
        if quitting.is_set() or not tray_running.is_set():
            api._flush_all()
            return True
        main_window.hide()
        return False

    tray_running = threading.Event()
    main_window.events.closing += closing

    def on_loaded() -> None:
        from webview.dom import DOMEventHandler

        def dropped(event: dict) -> None:
            files = (event.get("dataTransfer") or {}).get("files") or []
            found = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
            if found:
                api.add_paths(found)

        with contextlib.suppress(Exception):  # no drag and drop here: Add a book still works
            main_window.dom.document.events.drop += DOMEventHandler(dropped, prevent_default=True)

    main_window.events.loaded += on_loaded
    server.on_show = lambda: show_main()
    server.start()  # before the windows load their pages
    remember_instance(server)

    def started() -> None:
        if tray.start():
            tray_running.set()
            notifier.tray_notify = tray.notify
        elif quiet:
            main_window.show()  # no notification area to wait in: the window is the only way in
        library.start()

    webview.start(
        started,
        gui="edgechromium" if portable.WINDOWS else None,
        private_mode=False,
        storage_path=str(paths.home() / "webview"),
        icon=str(icon_file()),
    )
    quitting.set()
    api._flush_all()
    library.stop()
    tray.stop()
    # Quitting ends the process, whatever is still winding down (a tray or WebView2 thread can otherwise keep
    # NeuralLoop.exe alive, and an installer then finds it "still running"). Progress is saved above; a book
    # being prepared carries on in nl-book.exe.
    os._exit(0)


def icon_file():
    from .app import paths
    from .app.notify import icon_png

    ico = paths.bundle() / "NeuralLoop.ico"
    return ico if ico.exists() else icon_png()


def dark_mode() -> bool:
    from neuralloop_books import portable

    if not portable.WINDOWS:
        return False
    import winreg

    with contextlib.suppress(OSError):
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    return False


def another_instance() -> bool:
    """One NeuralLoop at a time: a second launch brings the first one's window forward and leaves."""
    from .app import paths
    from .app.store import JsonFile

    info = JsonFile(paths.home() / "instance.json").read()
    url = info.get("show")
    if not isinstance(url, str) or not url.startswith("http://127.0.0.1:"):
        return False
    try:
        with urllib.request.urlopen(url, timeout=2) as answer:
            return answer.status == 200
    except OSError:
        return False


def remember_instance(server) -> None:
    from .app import paths
    from .app.store import JsonFile

    JsonFile(paths.home() / "instance.json").write({"show": f"{server.base}/show"})


if __name__ == "__main__":
    raise SystemExit(main())
