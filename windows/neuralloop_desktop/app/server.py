"""The window's own little web server, on 127.0.0.1 only, behind a random token in every path.

It serves the window's files, Pip's poses and fonts (the pipeline's own), a book's media (with byte ranges, so
podcasts and videos can seek), PDF chapter pages as pictures, and Silly mode's sounds (converted from the
Mac's
.caf once). A book's files are served only from inside that book's folder; anything else is a 404.
"""

import contextlib
import json
import mimetypes
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..core import book as books
from ..core import pipeline_run
from . import paths

MOODS = {
    "sadViolin": "NeuralLoop-sad-violin",
    "sadMeow": "NeuralLoop-sad-meow",
    "shocked": "NeuralLoop-fahhh",
}
TYPES = {
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".wav": "audio/wav",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".html": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


def contained(root: Path, relative: str) -> Path | None:
    """A path under `root`, never outside it (no "..", no drive letters, no absolute paths)."""
    if not relative or relative.startswith("/") or "\\" in relative or ":" in relative or "\x00" in relative:
        return None
    base = root.resolve()
    try:
        path = (root / relative).resolve()
    except OSError:
        return None
    return path if base in path.parents else None


class Server:
    def __init__(self):
        self.token = secrets.token_urlsafe(24)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._render_lock = threading.Lock()
        self.on_show = lambda: None  # a second launch asks this one to come forward
        self.rpc = None  # development (--browser): the window's bridge over HTTP, and its events
        self.events: list = []

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/{self.token}"

    def start(self) -> None:
        threading.Thread(target=self.httpd.serve_forever, name="server", daemon=True).start()

    def stop(self) -> None:
        self.httpd.shutdown()

    def resolve(self, route: str) -> tuple[Path | None, str | None]:
        """(file to send, content type) for a path after the token, or (None, None)."""
        parts = route.split("/", 1)
        kind, rest = parts[0], (parts[1] if len(parts) > 1 else "")
        if kind == "ui":
            return contained(paths.ui(), rest or "index.html"), None
        if kind == "assets":
            return contained(paths.pipeline_assets(), rest), None
        if kind == "book":
            book_id, _, relative = rest.partition("/")
            if not pipeline_run.is_valid_id(book_id):
                return None, None
            folder = paths.books() / book_id
            if relative.startswith("."):  # private files (locks, page cache, …) are never served
                return None, None
            return books.file_in(folder, relative), None
        if kind == "page":
            return self.pdf_page(rest), "image/png"
        if kind == "sound":
            return self.sound(rest.removesuffix(".wav")), "audio/wav"
        return None, None

    def pdf_page(self, rest: str) -> Path | None:
        """`<book>/<chapter pdf path>/<page>.png`: one page of a chapter's PDF, drawn once and kept."""
        m = re.fullmatch(r"([a-z0-9-]+)/(.+\.pdf)/(\d+)\.png", rest)
        if not m or not pipeline_run.is_valid_id(m[1]):
            return None
        folder = paths.books() / m[1]
        pdf = books.file_in(folder, m[2])
        if not pdf or not pdf.exists():
            return None
        index = int(m[3])
        cache = folder / ".pages" / f"{pdf.stem}-{index:04d}.png"
        if cache.exists() and cache.stat().st_mtime >= pdf.stat().st_mtime:
            return cache
        with self._render_lock:
            try:
                import pypdfium2 as pdfium

                document = pdfium.PdfDocument(str(pdf))
                if index >= len(document):
                    return None
                page = document[index]
                image = page.render(scale=1.6).to_pil()
                cache.parent.mkdir(exist_ok=True)
                partial = cache.with_suffix(".part")
                image.save(partial, format="PNG", optimize=True)
                partial.replace(cache)
                document.close()
            except Exception:
                return None
        return cache

    def sound(self, mood: str) -> Path | None:
        """Silly mode's sound for a mood, as WAV (Edge plays it; the Mac ships CAF)."""
        name = MOODS.get(mood)
        if not name:
            return None
        cache = paths.home() / "sounds" / f"{name}.wav"
        if cache.exists():
            return cache
        source = paths.sounds() / f"{name}.caf"
        if not source.exists():
            return None
        try:
            import av

            cache.parent.mkdir(parents=True, exist_ok=True)
            partial = cache.with_suffix(".part")
            with av.open(str(source)) as src, av.open(str(partial), "w", format="wav") as out:
                heard = src.streams.audio[0]
                stream = out.add_stream(
                    "pcm_s16le", rate=heard.rate, layout="stereo" if heard.channels > 1 else "mono"
                )
                resampler = av.AudioResampler(format="s16", layout=stream.layout, rate=heard.rate)
                for frame in src.decode(heard):
                    for ready in resampler.resample(frame):
                        out.mux(stream.encode(ready))
                out.mux(stream.encode(None))
            partial.replace(cache)
        except Exception:
            return None
        return cache

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:  # quiet
                return

            def _deny(self, code: int = 404) -> None:
                self.send_response(code)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_HEAD(self) -> None:
                self._serve(body=False)

            def do_GET(self) -> None:
                if server.rpc is not None and self.path == f"/{server.token}/events" and self._trusted():
                    events, server.events[:] = list(server.events), []
                    return self._json(events)
                self._serve(body=True)

            def do_POST(self) -> None:
                """Development only: `/rpc/<method>` calls the window's bridge (never its private names)."""
                prefix = f"/{server.token}/rpc/"
                if server.rpc is None or not self.path.startswith(prefix) or not self._trusted():
                    return self._deny(404)
                name = self.path[len(prefix) :]
                method = (
                    getattr(server.rpc, name, None)
                    if name.isidentifier() and not name.startswith("_")
                    else None
                )
                if not callable(method):
                    return self._deny(404)
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    args = json.loads(self.rfile.read(length) or b"[]")
                    return self._json({"result": method(*args)})
                except Exception as error:
                    return self._json({"error": str(error)})

            def _trusted(self) -> bool:
                return self.headers.get("Host") in (f"127.0.0.1:{server.port}", f"localhost:{server.port}")

            def _json(self, value) -> None:
                data = json.dumps(value, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _serve(self, body: bool) -> None:
                # Only this app's own window: the right host (no DNS rebinding) and the right token.
                if self.headers.get("Host") not in (f"127.0.0.1:{server.port}", f"localhost:{server.port}"):
                    return self._deny(403)
                path = unquote(urlsplit(self.path).path)
                prefix = f"/{server.token}/"
                if not path.startswith(prefix):
                    return self._deny(404)
                route = path[len(prefix) :]
                if route == "show":
                    with contextlib.suppress(Exception):
                        server.on_show()
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                file, kind = server.resolve(route)
                if not file or not file.is_file():
                    return self._deny(404)
                kind = (
                    kind
                    or TYPES.get(file.suffix.lower())
                    or mimetypes.guess_type(file.name)[0]
                    or "application/octet-stream"
                )
                size = file.stat().st_size
                start, end = 0, size - 1
                ranged = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
                if ranged and size:
                    if ranged[1]:
                        start = int(ranged[1])
                        end = min(int(ranged[2]), size - 1) if ranged[2] else size - 1
                    elif ranged[2]:
                        start = max(0, size - int(ranged[2]))
                    if start > end or start >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                else:
                    self.send_response(200)
                length = end - start + 1 if size else 0
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if not body or not length:
                    return
                with contextlib.suppress(ConnectionError, OSError), open(file, "rb") as handle:
                    handle.seek(start)
                    left = length
                    while left > 0:
                        chunk = handle.read(min(1 << 16, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)

        return Handler
