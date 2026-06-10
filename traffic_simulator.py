"""
traffic_simulator.py — PyCache Concurrent Traffic Generator

Spawns N worker threads that hammer the PyCache TCP server with a
realistic mix of SET / GET / DEL / TTL commands, measuring throughput
and latency percentiles.

Usage
-----
  python traffic_simulator.py [--host HOST] [--port PORT]
                              [--clients N] [--requests R]
                              [--json]

Outputs a summary table (or JSON with --json for dashboard consumption).
"""

import socket
import threading
import time
import random
import string
import argparse
import json
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

# ── Config defaults ────────────────────────────────────────────────────────────
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
DEFAULT_CLIENTS = 50
DEFAULT_REQUESTS = 200   # per client
KEY_POOL_SIZE = 500      # re-use keys to generate realistic hit rates
VALUE_LEN = 32           # random value length
RECV_TIMEOUT = 5.0       # seconds per read


# ── Result container ───────────────────────────────────────────────────────────

@dataclass
class WorkerResult:
    worker_id: int
    sets: int = 0
    gets: int = 0
    deletes: int = 0
    hits: int = 0
    misses: int = 0
    errors: int = 0
    latencies: list = field(default_factory=list)  # seconds per op

    def total_ops(self):
        return self.sets + self.gets + self.deletes

    def error_rate(self):
        total = self.total_ops() + self.errors
        return (self.errors / total * 100) if total else 0.0


# ── Low-level client ───────────────────────────────────────────────────────────

class SimpleClient:
    """
    Minimal synchronous PyCache client for the simulator.
    Sends one command at a time over a persistent TCP connection.
    """

    def __init__(self, host: str, port: int):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((host, port))
        self._sock.settimeout(RECV_TIMEOUT)
        self._buf = b""

    def _send(self, cmd: str) -> str:
        self._sock.sendall((cmd + "\n").encode())
        return self._readline()

    def _readline(self) -> str:
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Server closed connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("utf-8", errors="replace").strip()

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> str:
        if ttl is not None:
            return self._send(f"SET {key} {value} EX {ttl}")
        return self._send(f"SET {key} {value}")

    def get(self, key: str) -> str:
        return self._send(f"GET {key}")

    def delete(self, key: str) -> str:
        return self._send(f"DEL {key}")

    def ttl(self, key: str) -> str:
        return self._send(f"TTL {key}")

    def ping(self) -> str:
        return self._send("PING")

    def close(self):
        try:
            self._send("QUIT")
            self._sock.close()
        except Exception:
            pass


# ── Key / value generators ─────────────────────────────────────────────────────

_key_pool = [f"bench:key:{i:05d}" for i in range(KEY_POOL_SIZE)]

def _rand_value(n: int = VALUE_LEN) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))

def _rand_key() -> str:
    return random.choice(_key_pool)

def _rand_ttl() -> Optional[int]:
    """30 % of SETs carry a TTL between 10–120 s."""
    if random.random() < 0.3:
        return random.randint(10, 120)
    return None


# ── Worker ─────────────────────────────────────────────────────────────────────

def worker(worker_id: int, host: str, port: int, n_requests: int,
           progress_lock: threading.Lock, progress: dict) -> WorkerResult:
    result = WorkerResult(worker_id=worker_id)
    client = None

    try:
        client = SimpleClient(host, port)

        for _ in range(n_requests):
            key = _rand_key()
            op = random.choices(["set", "get", "del", "ttl"], weights=[35, 50, 10, 5])[0]
            t0 = time.perf_counter()

            try:
                if op == "set":
                    resp = client.set(key, _rand_value(), ttl=_rand_ttl())
                    result.sets += 1
                    if resp.startswith("+OK"):
                        pass  # expected
                    else:
                        result.errors += 1

                elif op == "get":
                    resp = client.get(key)
                    result.gets += 1
                    if resp.startswith("$nil"):
                        result.misses += 1
                    elif resp.startswith("$"):
                        result.hits += 1
                    elif resp.startswith("-ERR"):
                        result.errors += 1
                    else:
                        result.misses += 1

                elif op == "del":
                    resp = client.delete(key)
                    result.deletes += 1
                    if resp.startswith("-ERR"):
                        result.errors += 1

                elif op == "ttl":
                    client.ttl(key)  # result not tracked separately

                elapsed = time.perf_counter() - t0
                result.latencies.append(elapsed)

            except Exception as exc:
                result.errors += 1

        # Update shared progress counter
        with progress_lock:
            progress["completed"] += n_requests

    except Exception as exc:
        result.errors += n_requests
    finally:
        if client:
            client.close()

    return result


# ── Stats helpers ──────────────────────────────────────────────────────────────

def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


def aggregate(results: list[WorkerResult]) -> dict:
    all_lat = []
    total_sets = total_gets = total_dels = total_hits = total_misses = total_errors = 0
    for r in results:
        all_lat.extend(r.latencies)
        total_sets += r.sets
        total_gets += r.gets
        total_dels += r.deletes
        total_hits += r.hits
        total_misses += r.misses
        total_errors += r.errors

    total_ops = total_sets + total_gets + total_dels
    return {
        "total_ops": total_ops,
        "total_sets": total_sets,
        "total_gets": total_gets,
        "total_deletes": total_dels,
        "total_hits": total_hits,
        "total_misses": total_misses,
        "total_errors": total_errors,
        "hit_rate_pct": round(total_hits / total_gets * 100, 2) if total_gets else 0.0,
        "error_rate_pct": round(total_errors / (total_ops + total_errors) * 100, 2) if total_ops else 0.0,
        "latency_min_ms": round(min(all_lat) * 1000, 3) if all_lat else 0,
        "latency_avg_ms": round(sum(all_lat) / len(all_lat) * 1000, 3) if all_lat else 0,
        "latency_p50_ms": round(percentile(all_lat, 50) * 1000, 3),
        "latency_p95_ms": round(percentile(all_lat, 95) * 1000, 3),
        "latency_p99_ms": round(percentile(all_lat, 99) * 1000, 3),
        "latency_max_ms": round(max(all_lat) * 1000, 3) if all_lat else 0,
    }


# ── Main runner ────────────────────────────────────────────────────────────────

def run_simulation(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    n_clients: int = DEFAULT_CLIENTS,
    n_requests: int = DEFAULT_REQUESTS,
    emit_json: bool = False,
    progress_callback=None,
) -> dict:
    """
    Run the full simulation.

    progress_callback: optional callable(completed_ops, total_ops)
    Returns aggregated stats dict.
    """
    total_ops = n_clients * n_requests
    progress_lock = threading.Lock()
    progress = {"completed": 0}

    # Optional live-progress printing
    _stop_progress = threading.Event()

    def _print_progress():
        while not _stop_progress.is_set():
            with progress_lock:
                done = progress["completed"]
            pct = done / total_ops * 100 if total_ops else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            sys.stdout.write(f"\r  [{bar}] {pct:5.1f}%  {done}/{total_ops} ops")
            sys.stdout.flush()
            if progress_callback:
                progress_callback(done, total_ops)
            if done >= total_ops:
                break
            time.sleep(0.15)

    if not emit_json:
        progress_thread = threading.Thread(target=_print_progress, daemon=True)
        progress_thread.start()

    t_start = time.perf_counter()
    results: list[WorkerResult] = []

    with ThreadPoolExecutor(max_workers=n_clients, thread_name_prefix="sim") as pool:
        futures = {
            pool.submit(
                worker,
                wid, host, port, n_requests,
                progress_lock, progress
            ): wid
            for wid in range(n_clients)
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                pass  # already counted inside worker

    elapsed = time.perf_counter() - t_start
    _stop_progress.set()

    stats = aggregate(results)
    stats["elapsed_sec"] = round(elapsed, 3)
    stats["throughput_ops_sec"] = round(stats["total_ops"] / elapsed, 1) if elapsed else 0
    stats["n_clients"] = n_clients
    stats["n_requests_per_client"] = n_requests

    if not emit_json:
        sys.stdout.write("\r" + " " * 70 + "\r")  # clear progress bar
        _print_table(stats)

    return stats


def _print_table(stats: dict):
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║            PyCache Traffic Simulator — Results            ║")
    print("╠══════════════════════════════════════════════════════════╣")

    rows = [
        ("Clients", stats["n_clients"]),
        ("Requests / client", stats["n_requests_per_client"]),
        ("Total ops", f"{stats['total_ops']:,}"),
        ("Elapsed", f"{stats['elapsed_sec']} s"),
        ("Throughput", f"{stats['throughput_ops_sec']:,.0f} ops/s"),
        ("", ""),
        ("SETs", f"{stats['total_sets']:,}"),
        ("GETs", f"{stats['total_gets']:,}"),
        ("DELs", f"{stats['total_deletes']:,}"),
        ("Cache hits", f"{stats['total_hits']:,}"),
        ("Cache misses", f"{stats['total_misses']:,}"),
        ("Hit rate", f"{stats['hit_rate_pct']} %"),
        ("Errors", f"{stats['total_errors']:,}"),
        ("Error rate", f"{stats['error_rate_pct']} %"),
        ("", ""),
        ("Latency min", f"{stats['latency_min_ms']} ms"),
        ("Latency avg", f"{stats['latency_avg_ms']} ms"),
        ("Latency p50", f"{stats['latency_p50_ms']} ms"),
        ("Latency p95", f"{stats['latency_p95_ms']} ms"),
        ("Latency p99", f"{stats['latency_p99_ms']} ms"),
        ("Latency max", f"{stats['latency_max_ms']} ms"),
    ]

    for label, value in rows:
        if label == "":
            print("║" + "─" * 58 + "║")
        else:
            print(f"║  {label:<28}{str(value):>26}  ║")

    print("╚══════════════════════════════════════════════════════════╝\n")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PyCache traffic simulator")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--clients", type=int, default=DEFAULT_CLIENTS)
    parser.add_argument("--requests", type=int, default=DEFAULT_REQUESTS)
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    print(f"\n  Launching {args.clients} concurrent clients "
          f"× {args.requests} requests → {args.host}:{args.port}")
    print("  " + "─" * 56)

    result = run_simulation(
        host=args.host,
        port=args.port,
        n_clients=args.clients,
        n_requests=args.requests,
        emit_json=args.json,
    )

    if args.json:
        print(json.dumps(result, indent=2))
