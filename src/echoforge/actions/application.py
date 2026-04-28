"""
Application actions for Flipper Zero.

Launches built-in or installed apps, loads files into running apps, and
simulates button presses for navigation. Wraps the Application protobuf
RPC (PB_App).

Common app names (case-sensitive, firmware-dependent):
    "Sub-GHz", "Infrared", "NFC", "125 kHz RFID", "iButton",
    "Bad USB" (stock) / "Bad KB" (Momentum), "U2F", "GPIO",
    "Music Player", "Archive", "Settings", "Clock"

Button names for press/release:
    "UP", "DOWN", "LEFT", "RIGHT", "OK", "BACK"

Quirk: AppExitRequest returns OK status but the app only exits after the
firmware drains its event queue — you may need a small delay before
launching another app.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Optional

from echoforge.proto import application_pb2, flipper_pb2
from echoforge.transport import RpcClient, RpcError


class Button(str, enum.Enum):
    UP = "UP"
    DOWN = "DOWN"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    OK = "OK"
    BACK = "BACK"


@dataclass(frozen=True)
class AppError:
    code: int
    text: str

    @property
    def is_ok(self) -> bool:
        return self.code == 0 and not self.text


class Application:
    """Wraps the Flipper Application RPC surface."""

    def __init__(self, client: RpcClient):
        self._client = client

    # -- launch / exit -----------------------------------------------------

    def start(self, name: str, args: str = "") -> None:
        """Launch a built-in or installed app by name, optionally with args
        (e.g. a file path to open)."""
        main = flipper_pb2.Main()
        main.app_start_request.name = name
        main.app_start_request.args = args
        self._client.request(main, timeout_s=10.0)

    def exit(self, *, settle_ms: int = 150) -> None:
        """Request the running app to exit. Sleeps briefly to let the
        firmware tear down — call before another `start()` to avoid races."""
        main = flipper_pb2.Main()
        main.app_exit_request.SetInParent()
        try:
            self._client.request(main, timeout_s=5.0)
        except RpcError as exc:
            # ERROR_APP_NOT_RUNNING is fine — nothing to exit.
            if exc.status_name != "ERROR_APP_NOT_RUNNING":
                raise
        if settle_ms > 0:
            time.sleep(settle_ms / 1000.0)

    def load_file(self, path: str) -> None:
        """Tell the currently-running app to load a file (e.g. open a
        specific .sub in an already-started Sub-GHz app)."""
        main = flipper_pb2.Main()
        main.app_load_file_request.path = path
        self._client.request(main, timeout_s=10.0)

    def open(self, name: str, file_path: Optional[str] = None, *, exit_current: bool = True) -> None:
        """Ergonomic wrapper: exit current app, start `name`, optionally load
        a file. Matches the common 'open garage.sub in Sub-GHz' pattern."""
        if exit_current:
            self.exit()
        self.start(name)
        if file_path:
            # Give the app a moment to initialize before loading.
            time.sleep(0.15)
            self.load_file(file_path)

    # -- state / errors ----------------------------------------------------

    def is_locked(self) -> bool:
        """Returns True if the desktop/app is locked (PIN, lockscreen)."""
        main = flipper_pb2.Main()
        main.app_lock_status_request.SetInParent()
        frames = self._client.request(main, timeout_s=5.0)
        for f in frames:
            if f.HasField("app_lock_status_response"):
                return f.app_lock_status_response.locked
        raise RuntimeError("lock_status returned no response")

    def last_error(self) -> AppError:
        """Get the most recent error from the running app. Returns (0, '')
        when there is none."""
        main = flipper_pb2.Main()
        main.app_get_error_request.SetInParent()
        frames = self._client.request(main, timeout_s=5.0)
        for f in frames:
            if f.HasField("app_get_error_response"):
                r = f.app_get_error_response
                return AppError(code=r.code, text=r.text)
        raise RuntimeError("get_error returned no response")

    # -- button simulation -------------------------------------------------

    def press(self, button: Button | str, *, index: int = 0) -> None:
        """Simulate pressing a button (held until release() or press_release)."""
        main = flipper_pb2.Main()
        main.app_button_press_request.args = str(button.value if isinstance(button, Button) else button)
        main.app_button_press_request.index = index
        self._client.request(main, timeout_s=5.0)

    def release(self) -> None:
        """Release the currently held button."""
        main = flipper_pb2.Main()
        main.app_button_release_request.SetInParent()
        self._client.request(main, timeout_s=5.0)

    def press_release(self, button: Button | str, *, index: int = 0) -> None:
        """Atomic press+release — typical for navigation taps."""
        main = flipper_pb2.Main()
        main.app_button_press_release_request.args = str(button.value if isinstance(button, Button) else button)
        main.app_button_press_release_request.index = index
        self._client.request(main, timeout_s=5.0)

    # -- data exchange -----------------------------------------------------

    def data_exchange(self, data: bytes) -> None:
        """Send arbitrary bytes to a running app that supports DataExchange
        (e.g. custom .fap apps). No response is guaranteed — read via
        RpcClient.on_unsolicited if the app responds asynchronously."""
        main = flipper_pb2.Main()
        main.app_data_exchange_request.data = data
        self._client.request(main, timeout_s=5.0)
