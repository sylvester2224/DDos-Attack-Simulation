# dos_sim_onefile_fixed.py
# Single-file Streamlit app that simulates Server / Attacker / Client (safe, local).
# Fixed: removed direct calls to st.experimental_rerun(); uses st_autorefresh if available.
# Run: pip install streamlit streamlit-autorefresh
#      streamlit run dos_sim_onefile_fixed.py

import streamlit as st
import sqlite3, threading, time, datetime, random, os, json
from collections import deque

# --- Config ---
DB_FILE = "sim.db"
MAX_LOGS_SHOWN = 200

# --- DB schema ---
SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    username TEXT,
    password TEXT,
    arrival_ts TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    result TEXT,
    processed_ts TEXT
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT,
    msg TEXT,
    packet TEXT
);
"""

def init_db_file():
    create = not os.path.exists(DB_FILE)
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if create:
        conn.executescript(SCHEMA)
        conn.commit()
    return conn

def new_db_conn():
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def db_log(conn, level, msg, packet=None):
    ts = datetime.datetime.utcnow().isoformat()
    conn.execute("INSERT INTO logs (ts, level, msg, packet) VALUES (?, ?, ?, ?)", (ts, level, msg, packet))
    conn.commit()

def db_insert_request(conn, typ, username=None, password=None):
    ts = datetime.datetime.utcnow().isoformat()
    cur = conn.execute("INSERT INTO requests (type, username, password, arrival_ts) VALUES (?, ?, ?, ?)",
                       (typ, username, password, ts))
    conn.commit()
    return cur.lastrowid

# --- event queue for worker -> main thread notifications ---
if "event_queue" not in st.session_state:
    import queue
    st.session_state.event_queue = queue.Queue()

# --- Stats (main thread updates) ---
if "stats" not in st.session_state:
    st.session_state.stats = {
        "processed_total": 0,
        "processed_auth_success": 0,
        "processed_auth_failed": 0,
        "processed_fake": 0,
        "auth_timeouts": 0,
        "queue_lengths": deque(maxlen=300),
        "timestamps": deque(maxlen=300),
        "recent_logs": deque(maxlen=1000)
    }

# --- Thread control ---
if "server_thread" not in st.session_state:
    st.session_state.server_thread = None
if "attacker_thread" not in st.session_state:
    st.session_state.attacker_thread = None
if "server_stop" not in st.session_state:
    st.session_state.server_stop = threading.Event()
if "attacker_stop" not in st.session_state:
    st.session_state.attacker_stop = threading.Event()

# --- Simulated credentials ---
SERVER_CREDENTIALS = {"admin": "P@ssw0rd"}

# --- Workers (write to DB and push events to event_queue) ---
def attacker_worker(rate_per_sec: float, burst: int, stop_event: threading.Event):
    conn = new_db_conn()
    if rate_per_sec <= 0:
        while not stop_event.is_set():
            time.sleep(0.2)
        conn.close()
        return
    interval = 1.0 / rate_per_sec
    try:
        while not stop_event.is_set():
            created = []
            for _ in range(burst):
                req_id = db_insert_request(conn, "fake")
                created.append(req_id)
            ts = datetime.datetime.utcnow().isoformat()
            for req_id in created:
                packet = f"FAKE_PKT id={req_id} src=10.0.0.{random.randint(2,254)} dst=127.0.0.1 proto=UDP len={random.randint(40,1400)} ts={ts}"
                db_log(conn, "ATTACK", f"Attacker inserted fake req id={req_id}", packet)
                st.session_state.event_queue.put({"type":"log","msg":f"{ts} ATTACK inserted id={req_id}","packet":packet})
            time.sleep(max(0.0005, interval * random.uniform(0.8, 1.2)))
    except Exception as e:
        db_log(conn, "ERROR", f"Attacker worker error: {e}", None)
        st.session_state.event_queue.put({"type":"log","msg":f"Attacker errored: {e}","packet":None})
    finally:
        conn.close()

def server_worker(capacity_per_sec: float, auth_timeout: float, tick: float, stop_event: threading.Event):
    conn = new_db_conn()
    processed_per_tick = capacity_per_sec * tick
    remainder = 0.0
    try:
        while not stop_event.is_set():
            start = time.time()
            to_process = int(processed_per_tick)
            remainder += (processed_per_tick - to_process)
            if remainder >= 1.0:
                to_process += 1
                remainder -= 1.0
            for _ in range(to_process):
                cur = conn.execute("SELECT * FROM requests WHERE status='pending' ORDER BY id LIMIT 1")
                row = cur.fetchone()
                if not row:
                    break
                conn.execute("UPDATE requests SET status='processing' WHERE id=?", (row["id"],))
                conn.commit()
                time.sleep(0.003 + random.random() * 0.01)
                arrival = datetime.datetime.fromisoformat(row["arrival_ts"])
                age = (datetime.datetime.utcnow() - arrival).total_seconds()
                if row["type"] == "auth":
                    if age > auth_timeout:
                        result = "timeout"
                        msg = f"AUTH timeout id={row['id']} user={row['username']}"
                        db_log(conn, "WARN", msg, None)
                        st.session_state.event_queue.put({"type":"log","msg":f"{datetime.datetime.utcnow().isoformat()} {msg}","packet":None})
                        st.session_state.event_queue.put({"type":"result","kind":"auth_timeout"})
                    else:
                        correct = SERVER_CREDENTIALS.get(row["username"])
                        if correct is not None and row["password"] == correct:
                            result = "success"
                            msg = f"AUTH success id={row['id']} user={row['username']}"
                            db_log(conn, "INFO", msg, None)
                            st.session_state.event_queue.put({"type":"log","msg":f"{datetime.datetime.utcnow().isoformat()} {msg}","packet":None})
                            st.session_state.event_queue.put({"type":"result","kind":"auth_success"})
                        else:
                            result = "failed"
                            msg = f"AUTH failed id={row['id']} user={row['username']}"
                            db_log(conn, "INFO", msg, None)
                            st.session_state.event_queue.put({"type":"log","msg":f"{datetime.datetime.utcnow().isoformat()} {msg}","packet":None})
                            st.session_state.event_queue.put({"type":"result","kind":"auth_failed"})
                    conn.execute("UPDATE requests SET status='done', result=?, processed_ts=? WHERE id=?",
                                 (result, datetime.datetime.utcnow().isoformat(), row["id"]))
                    conn.commit()
                else:
                    result = "consumed"
                    msg = f"Fake consumed id={row['id']}"
                    db_log(conn, "DEBUG", msg, None)
                    st.session_state.event_queue.put({"type":"log","msg":f"{datetime.datetime.utcnow().isoformat()} {msg}","packet":None})
                    conn.execute("UPDATE requests SET status='done', result=?, processed_ts=? WHERE id=?",
                                 (result, datetime.datetime.utcnow().isoformat(), row["id"]))
                    conn.commit()
            qlen = conn.execute("SELECT COUNT(*) as c FROM requests WHERE status='pending'").fetchone()["c"]
            st.session_state.event_queue.put({"type":"queue_sample","qlen":qlen,"ts":datetime.datetime.utcnow().strftime("%H:%M:%S")})
            elapsed = time.time() - start
            time.sleep(max(0.0, tick - elapsed))
    except Exception as e:
        db_log(conn, "ERROR", f"Server worker error: {e}", None)
        st.session_state.event_queue.put({"type":"log","msg":f"Server errored: {e}","packet":None})
    finally:
        conn.close()

# --- UI ---
st.set_page_config(page_title="DoS Simulator — Fixed", layout="wide")
st.title("DoS Simulation — Server + Attacker + Client (fixed auto-refresh)")

init_db_file()

with st.sidebar:
    st.header("Simulation Controls")
    server_capacity = st.number_input("Server capacity (requests/sec)", min_value=1.0, max_value=2000.0, value=25.0, step=1.0, format="%.1f")
    auth_timeout = st.number_input("Auth timeout (seconds)", min_value=0.5, max_value=60.0, value=3.0, step=0.5)
    server_tick = st.number_input("Server tick (seconds)", min_value=0.05, max_value=2.0, value=0.25, step=0.05, format="%.2f")

    st.markdown("---")
    attacker_rate = st.number_input("Attacker rate (fake reqs/sec)", min_value=0.0, max_value=5000.0, value=80.0, step=1.0)
    attacker_burst = st.number_input("Attacker burst size (per insertion)", min_value=1, max_value=50, value=1, step=1)

    st.markdown("---")
    if st.session_state.server_thread is None or not st.session_state.server_thread.is_alive():
        if st.button("Start Server"):
            st.session_state.server_stop.clear()
            t = threading.Thread(target=server_worker, args=(server_capacity, auth_timeout, server_tick, st.session_state.server_stop), daemon=True)
            st.session_state.server_thread = t
            t.start()
            st.success("Server thread started.")
    else:
        if st.button("Stop Server"):
            st.session_state.server_stop.set()
            st.success("Server stop requested; thread will stop soon.")

    if st.session_state.attacker_thread is None or not st.session_state.attacker_thread.is_alive():
        if st.button("Start Attacker"):
            st.session_state.attacker_stop.clear()
            t = threading.Thread(target=attacker_worker, args=(attacker_rate, attacker_burst, st.session_state.attacker_stop), daemon=True)
            st.session_state.attacker_thread = t
            t.start()
            st.success("Attacker started.")
    else:
        if st.button("Stop Attacker"):
            st.session_state.attacker_stop.set()
            st.success("Attacker stop requested; thread will stop soon.")

    st.markdown("---")
    st.checkbox("Auto-refresh UI (1s) — uses streamlit-autorefresh if installed", value=True, key="auto_refresh")

# Main metrics
conn_main = new_db_conn()
col1, col2, col3 = st.columns([1.2, 1, 1])
with col1:
    qlen_now = conn_main.execute("SELECT COUNT(*) as c FROM requests WHERE status='pending'").fetchone()["c"]
    st.metric("Queue length (pending)", qlen_now)
    st.write("Server running:", "Yes" if st.session_state.server_thread and st.session_state.server_thread.is_alive() else "No")
    st.write("Attacker running:", "Yes" if st.session_state.attacker_thread and st.session_state.attacker_thread.is_alive() else "No")
with col2:
    st.metric("Processed total", st.session_state.stats["processed_total"])
    st.metric("Processed fake", st.session_state.stats["processed_fake"])
with col3:
    st.metric("Auth successes", st.session_state.stats["processed_auth_success"])
    st.metric("Auth failures", st.session_state.stats["processed_auth_failed"])
    st.metric("Auth timeouts", st.session_state.stats["auth_timeouts"])

st.markdown("---")
st.subheader("Client: Submit login")
with st.form("login_form", clear_on_submit=True):
    username = st.text_input("Username", value="admin")
    password = st.text_input("Password", type="password", value="P@ssw0rd")
    submitted = st.form_submit_button("Submit login request")
    if submitted:
        conn = new_db_conn()
        req_id = db_insert_request(conn, "auth", username=username, password=password)
        db_log(conn, "INFO", f"Client submitted auth id={req_id} user={username}", None)
        st.session_state.event_queue.put({"type":"log","msg":f"{datetime.datetime.utcnow().isoformat()} Client submitted auth id={req_id} user={username}","packet":None})
        st.success(f"Auth request queued (id={req_id}).")

def drain_events(max_items=1000):
    count = 0
    while not st.session_state.event_queue.empty() and count < max_items:
        try:
            evt = st.session_state.event_queue.get_nowait()
        except Exception:
            break
        count += 1
        etype = evt.get("type")
        if etype == "log":
            msg = evt.get("msg", "")
            packet = evt.get("packet")
            st.session_state.stats["recent_logs"].appendleft({"ts": datetime.datetime.utcnow().isoformat(), "level":"EVENT", "msg": msg, "packet": packet})
        elif etype == "result":
            kind = evt.get("kind")
            if kind == "auth_success":
                st.session_state.stats["processed_auth_success"] += 1
                st.session_state.stats["processed_total"] += 1
            elif kind == "auth_failed":
                st.session_state.stats["processed_auth_failed"] += 1
                st.session_state.stats["processed_total"] += 1
            elif kind == "auth_timeout":
                st.session_state.stats["auth_timeouts"] += 1
                st.session_state.stats["processed_auth_failed"] += 1
                st.session_state.stats["processed_total"] += 1
            elif kind == "fake_processed":
                st.session_state.stats["processed_fake"] += 1
                st.session_state.stats["processed_total"] += 1
        elif etype == "queue_sample":
            q = evt.get("qlen", 0)
            ts = evt.get("ts", datetime.datetime.utcnow().strftime("%H:%M:%S"))
            st.session_state.stats["queue_lengths"].append(q)
            st.session_state.stats["timestamps"].append(ts)
    return count

drain_events()

chart_col, logs_col = st.columns([2,1])
with chart_col:
    st.subheader("Queue length over time")
    if st.session_state.stats["queue_lengths"]:
        import pandas as pd
        df = pd.DataFrame({"time": list(st.session_state.stats["timestamps"]), "queue": list(st.session_state.stats["queue_lengths"])})
        if not df.empty:
            df = df.set_index("time")
            st.line_chart(df)
with logs_col:
    st.subheader("Live logs (most recent)")
    rows = conn_main.execute("SELECT ts, level, msg, packet FROM logs ORDER BY id DESC LIMIT ?", (MAX_LOGS_SHOWN,)).fetchall()
    for r in rows[:50]:
        ts = r["ts"]; level = r["level"]; msg = r["msg"]; packet = r["packet"]
        if packet:
            st.markdown(f"**{ts}** — `{level}` — {msg}  \n```\n{packet}\n```")
        else:
            st.markdown(f"**{ts}** — `{level}` — {msg}")

st.markdown("---")
st.subheader("Recent auth requests (last 50)")
rows = conn_main.execute("SELECT id, username, arrival_ts, status, result, processed_ts FROM requests WHERE type='auth' ORDER BY id DESC LIMIT 50").fetchall()
if rows:
    for r in rows:
        st.write(dict(r))
else:
    st.write("No auth requests yet.")

# Export snapshot
if st.button("Export stats snapshot (JSON)"):
    snapshot = {
        "processed_total": st.session_state.stats["processed_total"],
        "processed_auth_success": st.session_state.stats["processed_auth_success"],
        "processed_auth_failed": st.session_state.stats["processed_auth_failed"],
        "processed_fake": st.session_state.stats["processed_fake"],
        "auth_timeouts": st.session_state.stats["auth_timeouts"],
        "queue_length_now": conn_main.execute("SELECT COUNT(*) as c FROM requests WHERE status='pending'").fetchone()["c"],
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }
    st.download_button("Download snapshot as JSON", data=json.dumps(snapshot, indent=2), file_name="dos_sim_snapshot.json", mime="application/json")

# --- Safe auto-refresh: prefer streamlit-autorefresh; fall back to manual Refresh button ---
auto_refresh_enabled = st.session_state.get("auto_refresh", True)
autorefresh_supported = False
try:
    from streamlit_autorefresh import st_autorefresh
    autorefresh_supported = True
except Exception:
    autorefresh_supported = False

if auto_refresh_enabled and autorefresh_supported:
    # st_autorefresh returns an integer incrementing each refresh.
    # interval milliseconds; this triggers Streamlit-friendly reruns.
    st_autorefresh(interval=1000, key="dos_sim_autorefresh")
elif auto_refresh_enabled and not autorefresh_supported:
    st.warning("streamlit-autorefresh not installed — auto-refresh disabled. Install via: pip install streamlit-autorefresh")
    if st.button("Refresh UI now"):
        # manual refresh via user action (no direct experimental_rerun call)
        pass
else:
    if st.button("Refresh UI now"):
        pass

# done
