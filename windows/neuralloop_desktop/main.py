"""NeuralLoop for Windows: the app, and (installed) its own pipeline.

NeuralLoop.exe                      the app: library window, Pip in the notification area
NeuralLoop.exe --pipeline ARGS      the book pipeline (what the app runs for every book)
NeuralLoop.exe -m notebooklm ...    the tools the pipeline runs as modules of this same Python
"""

import contextlib
import json
import runpy
import sys
import threading
import urllib.request

RUNNABLE_MODULES = {"notebooklm", "playwright"}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--pipeline"]:
        from neuralloop_books.cli import main as pipeline

        sys.argv = ["neuralloop", *argv[1:]]
        return pipeline() or 0
    if argv[:1] == ["-m"] and len(argv) > 1 and argv[1].split(".")[0] in RUNNABLE_MODULES:
        sys.argv = [argv[1], *argv[2:]]
        runpy.run_module(argv[1], run_name="__main__", alter_sys=True)
        return 0
    return run_app()


def run_app() -> int:
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
    big = webview.create_window(
        "Pip says hi",
        f"{base}/ui/pip.html",
        js_api=api,
        width=440,
        height=480,
        hidden=True,
        frameless=True,
        on_top=True,
        transparent=True,
        focus=False,
        resizable=False,
        easy_drag=False,
    )
    api._attach("main", main_window)
    api._attach("panel", panel)
    api._attach("pip", big)

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
        screen = webview.screens[0]
        big.move((screen.width - 440) // 2, (screen.height - 480) // 2)
        big.show()
        settings = library.nudge_settings()
        payload = json.dumps(
            {**nudge, "volume": settings["volume"], "sound": f"{base}/sound/{nudge['mood']}.wav"}
        )
        big.evaluate_js(f"window.BigPip && window.BigPip.show({payload})")
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
        for window in (big, panel, main_window):
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
        library.start()

    webview.start(
        started,
        gui="edgechromium" if portable.WINDOWS else None,
        private_mode=False,
        storage_path=str(paths.home() / "webview"),
        icon=str(icon_file()),
    )
    quitting.set()
    library.stop()
    tray.stop()
    return 0


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
