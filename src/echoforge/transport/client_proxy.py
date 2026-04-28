"""
Mutable proxy around the active RpcClient.

When the Flipper facade temporarily switches to CLI mode (in Stage 2c-3)
it must close and reopen the serial port, which forces it to recreate the
RpcClient. The action modules (Storage, System, Application, Gpio) hold
references to *this* proxy instead of a direct RpcClient, so swapping
the underlying client is invisible to them.

Only forwards `request` and `stream_request` because those are the only
RpcClient surface that action modules actually call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from echoforge.transport.rpc_client import RpcClient


class ClientProxy:
    """Holds a mutable reference to the active RpcClient."""

    __slots__ = ("_client",)

    def __init__(self, client: "Optional[RpcClient]" = None):
        self._client = client

    def _set(self, client: "RpcClient") -> None:
        self._client = client

    def _clear(self) -> None:
        self._client = None

    def _require(self) -> "RpcClient":
        if self._client is None:
            raise RuntimeError(
                "RPC session is detached (mid-mode-switch). "
                "This should be transparent — file a bug if you see it."
            )
        return self._client

    def request(self, *args, **kwargs):
        return self._require().request(*args, **kwargs)

    def stream_request(self, *args, **kwargs):
        return self._require().stream_request(*args, **kwargs)
