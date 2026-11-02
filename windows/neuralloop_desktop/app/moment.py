"""What's going on at this PC right now, for Silly mode's big Pip (NudgeDelivery's NudgeMoment): it only shows
when the screen isn't locked, nothing full-screen is in front on any display (a game, a video, a
presentation, a Store app), and no app is using the microphone (a call or a meeting is likely). Otherwise the
nudge stays a notification.

Windows answers through SHQueryUserNotificationState (which looks at the main display only), the window in
front measured against every display, and the privacy settings' own record of which apps are using the
microphone right now. Elsewhere nothing is known, which reads as calm.
"""

import contextlib

from neuralloop_books import portable

# SHQueryUserNotificationState answers.
QUNS_NOT_PRESENT = 1  # the screen is locked, the screen saver is on, or fast user switching is under way
QUNS_BUSY = 2  # a full-screen app is in front
QUNS_RUNNING_D3D_FULL_SCREEN = 3  # a full-screen game or video
QUNS_PRESENTATION_MODE = 4  # presentation settings are on
QUNS_QUIET_TIME = 6  # Focus (do not disturb) or the first hour after setup: Windows holds notifications
QUNS_APP = 7  # a Store app is full screen

Rect = tuple[int, int, int, int]  # left, top, right, bottom


def from_state(state: int | None, microphone: bool, fills_a_display: bool = False) -> dict:
    return {
        "screenLocked": state == QUNS_NOT_PRESENT,
        "fullScreenInFront": fills_a_display
        or state in (QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE, QUNS_APP),
        "microphoneInUse": microphone,
        "quietTime": state == QUNS_QUIET_TIME,
    }


def fills_one(window: Rect, displays: list[Rect]) -> bool:
    """Whether a window covers a whole display (a maximised window stops at the taskbar; full screen
    doesn't)."""
    left, top, right, bottom = window
    return any(
        left <= d_left and top <= d_top and right >= d_right and bottom >= d_bottom
        for d_left, d_top, d_right, d_bottom in displays
    )


def _foreground_fills_a_display() -> bool:
    """The window in front, against every display (SHQueryUserNotificationState only knows the main one)."""
    if not portable.WINDOWS:
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:
        window = user32.GetForegroundWindow()
        if not window or window in (user32.GetShellWindow(), user32.GetDesktopWindow()):
            return False
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(window, name, 64)
        if name.value in ("Progman", "WorkerW", "Shell_TrayWnd"):  # the desktop and the taskbar
            return False
        rect = wintypes.RECT()
        if not user32.GetWindowRect(window, ctypes.byref(rect)):
            return False
        displays: list[Rect] = []
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
        )

        def collect(_monitor, _dc, area, _data) -> int:
            r = area.contents
            displays.append((r.left, r.top, r.right, r.bottom))
            return 1

        user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
    except (AttributeError, OSError):
        return False
    return fills_one((rect.left, rect.top, rect.right, rect.bottom), displays)


def _notification_state() -> int | None:
    if not portable.WINDOWS:
        return None
    import ctypes

    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return None
    except (AttributeError, OSError):
        return None
    return state.value


def _microphone_in_use() -> bool:
    """An app is recording when its entry under the microphone's consent store has started but not stopped."""
    if not portable.WINDOWS:
        return False
    import winreg

    root = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

    def recording(key) -> bool:
        with contextlib.suppress(OSError):
            stop, _ = winreg.QueryValueEx(key, "LastUsedTimeStop")
            start, _ = winreg.QueryValueEx(key, "LastUsedTimeStart")
            return stop == 0 and start > 0
        return False

    def walk(path: str, depth: int) -> bool:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return False
        with key:
            if recording(key):
                return True
            if depth == 0:
                return False
            index = 0
            while True:
                try:
                    child = winreg.EnumKey(key, index)
                except OSError:
                    return False
                if walk(f"{path}\\{child}", depth - 1):
                    return True
                index += 1

    return walk(root, 2)


def now() -> dict:
    return from_state(_notification_state(), _microphone_in_use(), _foreground_fills_a_display())
