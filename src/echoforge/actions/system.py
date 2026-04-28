"""
System-level actions for Flipper Zero.

Wraps: ping, device_info (KV stream), power_info (KV stream), datetime,
reboot (OS/DFU/UPDATE), factory_reset, audio-visual alert.
"""

from __future__ import annotations

import datetime as _dt
import secrets
from dataclasses import dataclass, field
from typing import Optional

from echoforge.proto import flipper_pb2, system_pb2
from echoforge.transport import RpcClient


@dataclass(frozen=True)
class DateTime:
    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    weekday: int  # 1=Mon…7=Sun per Flipper spec

    def to_py(self) -> _dt.datetime:
        return _dt.datetime(self.year, self.month, self.day, self.hour, self.minute, self.second)

    @classmethod
    def from_py(cls, dt: _dt.datetime) -> "DateTime":
        return cls(
            year=dt.year,
            month=dt.month,
            day=dt.day,
            hour=dt.hour,
            minute=dt.minute,
            second=dt.second,
            weekday=dt.isoweekday(),
        )


@dataclass
class DeviceInfo:
    """Flat key/value dump from Flipper's DeviceInfo RPC. 50+ keys on typical firmware."""
    raw: dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        return self.raw.get(key, default)

    @property
    def hardware_name(self) -> str:
        return self.get("hardware_name")

    @property
    def firmware_version(self) -> str:
        return self.get("firmware_version")

    @property
    def firmware_branch(self) -> str:
        return self.get("firmware_branch")

    @property
    def firmware_commit(self) -> str:
        return self.get("firmware_commit")


@dataclass
class PowerInfo:
    """Battery/charging stats. Key names differ across firmwares (stock, Momentum,
    Xtreme, RogueMaster…) so accessors try a short list of known aliases."""
    raw: dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        return self.raw.get(key, default)

    def _first(self, *keys: str) -> Optional[str]:
        for k in keys:
            v = self.raw.get(k)
            if v is not None and v != "":
                return v
        return None

    @property
    def charge_level(self) -> Optional[int]:
        v = self._first("charge_level", "gauge_soc", "battery_level")
        try:
            return int(v) if v else None
        except ValueError:
            return None

    @property
    def is_charging(self) -> Optional[bool]:
        v = self._first("is_charging", "charge_state", "battery_charging")
        if v is None:
            return None
        s = v.strip().lower()
        if s in {"true", "1", "yes", "charging"}:
            return True
        if s in {"false", "0", "no", "not_charging", "discharging", "idle"}:
            return False
        return None

    @property
    def battery_voltage(self) -> Optional[float]:
        # Momentum commonly exposes gauge_vbat (mV) or voltage (V).
        v = self._first("battery_voltage", "voltage", "gauge_vbat", "vbat")
        if v is None:
            return None
        try:
            f = float(v)
        except ValueError:
            return None
        # Heuristic: > 100 means millivolts; < 10 means volts.
        return f / 1000.0 if f > 100 else f

    @property
    def temperature_c(self) -> Optional[float]:
        v = self._first(
            "battery_temp", "temperature", "battery_temperature", "gauge_temperature"
        )
        try:
            return float(v) if v else None
        except ValueError:
            return None


class System:
    """Wraps the Flipper system RPC surface."""

    def __init__(self, client: RpcClient):
        self._client = client

    # -- liveness ----------------------------------------------------------

    def ping(self, payload: Optional[bytes] = None) -> bytes:
        """Round-trip the firmware and return its echo."""
        data = payload if payload is not None else secrets.token_bytes(16)
        main = flipper_pb2.Main()
        main.system_ping_request.data = data
        frames = self._client.request(main, timeout_s=5.0)
        for f in frames:
            if f.HasField("system_ping_response"):
                return f.system_ping_response.data
        raise RuntimeError("ping returned no PingResponse")

    # -- info streams ------------------------------------------------------

    def device_info(self) -> DeviceInfo:
        """Stream the KV device-info table."""
        main = flipper_pb2.Main()
        main.system_device_info_request.SetInParent()
        frames = self._client.request(main, timeout_s=10.0)
        info = DeviceInfo()
        for f in frames:
            if f.HasField("system_device_info_response"):
                r = f.system_device_info_response
                info.raw[r.key] = r.value
        return info

    def power_info(self) -> PowerInfo:
        """Stream the KV power-info table (battery, charging, voltage, etc.)."""
        main = flipper_pb2.Main()
        main.system_power_info_request.SetInParent()
        frames = self._client.request(main, timeout_s=5.0)
        info = PowerInfo()
        for f in frames:
            if f.HasField("system_power_info_response"):
                r = f.system_power_info_response
                info.raw[r.key] = r.value
        return info

    def protobuf_version(self) -> tuple[int, int]:
        main = flipper_pb2.Main()
        main.system_protobuf_version_request.SetInParent()
        frames = self._client.request(main, timeout_s=5.0)
        for f in frames:
            if f.HasField("system_protobuf_version_response"):
                r = f.system_protobuf_version_response
                return r.major, r.minor
        raise RuntimeError("protobuf_version returned no response")

    # -- clock -------------------------------------------------------------

    def get_datetime(self) -> DateTime:
        main = flipper_pb2.Main()
        main.system_get_datetime_request.SetInParent()
        frames = self._client.request(main, timeout_s=5.0)
        for f in frames:
            if f.HasField("system_get_datetime_response"):
                d = f.system_get_datetime_response.datetime
                return DateTime(
                    year=d.year,
                    month=d.month,
                    day=d.day,
                    hour=d.hour,
                    minute=d.minute,
                    second=d.second,
                    weekday=d.weekday,
                )
        raise RuntimeError("get_datetime returned no response")

    def set_datetime(self, dt: DateTime | _dt.datetime) -> None:
        if isinstance(dt, _dt.datetime):
            dt = DateTime.from_py(dt)
        main = flipper_pb2.Main()
        req = main.system_set_datetime_request.datetime
        req.year = dt.year
        req.month = dt.month
        req.day = dt.day
        req.hour = dt.hour
        req.minute = dt.minute
        req.second = dt.second
        req.weekday = dt.weekday
        self._client.request(main, timeout_s=5.0)

    # -- actions -----------------------------------------------------------

    def play_alert(self) -> None:
        """Attention ping: sound + LED flash. Handy as 'confirm you're talking to the right flipper'."""
        main = flipper_pb2.Main()
        main.system_play_audiovisual_alert_request.SetInParent()
        self._client.request(main, timeout_s=5.0)

    def reboot(self, mode: str = "os") -> None:
        """
        Reboot the device. mode: 'os' (normal), 'dfu' (firmware flash mode),
        'update' (run pending firmware update).

        NOTE: the firmware closes the RPC channel before/during reboot, so
        the request may surface as a timeout. That's expected — caller
        should stop the RpcClient afterwards.
        """
        mode_map = {
            "os": system_pb2.RebootRequest.RebootMode.OS,
            "dfu": system_pb2.RebootRequest.RebootMode.DFU,
            "update": system_pb2.RebootRequest.RebootMode.UPDATE,
        }
        if mode not in mode_map:
            raise ValueError(f"reboot mode must be one of {list(mode_map)}, got {mode!r}")
        main = flipper_pb2.Main()
        main.system_reboot_request.mode = mode_map[mode]
        # Short timeout — firmware tears down before responding.
        try:
            self._client.request(main, timeout_s=1.5)
        except TimeoutError:
            pass

    def factory_reset(self) -> None:
        """Wipe all user data and reboot. DESTRUCTIVE."""
        main = flipper_pb2.Main()
        main.system_factory_reset_request.SetInParent()
        try:
            self._client.request(main, timeout_s=1.5)
        except TimeoutError:
            pass
