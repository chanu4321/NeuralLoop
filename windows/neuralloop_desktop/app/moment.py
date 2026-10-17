"""What's going on at this PC right now, for Silly mode's big Pip (NudgeDelivery's NudgeMoment): it only shows
when the screen isn't locked, nothing full-screen is in front (a game, a video, a presentation), and no app is
using the microphone (a call or a meeting is likely). Otherwise the nudge stays a notification.

Windows answers the first two through SHQueryUserNotificationState and the third through the privacy settings'
own record of which apps are using the microphone right now. Elsewhere nothing is known, which reads as calm.
"""

import contextlib

from neuralloop_books import portable

# SHQueryUserNotificationState answers.
QUNS_NOT_PRESENT = 1  # the screen is locked, the screen saver is on, or fast user switching is under way
QUNS_BUSY = 2  # a full-screen app is in front
QUNS_RUNNING_D3D_FULL_SCREEN = 3  # a full-screen game or video
QUNS_PRESENTATION_MODE = 4  # presentation settings are on


def from_state(state: int | None, microphone: bool) -> dict:
    return {
        "screenLocked": state == QUNS_NOT_PRESENT,
        "fullScreenInFront": state in (QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE),
        "microphoneInUse": microphone,
    }


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
    return from_state(_notification_state(), _microphone_in_use())
