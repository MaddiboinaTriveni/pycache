"""
engine.py — PyCache Core In-Memory Engine
Thread-safe key/value store with TTL expiry and stats tracking.
"""

import threading
import time
import logging
from typing import Any, Optional, Tuple

logger = logging.getLogger("pycache.engine")


class PyCache:
    """
    High-throughput in-memory key-value store.

    Internals
    ---------
    _store  : dict[str, Any]          — raw values
    _expiry : dict[str, float]        — absolute expiry timestamps (epoch seconds)
    _lock   : threading.Lock          — protects all mutations
    _stats  : dict                    — live counters (hits, misses, sets, dels, conns)
    """

    TTL_SWEEP_INTERVAL = 1.0  # seconds between background sweeps

    def __init__(self, aof=None):
        self._store: dict[str, Any] = {}
        self._expiry: dict[str, float] = {}
        self._lock = threading.Lock()
        self._aof = aof  # optional AOFLogger instance

        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
            "connections": 0,
            "expired_evictions": 0,
        }

        # Start background TTL sweeper daemon
        self._sweeper = threading.Thread(
            target=self._sweep_expired,
            name="ttl-sweeper",
            daemon=True,
        )
        self._sweeper.start()
        logger.info("PyCache engine started — TTL sweeper active.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Store a key. Optional ttl (seconds) sets expiry.
        Returns True on success.
        """
        with self._lock:
            self._store[key] = value
            if ttl is not None:
                self._expiry[key] = time.monotonic() + ttl
            else:
                # Clear any previously set TTL
                self._expiry.pop(key, None)
            self._stats["sets"] += 1

        if self._aof:
            if ttl is not None:
                self._aof.log(f"SET {key} {value} EX {ttl}")
            else:
                self._aof.log(f"SET {key} {value}")
        return True

    def get(self, key: str) -> Tuple[bool, Any]:
        """
        Retrieve a key.
        Returns (True, value) on hit, (False, None) on miss/expired.
        """
        with self._lock:
            if self._is_expired_unsafe(key):
                self._evict_unsafe(key)
                self._stats["misses"] += 1
                return False, None

            if key in self._store:
                self._stats["hits"] += 1
                return True, self._store[key]

            self._stats["misses"] += 1
            return False, None

    def delete(self, key: str) -> int:
        """
        Delete a key. Returns 1 if deleted, 0 if not found.
        """
        with self._lock:
            existed = key in self._store
            if existed:
                del self._store[key]
                self._expiry.pop(key, None)
                self._stats["deletes"] += 1

        if existed and self._aof:
            self._aof.log(f"DEL {key}")

        return 1 if existed else 0

    def exists(self, key: str) -> bool:
        """Return True if key exists and has not expired."""
        found, _ = self.get(key)
        return found

    def ttl(self, key: str) -> Optional[float]:
        """
        Return remaining TTL in seconds, or None if no expiry / not found.
        Returns -1 if key exists with no TTL.
        Returns -2 if key does not exist.
        """
        with self._lock:
            if self._is_expired_unsafe(key):
                self._evict_unsafe(key)
                return -2.0
            if key not in self._store:
                return -2.0
            if key not in self._expiry:
                return -1.0
            remaining = self._expiry[key] - time.monotonic()
            return max(0.0, remaining)

    def keys(self) -> list[str]:
        """Return all non-expired keys."""
        with self._lock:
            now = time.monotonic()
            return [
                k for k in self._store
                if k not in self._expiry or self._expiry[k] > now
            ]

    def all_items(self) -> list[dict]:
        """
        Return a snapshot list of dicts with key, value, ttl_remaining.
        Safe for dashboard iteration.
        """
        with self._lock:
            now = time.monotonic()
            result = []
            for k, v in list(self._store.items()):
                if k in self._expiry and self._expiry[k] <= now:
                    continue
                ttl_remaining = None
                if k in self._expiry:
                    ttl_remaining = round(self._expiry[k] - now, 2)
                result.append({"key": k, "value": v, "ttl": ttl_remaining})
            return result

    def flush(self) -> bool:
        """Delete all keys (FLUSHALL)."""
        with self._lock:
            self._store.clear()
            self._expiry.clear()
        if self._aof:
            self._aof.log("FLUSHALL")
        return True

    def dbsize(self) -> int:
        """Return count of non-expired keys."""
        return len(self.keys())

    def get_stats(self) -> dict:
        """Return a copy of current stats."""
        with self._lock:
            stats = dict(self._stats)
        stats["total_keys"] = self.dbsize()
        stats["memory_bytes"] = self._estimate_memory()
        return stats

    def increment_connections(self):
        with self._lock:
            self._stats["connections"] += 1

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_expired_unsafe(self, key: str) -> bool:
        """Must be called while holding _lock."""
        if key in self._expiry:
            return self._expiry[key] <= time.monotonic()
        return False

    def _evict_unsafe(self, key: str):
        """Remove key without re-acquiring lock."""
        self._store.pop(key, None)
        self._expiry.pop(key, None)
        self._stats["expired_evictions"] += 1

    def _sweep_expired(self):
        """
        Background daemon: periodically scan for expired keys and evict them.
        Uses a snapshot of keys to avoid holding the lock during the full scan.
        """
        while True:
            time.sleep(self.TTL_SWEEP_INTERVAL)
            try:
                now = time.monotonic()
                with self._lock:
                    expired_keys = [
                        k for k, exp in list(self._expiry.items()) if exp <= now
                    ]
                    for k in expired_keys:
                        self._evict_unsafe(k)
                        if self._aof:
                            # Record eviction in AOF as a DEL
                            pass  # AOF write handled outside lock below
                if expired_keys and self._aof:
                    for k in expired_keys:
                        self._aof.log(f"# EXPIRED {k}")
                if expired_keys:
                    logger.debug("Swept %d expired key(s).", len(expired_keys))
            except Exception as exc:
                logger.exception("Error in TTL sweeper: %s", exc)

    def _estimate_memory(self) -> int:
        """
        Rough memory estimate using sys.getsizeof on stored values.
        Not exact — does not account for Python object overhead fully.
        """
        import sys
        with self._lock:
            total = sys.getsizeof(self._store)
            for k, v in self._store.items():
                total += sys.getsizeof(k) + sys.getsizeof(v)
        return total

    def load_from_aof(self, commands: list[str]):
        """
        Replay a list of AOF command strings to restore state on startup.
        Called by the AOFLogger during server boot.
        """
        for line in commands:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if not parts:
                continue
            cmd = parts[0].upper()
            try:
                if cmd == "SET" and len(parts) >= 3:
                    key, value = parts[1], parts[2]
                    ttl = None
                    if len(parts) == 5 and parts[3].upper() == "EX":
                        ttl = int(parts[4])
                    # During replay we do NOT log again to AOF
                    with self._lock:
                        self._store[key] = value
                        if ttl is not None:
                            self._expiry[key] = time.monotonic() + ttl
                        else:
                            self._expiry.pop(key, None)
                elif cmd == "DEL" and len(parts) >= 2:
                    key = parts[1]
                    with self._lock:
                        self._store.pop(key, None)
                        self._expiry.pop(key, None)
                elif cmd == "FLUSHALL":
                    with self._lock:
                        self._store.clear()
                        self._expiry.clear()
            except Exception as exc:
                logger.warning("AOF replay error on line %r: %s", line, exc)
        logger.info("AOF replay complete — %d keys loaded.", len(self._store))
