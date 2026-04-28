"""
Flipper Zero action surface.

Each module maps a Flipper subsystem onto the RpcClient. The top-level
`Flipper` facade in echoforge.flipper composes them.
"""

from echoforge.actions.application import Application, AppError, Button
from echoforge.actions.gpio import Gpio, InputPull, OtgMode, Pin, PinMode, PinSnapshot
from echoforge.actions.hardware import (
    BadUsb,
    Buzzer,
    CliAck,
    Emulate,
    Infrared,
    Led,
    LedColor,
    SubGhz,
    Vibro,
)
from echoforge.actions.storage import Storage, FileEntry, FileType, StorageInfo
from echoforge.actions.system import System, DateTime, PowerInfo, DeviceInfo

__all__ = [
    "Application",
    "AppError",
    "BadUsb",
    "Button",
    "Buzzer",
    "CliAck",
    "Emulate",
    "Gpio",
    "Infrared",
    "InputPull",
    "Led",
    "LedColor",
    "OtgMode",
    "Pin",
    "PinMode",
    "PinSnapshot",
    "Storage",
    "FileEntry",
    "FileType",
    "StorageInfo",
    "SubGhz",
    "System",
    "DateTime",
    "PowerInfo",
    "DeviceInfo",
    "Vibro",
]
