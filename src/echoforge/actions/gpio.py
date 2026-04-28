"""
GPIO actions for Flipper Zero.

Flipper exposes 8 user-accessible pins on the top header:
    PA7 (17), PA6 (18), PA4 (19), PB3 (20)   — top row
    PB2 (21), PC3 (22), PC1 (23), PC0 (24)   — bottom row

Each pin can be configured as INPUT (optionally with pull-up / pull-down)
or OUTPUT, then read or written. `otg_mode` toggles the 5 V OTG rail that
powers external boards like the Flipper WiFi dev board.

Safety notes:
  - Driving a pin OUTPUT HIGH while it's shorted to ground can damage the
    MCU. The firmware does not enforce any electrical interlock.
  - Switching OTG on draws extra battery; turn it off when not in use.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Union

from echoforge.proto import flipper_pb2, gpio_pb2


class Pin(enum.IntEnum):
    PC0 = gpio_pb2.PC0
    PC1 = gpio_pb2.PC1
    PC3 = gpio_pb2.PC3
    PB2 = gpio_pb2.PB2
    PB3 = gpio_pb2.PB3
    PA4 = gpio_pb2.PA4
    PA6 = gpio_pb2.PA6
    PA7 = gpio_pb2.PA7


class PinMode(enum.IntEnum):
    OUTPUT = gpio_pb2.OUTPUT
    INPUT = gpio_pb2.INPUT


class InputPull(enum.IntEnum):
    NO = gpio_pb2.NO
    UP = gpio_pb2.UP
    DOWN = gpio_pb2.DOWN


class OtgMode(enum.IntEnum):
    OFF = gpio_pb2.OFF
    ON = gpio_pb2.ON


@dataclass(frozen=True)
class PinSnapshot:
    pin: Pin
    mode: PinMode
    value: int  # 0 or 1


def _resolve_pin(pin: Union[Pin, str, int]) -> Pin:
    if isinstance(pin, Pin):
        return pin
    if isinstance(pin, str):
        try:
            return Pin[pin.upper()]
        except KeyError as exc:
            raise ValueError(f"unknown pin name {pin!r}; expected one of {[p.name for p in Pin]}") from exc
    return Pin(int(pin))


class Gpio:
    """Wraps the Flipper GPIO RPC surface."""

    def __init__(self, client):
        self._client = client

    # -- pin mode ----------------------------------------------------------

    def set_mode(self, pin: Union[Pin, str, int], mode: PinMode) -> None:
        main = flipper_pb2.Main()
        main.gpio_set_pin_mode.pin = _resolve_pin(pin).value
        main.gpio_set_pin_mode.mode = mode.value
        self._client.request(main, timeout_s=3.0)

    def get_mode(self, pin: Union[Pin, str, int]) -> PinMode:
        main = flipper_pb2.Main()
        main.gpio_get_pin_mode.pin = _resolve_pin(pin).value
        frames = self._client.request(main, timeout_s=3.0)
        for f in frames:
            if f.HasField("gpio_get_pin_mode_response"):
                return PinMode(f.gpio_get_pin_mode_response.mode)
        raise RuntimeError("get_pin_mode returned no response")

    def set_input_pull(self, pin: Union[Pin, str, int], pull: InputPull) -> None:
        main = flipper_pb2.Main()
        main.gpio_set_input_pull.pin = _resolve_pin(pin).value
        main.gpio_set_input_pull.pull_mode = pull.value
        self._client.request(main, timeout_s=3.0)

    # -- read / write ------------------------------------------------------

    def read(self, pin: Union[Pin, str, int]) -> int:
        main = flipper_pb2.Main()
        main.gpio_read_pin.pin = _resolve_pin(pin).value
        frames = self._client.request(main, timeout_s=3.0)
        for f in frames:
            if f.HasField("gpio_read_pin_response"):
                return f.gpio_read_pin_response.value
        raise RuntimeError("read_pin returned no response")

    def write(self, pin: Union[Pin, str, int], value: int) -> None:
        main = flipper_pb2.Main()
        main.gpio_write_pin.pin = _resolve_pin(pin).value
        main.gpio_write_pin.value = 1 if value else 0
        self._client.request(main, timeout_s=3.0)

    def snapshot(self, pin: Union[Pin, str, int]) -> PinSnapshot:
        """Read current mode + level in one shot."""
        p = _resolve_pin(pin)
        return PinSnapshot(pin=p, mode=self.get_mode(p), value=self.read(p))

    # -- OTG 5 V rail ------------------------------------------------------

    def get_otg(self) -> OtgMode:
        main = flipper_pb2.Main()
        main.gpio_get_otg_mode.SetInParent()
        frames = self._client.request(main, timeout_s=3.0)
        for f in frames:
            if f.HasField("gpio_get_otg_mode_response"):
                return OtgMode(f.gpio_get_otg_mode_response.mode)
        raise RuntimeError("get_otg_mode returned no response")

    def set_otg(self, mode: OtgMode | bool) -> None:
        """Turn the 5 V OTG rail on/off. Accepts OtgMode or a bool."""
        if isinstance(mode, bool):
            mode = OtgMode.ON if mode else OtgMode.OFF
        main = flipper_pb2.Main()
        main.gpio_set_otg_mode.mode = mode.value
        self._client.request(main, timeout_s=3.0)
