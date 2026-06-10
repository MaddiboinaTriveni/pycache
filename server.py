"""
server.py — PyCache Raw TCP Socket Server

Listens on TCP port 5000 (configurable).  Each accepted connection is
handled in its own thread.  The wire protocol is line-oriented plain text:

  Client → Server:   SET <key> <value> [EX <seconds>]\r\n
                     GET <key>\r\n
                     DEL <key>\r\n
                     TTL <key>\r\n
                     KEYS\r\n
                     DBSIZE\r\n
                     FLUSHALL\r\n
                     PING\r\n
                     QUIT\r\n

  Server → Client:   +OK\r\n          (success)
                     $<value>\r\n     (GET hit)
                     :1\r\n           (integer result)
                     -ERR <msg>\r\n   (error)
                     $nil\r\n         (GET miss)

Run:  python server.py [--host HOST] [--port PORT]
"""

import socket
import threading
import logging
import argparse
import signal
import sys
import os

# Allow imports from parent directory when run directly
sys.path.insert(0, os.path.dirname(__file__))

from engine import PyCache
from aof import AOFLogger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pycache.server")

# ── Shared singletons ──────────────────────────────────────────────────────────
_aof = AOFLogger("pycache.aof")
_cache = PyCache(aof=_aof)


# ── Protocol helpers ──────────────────────────────────────────────────────────

def resp_ok() -> bytes:
    return b"+OK\r\n"

def resp_str(value: str) -> bytes:
    return f"${value}\r\n".encode()

def resp_nil() -> bytes:
    return b"$nil\r\n"

def resp_int(n: int) -> bytes:
    return f":{n}\r\n".encode()

def resp_float(f: float) -> bytes:
    return f":{f:.2f}\r\n".encode()

def resp_err(msg: str) -> bytes:
    return f"-ERR {msg}\r\n".encode()

def resp_array(items: list) -> bytes:
    if not items:
        return b"*0\r\n"
    lines = [f"*{len(items)}\r\n".encode()]
    for item in items:
        lines.append(f"${item}\r\n".encode())
    return b"".join(lines)


# ── Command dispatcher ─────────────────────────────────────────────────────────

def dispatch(tokens: list[str]) -> bytes:
    """
    Parse a tokenised command and execute it against the engine.
    Returns a bytes response.
    """
    if not tokens:
        return resp_err("empty command")

    cmd = tokens[0].upper()

    try:
        # ── PING ──────────────────────────────────────────────────────
        if cmd == "PING":
            return b"+PONG\r\n"

        # ── SET key value [EX seconds] ────────────────────────────────
        elif cmd == "SET":
            if len(tokens) < 3:
                return resp_err("wrong number of arguments for SET")
            key, value = tokens[1], tokens[2]
            ttl = None
            if len(tokens) >= 5 and tokens[3].upper() == "EX":
                try:
                    ttl = int(tokens[4])
                    if ttl <= 0:
                        return resp_err("invalid TTL: must be positive integer")
                except ValueError:
                    return resp_err("invalid TTL value")
            _cache.set(key, value, ttl=ttl)
            return resp_ok()

        # ── GET key ───────────────────────────────────────────────────
        elif cmd == "GET":
            if len(tokens) < 2:
                return resp_err("wrong number of arguments for GET")
            found, value = _cache.get(tokens[1])
            if found:
                return resp_str(str(value))
            return resp_nil()

        # ── DEL key [key ...] ─────────────────────────────────────────
        elif cmd == "DEL":
            if len(tokens) < 2:
                return resp_err("wrong number of arguments for DEL")
            total = sum(_cache.delete(k) for k in tokens[1:])
            return resp_int(total)

        # ── TTL key ───────────────────────────────────────────────────
        elif cmd == "TTL":
            if len(tokens) < 2:
                return resp_err("wrong number of arguments for TTL")
            result = _cache.ttl(tokens[1])
            if result == -2.0:
                return resp_int(-2)
            if result == -1.0:
                return resp_int(-1)
            return resp_float(result)

        # ── EXISTS key ────────────────────────────────────────────────
        elif cmd == "EXISTS":
            if len(tokens) < 2:
                return resp_err("wrong number of arguments for EXISTS")
            return resp_int(1 if _cache.exists(tokens[1]) else 0)

        # ── KEYS ──────────────────────────────────────────────────────
        elif cmd == "KEYS":
            return resp_array(_cache.keys())

        # ── DBSIZE ────────────────────────────────────────────────────
        elif cmd == "DBSIZE":
            return resp_int(_cache.dbsize())

        # ── FLUSHALL ──────────────────────────────────────────────────
        elif cmd == "FLUSHALL":
            _cache.flush()
            return resp_ok()

        # ── STATS ─────────────────────────────────────────────────────
        elif cmd == "STATS":
            stats = _cache.get_stats()
            lines = [f"{k}={v}" for k, v in stats.items()]
            return resp_str(" ".join(lines))

        # ── INFO ──────────────────────────────────────────────────────
        elif cmd == "INFO":
            stats = _cache.get_stats()
            info_lines = "\n".join(f"{k}:{v}" for k, v in stats.items())
            return resp_str(info_lines)

        # ── QUIT ──────────────────────────────────────────────────────
        elif cmd == "QUIT":
            return b"+BYE\r\n"

        else:
            return resp_err(f"unknown command '{cmd}'")

    except Exception as exc:
        logger.exception("Dispatch error: %s", exc)
        return resp_err(f"internal error: {exc}")


# ── Client handler ─────────────────────────────────────────────────────────────

def handle_client(conn: socket.socket, addr: tuple):
    """
    Handle a single client connection in its own thread.
    Reads newline-delimited commands and writes responses.
    """
    _cache.increment_connections()
    logger.debug("New connection from %s:%d", *addr)
    try:
        conn.settimeout(30.0)
        buf = b""
        while True:
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip().decode("utf-8", errors="replace")
                if not line:
                    continue
                tokens = line.split()
                response = dispatch(tokens)
                try:
                    conn.sendall(response)
                except BrokenPipeError:
                    return
                if tokens and tokens[0].upper() == "QUIT":
                    return
    except ConnectionResetError:
        pass
    except Exception as exc:
        logger.debug("Client %s:%d error: %s", *addr, exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        logger.debug("Connection closed: %s:%d", *addr)


# ── Server boot ────────────────────────────────────────────────────────────────

def run_server(host: str = "127.0.0.1", port: int = 5000):
    # Restore state from AOF
    replayed = _aof.replay(_cache)
    logger.info("AOF replay: %d entries processed.", replayed)

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((host, port))
    server_sock.listen(512)
    logger.info("PyCache server listening on %s:%d", host, port)

    # Graceful shutdown on SIGINT / SIGTERM
    def _shutdown(signum, frame):
        logger.info("Shutdown signal received — closing server.")
        server_sock.close()
        _aof.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        try:
            conn, addr = server_sock.accept()
        except OSError:
            break
        t = threading.Thread(
            target=handle_client,
            args=(conn, addr),
            daemon=True,
        )
        t.start()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PyCache TCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
