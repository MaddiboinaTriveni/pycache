"""
aof.py — PyCache Append-Only File (AOF) Persistence Layer

Every write mutation (SET, DEL, FLUSHALL) is immediately appended to a
local log file.  On server start the log is replayed sequentially to
rebuild in-memory state — giving durable persistence across restarts.

Design decisions
----------------
* Each log entry is a plain-text line (human-readable, easy to debug).
* Writes are fsync'd immediately (O_SYNC semantics via flush+fsync).
* A compaction helper rewrites the AOF from a live engine snapshot,
  removing stale SET/DEL pairs to keep the file lean.
* Thread-safe: a dedicated threading.Lock guards the file handle.
"""

import os
import threading
import logging
import time
from pathlib import Path

logger = logging.getLogger("pycache.aof")

DEFAULT_AOF_PATH = "pycache.aof"


class AOFLogger:
    """
    Append-Only File logger for PyCache.

    Usage
    -----
    aof = AOFLogger("pycache.aof")
    engine = PyCache(aof=aof)
    aof.replay(engine)          # call before accepting connections
    """

    def __init__(self, path: str = DEFAULT_AOF_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._fh = None
        self._entry_count = 0
        self._open()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(self, command: str):
        """
        Append a command string to the AOF file and flush to disk.
        Thread-safe.
        """
        timestamp = time.time()
        line = f"{timestamp:.6f} {command}\n"
        with self._lock:
            try:
                self._fh.write(line)
                self._fh.flush()
                os.fsync(self._fh.fileno())
                self._entry_count += 1
            except Exception as exc:
                logger.error("AOF write failed: %s", exc)
                self._reopen()

    def replay(self, engine) -> int:
        """
        Read the AOF file from top to bottom and replay all commands
        into the provided engine instance.

        Returns the number of commands replayed.
        """
        if not self.path.exists():
            logger.info("No AOF file found at %s — starting fresh.", self.path)
            return 0

        commands = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    # Strip leading timestamp token
                    parts = raw_line.split(" ", 1)
                    if len(parts) == 2:
                        try:
                            float(parts[0])  # validate timestamp token
                            commands.append(parts[1])
                        except ValueError:
                            # No timestamp prefix — older format
                            commands.append(raw_line)
                    else:
                        commands.append(raw_line)
        except IOError as exc:
            logger.error("Cannot read AOF file: %s", exc)
            return 0

        logger.info("Replaying %d AOF entries from %s …", len(commands), self.path)
        engine.load_from_aof(commands)
        return len(commands)

    def compact(self, engine):
        """
        Rewrite the AOF from the current engine snapshot.

        This removes stale SET/DEL pairs and reduces file size.
        The engine's all_items() snapshot is used; keys with a
        remaining TTL of ≤ 0 are omitted.
        """
        items = engine.all_items()
        tmp_path = self.path.with_suffix(".aof.tmp")

        try:
            with open(tmp_path, "w", encoding="utf-8") as tmp:
                tmp.write(f"# PyCache AOF — compacted at {time.time():.0f}\n")
                for item in items:
                    k = item["key"]
                    v = item["value"]
                    ttl = item.get("ttl")
                    ts = time.time()
                    if ttl is not None and ttl <= 0:
                        continue
                    if ttl is not None:
                        line = f"{ts:.6f} SET {k} {v} EX {int(ttl)}\n"
                    else:
                        line = f"{ts:.6f} SET {k} {v}\n"
                    tmp.write(line)

            # Atomic rename
            with self._lock:
                self._fh.close()
                tmp_path.replace(self.path)
                self._open_unsafe()
                self._entry_count = len(items)

            logger.info("AOF compacted — %d entries written.", len(items))
        except Exception as exc:
            logger.error("AOF compaction failed: %s", exc)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def entry_count(self) -> int:
        return self._entry_count

    def file_size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    def close(self):
        with self._lock:
            if self._fh and not self._fh.closed:
                self._fh.flush()
                self._fh.close()
                logger.info("AOF file closed.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open(self):
        with self._lock:
            self._open_unsafe()

    def _open_unsafe(self):
        """Open (or re-open) the AOF file in append mode. Lock must be held."""
        try:
            self._fh = open(self.path, "a", encoding="utf-8", buffering=1)
            logger.info("AOF file opened: %s", self.path.resolve())
        except IOError as exc:
            logger.critical("Cannot open AOF file %s: %s", self.path, exc)
            raise

    def _reopen(self):
        """Attempt to recover a broken file handle."""
        logger.warning("Attempting AOF file handle recovery …")
        try:
            if self._fh and not self._fh.closed:
                self._fh.close()
        except Exception:
            pass
        self._open_unsafe()