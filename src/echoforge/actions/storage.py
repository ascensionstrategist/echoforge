"""
Storage (filesystem) actions for Flipper Zero.

All file-system ops on /ext (SD card) and /int (internal) go through here.
Paths use forward slashes, absolute paths starting at /ext or /int.

Chunking:
  Reads can return multi-frame responses (protobuf splits large files); the
  RpcClient already collates them into a list of Main frames, so we just
  concatenate the payload bytes across frames.

  Writes chunk on the host side. Flipper firmware accepts a stream of
  WriteRequest frames each with the same command_id, all has_next=True
  except the final one. Default chunk size: 512 bytes (empirically safe
  under CDC framing + protobuf overhead).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Iterable

from echoforge.proto import flipper_pb2, storage_pb2
from echoforge.transport import RpcClient


class FileType(enum.IntEnum):
    FILE = storage_pb2.File.FileType.FILE
    DIR = storage_pb2.File.FileType.DIR


@dataclass(frozen=True)
class FileEntry:
    name: str
    type: FileType
    size: int
    md5: str = ""

    @property
    def is_dir(self) -> bool:
        return self.type == FileType.DIR


@dataclass(frozen=True)
class StorageInfo:
    path: str
    total_bytes: int
    free_bytes: int

    @property
    def used_bytes(self) -> int:
        return self.total_bytes - self.free_bytes

    @property
    def percent_used(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return 100.0 * self.used_bytes / self.total_bytes


class Storage:
    """Wraps the Flipper storage RPC surface."""

    # Write payload per frame. Flipper's RPC buffer and the CDC endpoint
    # both tolerate more, but 512 is a safe sweet spot that keeps total
    # frame size well under 1 KB including protobuf overhead.
    WRITE_CHUNK_SIZE = 512

    def __init__(self, client: RpcClient):
        self._client = client

    # -- read ops ----------------------------------------------------------

    def list(self, path: str, *, include_md5: bool = False) -> list[FileEntry]:
        """List entries in a directory."""
        main = flipper_pb2.Main()
        main.storage_list_request.path = path
        main.storage_list_request.include_md5 = include_md5
        frames = self._client.request(main, timeout_s=10.0)

        out: list[FileEntry] = []
        for f in frames:
            if not f.HasField("storage_list_response"):
                continue
            for entry in f.storage_list_response.file:
                out.append(
                    FileEntry(
                        name=entry.name,
                        type=FileType(entry.type),
                        size=entry.size,
                        md5=entry.md5sum,
                    )
                )
        return out

    def stat(self, path: str) -> FileEntry:
        """Return metadata for a single file or directory."""
        main = flipper_pb2.Main()
        main.storage_stat_request.path = path
        frames = self._client.request(main, timeout_s=5.0)
        for f in frames:
            if f.HasField("storage_stat_response"):
                file = f.storage_stat_response.file
                # Stat responses carry the path-stripped name only; pass full path.
                return FileEntry(
                    name=path.rsplit("/", 1)[-1],
                    type=FileType(file.type),
                    size=file.size,
                    md5=file.md5sum,
                )
        raise RuntimeError("stat returned no StatResponse frames")

    def exists(self, path: str) -> bool:
        from echoforge.transport import RpcError

        try:
            self.stat(path)
            return True
        except RpcError as exc:
            if exc.status_name == "ERROR_STORAGE_NOT_EXIST":
                return False
            raise

    def read(self, path: str, *, timeout_s: float = 30.0) -> bytes:
        """Read a file's full contents. Multi-frame responses are concatenated."""
        main = flipper_pb2.Main()
        main.storage_read_request.path = path
        frames = self._client.request(main, timeout_s=timeout_s)

        buf = bytearray()
        for f in frames:
            if f.HasField("storage_read_response"):
                buf.extend(f.storage_read_response.file.data)
        return bytes(buf)

    def md5sum(self, path: str) -> str:
        main = flipper_pb2.Main()
        main.storage_md5sum_request.path = path
        frames = self._client.request(main, timeout_s=30.0)
        for f in frames:
            if f.HasField("storage_md5sum_response"):
                return f.storage_md5sum_response.md5sum
        raise RuntimeError("md5sum returned no response frames")

    def info(self, path: str = "/ext") -> StorageInfo:
        """Get free/total bytes for a mount point (/ext or /int)."""
        main = flipper_pb2.Main()
        main.storage_info_request.path = path
        frames = self._client.request(main, timeout_s=5.0)
        for f in frames:
            if f.HasField("storage_info_response"):
                r = f.storage_info_response
                return StorageInfo(path=path, total_bytes=r.total_space, free_bytes=r.free_space)
        raise RuntimeError("info returned no InfoResponse frames")

    # -- write ops ---------------------------------------------------------

    def mkdir(self, path: str) -> None:
        main = flipper_pb2.Main()
        main.storage_mkdir_request.path = path
        self._client.request(main, timeout_s=5.0)

    def delete(self, path: str, *, recursive: bool = False) -> None:
        main = flipper_pb2.Main()
        main.storage_delete_request.path = path
        main.storage_delete_request.recursive = recursive
        self._client.request(main, timeout_s=15.0)

    def rename(self, old_path: str, new_path: str) -> None:
        """Move or rename — firmware handles both via the same message."""
        main = flipper_pb2.Main()
        main.storage_rename_request.old_path = old_path
        main.storage_rename_request.new_path = new_path
        self._client.request(main, timeout_s=10.0)

    move = rename  # alias for clarity at the action layer

    def write(self, path: str, content: bytes | str, *, timeout_s: float = 60.0) -> None:
        """
        Write a file. Chunks automatically if payload > WRITE_CHUNK_SIZE.

        The firmware requires a multi-frame write to share one command_id
        with has_next=True on all but the final frame. Our RpcClient doesn't
        currently expose a "multi-send, single-correlate" API, so for
        chunked writes we bypass it and drive the codec directly while
        registering a pending slot by hand.
        """
        if isinstance(content, str):
            content = content.encode("utf-8")

        if len(content) <= self.WRITE_CHUNK_SIZE:
            main = flipper_pb2.Main()
            main.storage_write_request.path = path
            main.storage_write_request.file.data = content
            self._client.request(main, timeout_s=timeout_s)
            return

        # Chunked write — drive the client's low-level interface.
        self._client.stream_request(
            frames=list(self._build_write_frames(path, content)),
            timeout_s=timeout_s,
        )

    def _build_write_frames(
        self, path: str, content: bytes
    ) -> Iterable[flipper_pb2.Main]:
        """Yield one Main per chunk, with has_next set correctly."""
        total = len(content)
        offset = 0
        while offset < total:
            end = min(offset + self.WRITE_CHUNK_SIZE, total)
            chunk = content[offset:end]
            main = flipper_pb2.Main()
            main.storage_write_request.path = path
            main.storage_write_request.file.data = chunk
            main.has_next = end < total  # False on the last frame
            yield main
            offset = end

    # -- compound ----------------------------------------------------------

    def copy(self, source: str, destination: str) -> int:
        """
        Host-driven copy: read source fully, write destination. Returns
        bytes copied. Not atomic — if write fails midway, dest is partial.
        """
        data = self.read(source)
        self.write(destination, data)
        return len(data)
