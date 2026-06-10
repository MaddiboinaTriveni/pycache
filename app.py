"""
app.py — PyCache Interactive Web Dashboard
Built with Streamlit. Connects directly to the in-process engine
(no TCP round-trip needed for the UI) and also can send commands over
the TCP socket for the "terminal" panel.

Run:
  # Start server first (separate terminal):
  python server.py

  # Then launch dashboard:
  streamlit run app.py
"""

import streamlit as st
import socket
import time
import threading
import subprocess
import sys
import os
import json
import random
import string
from datetime import datetime
from pathlib import Path

# ── Page config (must be first Streamlit call) ─────────────────────────────────
st.set_page_config(
    page_title="PyCache Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* ── Google Font ── */
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@300;400;600;700&display=swap');

  /* ── Root theme ── */
  :root {
    --bg:         #0d1117;
    --surface:    #161b22;
    --surface2:   #1c2333;
    --border:     #30363d;
    --emerald:    #10b981;
    --emerald-lo: #064e3b;
    --indigo:     #6366f1;
    --indigo-lo:  #1e1b4b;
    --amber:      #f59e0b;
    --rose:       #f43f5e;
    --text:       #e6edf3;
    --muted:      #8b949e;
    --mono:       'JetBrains Mono', monospace;
    --sans:       'Inter', sans-serif;
  }

  /* ── Global resets ── */
  html, body, [class*="css"]  {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: var(--sans) !important;
  }

  /* ── Sidebar ── */
  [data-testid="stSidebar"] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border) !important;
  }
  [data-testid="stSidebar"] * { color: var(--text) !important; }

  /* ── Metric cards ── */
  [data-testid="stMetric"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 18px 22px !important;
  }
  [data-testid="stMetricLabel"] {
    font-family: var(--mono) !important;
    font-size: 0.72rem !important;
    color: var(--muted) !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
  }
  [data-testid="stMetricValue"] {
    font-family: var(--mono) !important;
    font-size: 2rem !important;
    font-weight: 700 !important;
    color: var(--emerald) !important;
  }
  [data-testid="stMetricDelta"] svg { display: none !important; }

  /* ── Buttons ── */
  .stButton > button {
    font-family: var(--mono) !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.05em !important;
    background: var(--surface2) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    padding: 8px 18px !important;
    transition: all 0.15s ease !important;
  }
  .stButton > button:hover {
    border-color: var(--emerald) !important;
    color: var(--emerald) !important;
    box-shadow: 0 0 8px rgba(16,185,129,0.2) !important;
  }

  /* ── Text input ── */
  .stTextInput > div > div > input {
    font-family: var(--mono) !important;
    font-size: 0.85rem !important;
    background: var(--surface2) !important;
    color: var(--emerald) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    padding: 10px 14px !important;
  }
  .stTextInput > div > div > input:focus {
    border-color: var(--emerald) !important;
    box-shadow: 0 0 0 2px rgba(16,185,129,0.18) !important;
  }

  /* ── Dataframe / table ── */
  [data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    overflow: hidden !important;
  }
  .dvn-scroller { background: var(--surface) !important; }

  /* ── Code / terminal ── */
  .terminal-box {
    background: #0a0e13;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 20px;
    font-family: var(--mono);
    font-size: 0.82rem;
    line-height: 1.7;
    min-height: 280px;
    max-height: 400px;
    overflow-y: auto;
    color: var(--text);
  }
  .terminal-box .cmd  { color: #79c0ff; }
  .terminal-box .ok   { color: var(--emerald); }
  .terminal-box .err  { color: var(--rose); }
  .terminal-box .val  { color: var(--amber); }
  .terminal-box .nil  { color: var(--muted); }
  .terminal-box .ts   { color: #3a424f; font-size: 0.72rem; }
  .terminal-box .prompt { color: var(--indigo); font-weight: 700; }

  /* ── Section headers ── */
  .section-header {
    font-family: var(--mono);
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
    padding-bottom: 8px;
    margin-bottom: 14px;
    margin-top: 4px;
  }

  /* ── Stress test banner ── */
  .stress-active {
    background: linear-gradient(90deg, var(--indigo-lo), var(--emerald-lo));
    border: 1px solid var(--indigo);
    border-radius: 8px;
    padding: 14px 20px;
    font-family: var(--mono);
    font-size: 0.85rem;
    color: var(--text);
    margin-bottom: 10px;
    animation: pulse-border 2s infinite;
  }
  @keyframes pulse-border {
    0%, 100% { border-color: var(--indigo); }
    50%       { border-color: var(--emerald); }
  }

  /* ── AOF badge ── */
  .badge {
    display: inline-block;
    padding: 2px 9px;
    border-radius: 999px;
    font-family: var(--mono);
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.06em;
  }
  .badge-green { background: var(--emerald-lo); color: var(--emerald); border: 1px solid var(--emerald); }
  .badge-blue  { background: var(--indigo-lo);  color: var(--indigo);  border: 1px solid var(--indigo); }

  /* ── Tabs ── */
  [data-testid="stTabs"] button {
    font-family: var(--mono) !important;
    font-size: 0.78rem !important;
    letter-spacing: 0.06em !important;
    color: var(--muted) !important;
  }
  [data-testid="stTabs"] button[aria-selected="true"] {
    color: var(--emerald) !important;
    border-bottom-color: var(--emerald) !important;
  }

  /* ── Progress bar ── */
  .stProgress > div > div {
    background: var(--emerald) !important;
  }

  /* ── Dividers ── */
  hr { border-color: var(--border) !important; }

  /* ── Selectbox ── */
  [data-testid="stSelectbox"] > div > div {
    background: var(--surface2) !important;
    border-color: var(--border) !important;
    font-family: var(--mono) !important;
    font-size: 0.82rem !important;
  }

  /* ── Title bar ── */
  .title-bar {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 12px 0 20px 0;
    border-bottom: 1px solid var(--border);
    margin-bottom: 24px;
  }
  .title-bar .logo {
    font-family: var(--mono);
    font-size: 1.6rem;
    font-weight: 700;
    color: var(--emerald);
    letter-spacing: -0.02em;
  }
  .title-bar .sub {
    font-size: 0.82rem;
    color: var(--muted);
    font-family: var(--mono);
  }
  .title-bar .version {
    margin-left: auto;
    font-family: var(--mono);
    font-size: 0.72rem;
    color: var(--muted);
  }

  /* ── Key table rows ── */
  .key-table {
    width: 100%;
    border-collapse: collapse;
    font-family: var(--mono);
    font-size: 0.8rem;
  }
  .key-table th {
    background: var(--surface2);
    color: var(--muted);
    padding: 8px 12px;
    text-align: left;
    font-size: 0.68rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    border-bottom: 1px solid var(--border);
  }
  .key-table td {
    padding: 7px 12px;
    border-bottom: 1px solid #1a2030;
    color: var(--text);
  }
  .key-table tr:hover td { background: var(--surface2); }
  .key-table .key-col  { color: #79c0ff; }
  .key-table .val-col  { color: var(--amber); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .key-table .ttl-col  { color: var(--emerald); }
  .key-table .perm-col { color: var(--muted); }

  /* ── Latency bars ── */
  .lat-bar {
    display: inline-block;
    height: 10px;
    background: linear-gradient(90deg, var(--indigo), var(--emerald));
    border-radius: 3px;
    vertical-align: middle;
    margin-right: 8px;
  }

  /* Chart placeholder ── */
  .chart-placeholder {
    background: var(--surface);
    border: 1px dashed var(--border);
    border-radius: 8px;
    min-height: 120px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.8rem;
  }
</style>
""", unsafe_allow_html=True)


# ── Server connection helpers ──────────────────────────────────────────────────

SERVER_HOST = os.environ.get("PYCACHE_HOST", "127.0.0.1")
SERVER_PORT = int(os.environ.get("PYCACHE_PORT", "5000"))


def _tcp_command(command: str, timeout: float = 3.0) -> str:
    """Send a single command to the PyCache TCP server, return raw response."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((SERVER_HOST, SERVER_PORT))
        s.sendall((command.strip() + "\n").encode())
        data = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break
            except socket.timeout:
                break
        s.close()
        return data.decode("utf-8", errors="replace").strip()
    except ConnectionRefusedError:
        return "-ERR Connection refused — is server.py running?"
    except Exception as e:
        return f"-ERR {e}"


def _fetch_stats() -> dict:
    """Parse STATS command output into a dict."""
    raw = _tcp_command("STATS")
    stats = {
        "hits": 0, "misses": 0, "sets": 0, "deletes": 0,
        "connections": 0, "total_keys": 0, "memory_bytes": 0,
        "expired_evictions": 0,
    }
    if raw.startswith("$"):
        for pair in raw[1:].split():
            if "=" in pair:
                k, v = pair.split("=", 1)
                try:
                    stats[k] = int(v)
                except ValueError:
                    pass
    return stats


def _fetch_all_keys() -> list[dict]:
    """Fetch all keys+values+ttl from the server via KEYS then individual GETs."""
    keys_raw = _tcp_command("KEYS")
    if not keys_raw.startswith("*"):
        return []
    lines = keys_raw.split("\n")
    # protocol: *N\n$key1\n$key2\n...
    keys = [l.lstrip("$").strip() for l in lines[1:] if l.strip() and not l.startswith("*")]
    result = []
    for k in keys[:200]:  # cap at 200 for UI performance
        val_raw = _tcp_command(f"GET {k}")
        ttl_raw = _tcp_command(f"TTL {k}")
        value = val_raw.lstrip("$").strip() if val_raw.startswith("$") else "—"
        try:
            ttl_v = float(ttl_raw.lstrip(":").strip())
        except Exception:
            ttl_v = -1.0
        result.append({"key": k, "value": value, "ttl": ttl_v})
    return result


def _server_online() -> bool:
    raw = _tcp_command("PING", timeout=1.0)
    return raw == "+PONG"


# ── Session state init ─────────────────────────────────────────────────────────

def _init_state():
    defaults = {
        "terminal_history": [],
        "sim_running": False,
        "sim_results": None,
        "sim_progress": 0.0,
        "last_refresh": 0.0,
        "stats_history": [],   # ring buffer of (ts, stats) for charts
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div style="font-family:'JetBrains Mono',monospace;font-size:1.1rem;font-weight:700;
                color:#10b981;margin-bottom:6px;letter-spacing:-0.02em;">
      ⚡ PyCache
    </div>
    <div style="font-size:0.72rem;color:#8b949e;font-family:'JetBrains Mono',monospace;
                margin-bottom:18px;">
      Distributed In-Memory KV Store
    </div>
    """, unsafe_allow_html=True)

    online = _server_online()
    status_color = "#10b981" if online else "#f43f5e"
    status_label = "● ONLINE" if online else "● OFFLINE"
    st.markdown(f"""
    <div style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;
                color:{status_color};margin-bottom:20px;letter-spacing:0.06em;">
      SERVER {status_label}
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="section-header">Configuration</div>', unsafe_allow_html=True)
    st.text(f"Host: {SERVER_HOST}")
    st.text(f"Port: {SERVER_PORT}")

    st.markdown('<div class="section-header">Quick Actions</div>', unsafe_allow_html=True)
    if st.button("🔄  Refresh Now"):
        st.session_state.last_refresh = 0.0
        st.rerun()

    if st.button("🗑️  FLUSHALL (clear DB)"):
        resp = _tcp_command("FLUSHALL")
        st.success(resp)

    st.markdown('<div class="section-header">Auto-Refresh</div>', unsafe_allow_html=True)
    auto_interval = st.selectbox(
        "Interval", ["Off", "2s", "5s", "10s"], index=2, label_visibility="collapsed"
    )

    st.markdown("---")
    st.markdown("""
    <div style="font-size:0.7rem;color:#3a424f;font-family:'JetBrains Mono',monospace;">
      engine.py · aof.py · server.py<br>
      traffic_simulator.py · app.py<br><br>
      Built with Python 3.11 + Streamlit
    </div>
    """, unsafe_allow_html=True)


# ── Auto-refresh ───────────────────────────────────────────────────────────────
interval_map = {"Off": 0, "2s": 2, "5s": 5, "10s": 10}
interval = interval_map[auto_interval]
if interval and (time.time() - st.session_state.last_refresh) > interval:
    st.session_state.last_refresh = time.time()
    st.rerun()


# ── Title bar ─────────────────────────────────────────────────────────────────
st.markdown("""
<div class="title-bar">
  <div>
    <div class="logo">⚡ PyCache</div>
    <div class="sub">High-Throughput Distributed In-Memory Key-Value Store</div>
  </div>
  <div class="version">v1.0.0 · Python 3.11</div>
</div>
""", unsafe_allow_html=True)


# ── Fetch live data ────────────────────────────────────────────────────────────
stats = _fetch_stats()
hit_rate = round(stats["hits"] / (stats["hits"] + stats["misses"]) * 100, 1) \
           if (stats["hits"] + stats["misses"]) > 0 else 0.0
mem_kb = round(stats["memory_bytes"] / 1024, 1)


# ── SECTION 1: Metrics Cards ──────────────────────────────────────────────────
st.markdown('<div class="section-header">Live Metrics</div>', unsafe_allow_html=True)

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total Keys", f"{stats['total_keys']:,}")
c2.metric("Memory", f"{mem_kb} KB")
c3.metric("Connections", f"{stats['connections']:,}")
c4.metric("Cache Hits", f"{stats['hits']:,}")
c5.metric("Cache Misses", f"{stats['misses']:,}")
c6.metric("Hit Rate", f"{hit_rate} %")

st.markdown("")

col_left, col_right = st.columns([3, 2])


# ── SECTION 2: Data Viewer ────────────────────────────────────────────────────
with col_left:
    st.markdown('<div class="section-header">Active Key Store</div>', unsafe_allow_html=True)

    search_q = st.text_input("", placeholder="🔍  Filter keys…", label_visibility="collapsed")

    all_items = _fetch_all_keys()
    if search_q:
        all_items = [i for i in all_items if search_q.lower() in i["key"].lower()
                     or search_q.lower() in str(i["value"]).lower()]

    if not all_items:
        st.markdown("""
        <div class="chart-placeholder" style="min-height:180px;">
          No keys found — run the stress test or SET some values
        </div>
        """, unsafe_allow_html=True)
    else:
        rows_html = ""
        for item in all_items[:80]:
            k = item["key"]
            v = str(item["value"])
            ttl = item["ttl"]
            if ttl == -2.0:
                ttl_display = '<span class="perm-col">gone</span>'
            elif ttl == -1.0:
                ttl_display = '<span class="perm-col">∞ persist</span>'
            elif ttl is not None and ttl >= 0:
                bar_w = min(int(ttl / 120 * 80), 80)
                color = "#10b981" if ttl > 30 else ("#f59e0b" if ttl > 10 else "#f43f5e")
                ttl_display = (
                    f'<span style="color:{color};">{ttl:.1f}s</span>'
                )
            else:
                ttl_display = '<span class="perm-col">∞</span>'

            rows_html += f"""
            <tr>
              <td class="key-col">{k}</td>
              <td class="val-col" title="{v}">{v[:40]}{'…' if len(v)>40 else ''}</td>
              <td class="ttl-col">{ttl_display}</td>
            </tr>"""

        st.markdown(f"""
        <div style="max-height:400px;overflow-y:auto;border:1px solid #30363d;border-radius:8px;">
          <table class="key-table">
            <thead>
              <tr>
                <th>Key</th>
                <th>Value</th>
                <th>TTL</th>
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;
                    color:#3a424f;margin-top:6px;">
          Showing {min(len(all_items),80)} of {len(all_items)} keys
        </div>
        """, unsafe_allow_html=True)


# ── SECTION 3: Terminal ───────────────────────────────────────────────────────
with col_right:
    st.markdown('<div class="section-header">Interactive Terminal</div>', unsafe_allow_html=True)

    # Render history
    history_html = ""
    for entry in st.session_state.terminal_history[-30:]:
        ts = entry.get("ts", "")
        cmd = entry.get("cmd", "")
        resp = entry.get("resp", "")

        resp_class = "err" if resp.startswith("-ERR") else \
                     "ok"  if resp.startswith("+") else \
                     "nil" if resp == "$nil" else "val"

        history_html += f"""
        <div>
          <span class="ts">{ts}</span>
          <span class="prompt"> pycache&gt; </span>
          <span class="cmd">{cmd}</span>
        </div>
        <div style="margin-left:18px;margin-bottom:6px;">
          <span class="{resp_class}">{resp}</span>
        </div>"""

    if not history_html:
        history_html = '<span style="color:#3a424f;">Type a command above and press ↵</span>'

    st.markdown(f'<div class="terminal-box">{history_html}</div>', unsafe_allow_html=True)

    # Command input
    col_inp, col_btn = st.columns([4, 1])
    with col_inp:
        cmd_input = st.text_input(
            "Terminal Input", placeholder="SET user:101 Admin EX 60",
            key="term_input", label_visibility="collapsed"
        )

    with col_btn:
        send_btn = st.button("RUN", use_container_width=True)

    if send_btn and cmd_input.strip():
        raw_resp = _tcp_command(cmd_input.strip())
        st.session_state.terminal_history.append({
            "ts": datetime.now().strftime("%H:%M:%S"),
            "cmd": cmd_input.strip(),
            "resp": raw_resp,
        })
        st.rerun()

    # Quick command buttons
    st.markdown('<div style="margin-top:10px;"></div>', unsafe_allow_html=True)
    qc1, qc2, qc3, qc4 = st.columns(4)
    if qc1.button("PING"):
        r = _tcp_command("PING")
        st.session_state.terminal_history.append({"ts": datetime.now().strftime("%H:%M:%S"), "cmd": "PING", "resp": r})
        st.rerun()
    if qc2.button("DBSIZE"):
        r = _tcp_command("DBSIZE")
        st.session_state.terminal_history.append({"ts": datetime.now().strftime("%H:%M:%S"), "cmd": "DBSIZE", "resp": r})
        st.rerun()
    if qc3.button("INFO"):
        r = _tcp_command("INFO")
        st.session_state.terminal_history.append({"ts": datetime.now().strftime("%H:%M:%S"), "cmd": "INFO", "resp": r[:120] + ("…" if len(r)>120 else "")})
        st.rerun()
    if qc4.button("KEYS"):
        r = _tcp_command("KEYS")
        preview = r[:80] + ("…" if len(r) > 80 else "")
        st.session_state.terminal_history.append({"ts": datetime.now().strftime("%H:%M:%S"), "cmd": "KEYS", "resp": preview})
        st.rerun()

    # Sample commands reference
    with st.expander("📖 Command Reference", expanded=False):
        st.markdown("""
        <div style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;
                    color:#8b949e;line-height:2;">
          <b style="color:#79c0ff;">SET</b> key value [EX seconds]<br>
          <b style="color:#79c0ff;">GET</b> key<br>
          <b style="color:#79c0ff;">DEL</b> key [key ...]<br>
          <b style="color:#79c0ff;">TTL</b> key<br>
          <b style="color:#79c0ff;">EXISTS</b> key<br>
          <b style="color:#79c0ff;">KEYS</b><br>
          <b style="color:#79c0ff;">DBSIZE</b><br>
          <b style="color:#79c0ff;">FLUSHALL</b><br>
          <b style="color:#79c0ff;">INFO</b><br>
          <b style="color:#79c0ff;">PING</b>
        </div>
        """, unsafe_allow_html=True)


# ── SECTION 4: Stress Test Panel ─────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="section-header">Stress Test Engine</div>', unsafe_allow_html=True)

st_col1, st_col2, st_col3, st_col4 = st.columns([1, 1, 1, 2])

with st_col1:
    sim_clients = st.number_input("Concurrent Clients", min_value=1, max_value=200,
                                   value=50, step=10)
with st_col2:
    sim_requests = st.number_input("Requests / Client", min_value=10, max_value=2000,
                                    value=100, step=50)
with st_col3:
    st.markdown('<div style="margin-top:28px;"></div>', unsafe_allow_html=True)
    launch_btn = st.button(
        "🚀  LAUNCH STRESS TEST",
        use_container_width=True,
        disabled=st.session_state.sim_running or not online
    )


def _run_simulation_thread(n_clients, n_requests):
    """Run in a background thread so Streamlit doesn't block."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from traffic_simulator import run_simulation
        result = run_simulation(
            host=SERVER_HOST,
            port=SERVER_PORT,
            n_clients=n_clients,
            n_requests=n_requests,
            emit_json=True,
        )
        st.session_state.sim_results = result
    except Exception as e:
        st.session_state.sim_results = {"error": str(e)}
    finally:
        st.session_state.sim_running = False


if launch_btn and not st.session_state.sim_running:
    st.session_state.sim_running = True
    st.session_state.sim_results = None
    t = threading.Thread(
        target=_run_simulation_thread,
        args=(sim_clients, sim_requests),
        daemon=True
    )
    t.start()

if st.session_state.sim_running:
    total_ops_est = sim_clients * sim_requests
    st.markdown(f"""
    <div class="stress-active">
      ⚡ <b>Stress test in progress</b> —
      {sim_clients} concurrent clients firing {sim_requests} requests each
      ({total_ops_est:,} total operations) …
    </div>
    """, unsafe_allow_html=True)
    with st.spinner("Hammering the server…"):
        # Poll until done
        deadline = time.time() + 120
        while st.session_state.sim_running and time.time() < deadline:
            time.sleep(0.5)
    st.rerun()

if st.session_state.sim_results:
    r = st.session_state.sim_results

    if "error" in r:
        st.error(f"Simulation failed: {r['error']}")
    else:
        st.markdown('<div style="margin-top:8px;"></div>', unsafe_allow_html=True)
        r1, r2, r3, r4, r5, r6 = st.columns(6)
        r1.metric("Total Ops", f"{r.get('total_ops',0):,}")
        r2.metric("Throughput", f"{r.get('throughput_ops_sec',0):,.0f}/s")
        r3.metric("Hit Rate", f"{r.get('hit_rate_pct',0)} %")
        r4.metric("Errors", f"{r.get('total_errors',0):,}")
        r5.metric("p95 Latency", f"{r.get('latency_p95_ms',0)} ms")
        r6.metric("p99 Latency", f"{r.get('latency_p99_ms',0)} ms")

        # Latency breakdown bar chart (HTML canvas-free, pure HTML)
        lat_data = [
            ("min",  r.get("latency_min_ms", 0)),
            ("avg",  r.get("latency_avg_ms", 0)),
            ("p50",  r.get("latency_p50_ms", 0)),
            ("p95",  r.get("latency_p95_ms", 0)),
            ("p99",  r.get("latency_p99_ms", 0)),
            ("max",  r.get("latency_max_ms", 0)),
        ]
        max_lat = max(v for _, v in lat_data) or 1
        bars_html = ""
        for label, val in lat_data:
            pct = int(val / max_lat * 100)
            bars_html += f"""
            <div style="display:flex;align-items:center;margin-bottom:6px;
                        font-family:'JetBrains Mono',monospace;font-size:0.8rem;">
              <div style="width:38px;color:#8b949e;text-align:right;margin-right:12px;">{label}</div>
              <div style="flex:1;background:#161b22;border-radius:4px;height:14px;overflow:hidden;">
                <div style="width:{pct}%;height:14px;
                            background:linear-gradient(90deg,#6366f1,#10b981);
                            border-radius:4px;transition:width 0.4s;"></div>
              </div>
              <div style="width:70px;text-align:right;color:#f59e0b;margin-left:12px;">
                {val} ms
              </div>
            </div>"""

        op_data = [
            ("SETs",   r.get("total_sets", 0),    "#6366f1"),
            ("GETs",   r.get("total_gets", 0),    "#10b981"),
            ("DELs",   r.get("total_deletes", 0), "#f59e0b"),
            ("Hits",   r.get("total_hits", 0),    "#34d399"),
            ("Misses", r.get("total_misses", 0),  "#8b949e"),
        ]
        max_ops = max(v for _, v, _ in op_data) or 1
        ops_bars = ""
        for label, val, color in op_data:
            pct = int(val / max_ops * 100)
            ops_bars += f"""
            <div style="display:flex;align-items:center;margin-bottom:6px;
                        font-family:'JetBrains Mono',monospace;font-size:0.8rem;">
              <div style="width:52px;color:#8b949e;text-align:right;margin-right:12px;">{label}</div>
              <div style="flex:1;background:#161b22;border-radius:4px;height:14px;overflow:hidden;">
                <div style="width:{pct}%;height:14px;background:{color};
                            border-radius:4px;transition:width 0.4s;opacity:0.85;"></div>
              </div>
              <div style="width:80px;text-align:right;color:{color};margin-left:12px;">
                {val:,}
              </div>
            </div>"""

        bc1, bc2 = st.columns(2)
        with bc1:
            st.markdown(f"""
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;
                        padding:16px 20px;">
              <div style="font-family:'JetBrains Mono',monospace;font-size:0.68rem;
                          letter-spacing:0.1em;text-transform:uppercase;color:#8b949e;
                          margin-bottom:14px;">Latency Distribution</div>
              {bars_html}
            </div>
            """, unsafe_allow_html=True)

        with bc2:
            st.markdown(f"""
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;
                        padding:16px 20px;">
              <div style="font-family:'JetBrains Mono',monospace;font-size:0.68rem;
                          letter-spacing:0.1em;text-transform:uppercase;color:#8b949e;
                          margin-bottom:14px;">Operation Breakdown</div>
              {ops_bars}
            </div>
            """, unsafe_allow_html=True)

        with st.expander("Raw JSON results"):
            st.json(r)


# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(f"""
<div style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;
            color:#3a424f;text-align:center;padding:10px 0;">
  PyCache · Last refreshed {datetime.now().strftime("%H:%M:%S")} ·
  engine.py · aof.py · server.py · traffic_simulator.py · app.py
</div>
""", unsafe_allow_html=True)
