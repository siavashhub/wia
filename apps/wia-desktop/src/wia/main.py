"""Entry point: launch FastAPI in a background thread, then open a pywebview window."""

from __future__ import annotations

import logging
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from wia.app import create_app
from wia.config import get_settings

log = logging.getLogger(__name__)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_ready(url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=0.5)
            if r.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"FastAPI did not become ready at {url}")


def _resolve_icon_path() -> str | None:
    """Return a path to a Windows-friendly ``.ico`` for the app icon.

    The shipped asset is a PNG (``ui/logo.png``). On Windows the
    taskbar / window icon needs ``.ico`` format; we generate one next to
    the PNG using Pillow (lazily cached). On non-Windows platforms we
    return the PNG directly. Any failure logs and returns ``None`` so the
    app still launches with the platform default icon.
    """
    settings = get_settings()
    ui_dir = Path(__file__).parent / "ui"
    # Look in a few likely locations so the resolver keeps working if the
    # asset is moved between ``ui/`` and ``ui/static/``.
    candidates = [ui_dir / "logo.png", ui_dir / "static" / "logo.png"]
    png_path = next((p for p in candidates if p.exists()), None)
    if png_path is None:
        return None

    if not sys.platform.startswith("win"):
        return str(png_path)

    # Windows: convert to .ico, cached in the user cache dir so we don't
    # touch the (potentially read-only) install directory.
    ico_path = settings.cache_dir / "logo.ico"
    try:
        png_mtime = png_path.stat().st_mtime
        if ico_path.exists() and ico_path.stat().st_mtime >= png_mtime:
            return str(ico_path)
        from PIL import Image  # type: ignore[import-not-found]

        img = Image.open(png_path).convert("RGBA")
        img.save(
            ico_path,
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        return str(ico_path)
    except Exception as exc:
        log.warning("Could not generate window icon (%s); using default", exc)
        return None


def _set_windows_app_user_model_id(app_id: str) -> None:
    """Tell Windows this is a distinct app so the taskbar uses our icon
    instead of grouping under the generic Python interpreter icon.

    Safe no-op on non-Windows or when ctypes/shell32 isn't available.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)  # type: ignore[attr-defined]
    except Exception as exc:
        log.debug("SetCurrentProcessExplicitAppUserModelID failed: %s", exc)


def run() -> None:
    """Launch the desktop app."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    _set_windows_app_user_model_id("WIA.WorkIntelligenceAgent")

    port = _find_free_port()
    app = create_app()

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    server = uvicorn.Server(config)

    server_thread = threading.Thread(target=server.run, daemon=True, name="wia-uvicorn")
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"
    _wait_until_ready(f"{base_url}/api/health")

    # Import lazily so headless environments (e.g., CI tests) don't need WebView2.
    import webview  # type: ignore[import-not-found]

    class WiaJsApi:
        """Bridge exposed to the WebView via ``window.pywebview.api.*``.

        WebView2 does not surface a download manager for ``Blob`` URLs, so the
        UI calls back into Python to pop a native Save dialog and write the
        file. Returns the saved path (or ``None`` if cancelled).
        """

        def save_file(
            self,
            suggested_name: str,
            content: str,
            file_types: list[str] | None = None,
        ) -> str | None:
            try:
                window = webview.windows[0]
            except IndexError:
                return None
            types = tuple(file_types) if file_types else ("All files (*.*)",)
            result = window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=suggested_name,
                file_types=types,
            )
            if not result:
                return None
            # pywebview returns either a string or a single-element tuple/list.
            path = result if isinstance(result, str) else result[0]
            try:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(content)
            except OSError as exc:
                log.exception("save_file failed: %s", exc)
                return None
            return path

    webview.create_window(
        title=settings.window_title,
        url=base_url,
        width=settings.window_width,
        height=settings.window_height,
        js_api=WiaJsApi(),
    )
    icon_path = _resolve_icon_path()
    try:
        if icon_path:
            try:
                webview.start(icon=icon_path)
            except TypeError:
                # Older pywebview without the ``icon`` kwarg.
                webview.start()
        else:
            webview.start()
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)


if __name__ == "__main__":
    run()
