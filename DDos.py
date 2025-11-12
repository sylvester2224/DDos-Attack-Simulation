# dos_simulation_threadsafe.py
import streamlit as st
import threading, time, queue, random, datetime
from collections import deque

st.set_page_config(page_title="DoS Attack Simulator (Safe)", layout="wide")

# ---------- Simulation request/event objects ----------
class SimRequest:
    def __init__(self, req_type, user_id=None, username=None, password=None):
        self.req_type = req_type  # 'auth' or 'fake'
        self.user_id = user_id
        self.username = username
        self.password = password
        self.arrival = datetime.datetime.now()

# An event is a simple dict pushed by worker threads into event_queue,
# e.g. {"type":"log","msg":"..."} or {"type":"result","kind":"auth_success"} etc.

# ---------- Session state initialization ----------
if "sim_running" not in st.session_state:
    st.session_state.sim_running = False

# Thread-safe queues stored in session_state (it's OK to store queue objects)
if "req_queue" not in st.session_state:
    st.session_state.req_queue = queue.Queue()
if "event_queue" not in st.session_state:
    st.session_state.event_queue = queue.Queue()

# Stats stored in session_state — only the main thread updates these
if "stats" not in st.session_state:
    st.session_state.stats = {
        "processed_total": 0,
        "processed_auth_success": 0,
        "processed_auth_failed": 0,
        "processed_fake": 0,
        "auth_timeouts": 0,
        "queue_lengths": deque(maxlen=200),
        "timestamps": deque(maxlen=200),
        "recent_logs": deque(maxlen=500),
    }

if "threads" not in st.session_state:
    st.session_state.threads = []
if "stop_event" not in st.session_state:
    st.session_state.stop_event = threading.Event()
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = False

# ---------- Controls ----------
st.title("DoS Attack Simulator — **Safe & Thread-Safe**")
st.markdown(
    """
This is an **offline** simulation. All background threads push events into a queue;
the main Streamlit thread drains that queue and updates UI state — avoiding thread-safety issues.
"""
)

with st.sidebar:
    st.header("Simulation controls")
    auth_rate = st.slider("Legitimate users: login attempts / sec (total)", 0, 50, 5)
    num_legit_users = st.slider("Number of legitimate users (simulated)", 1, 10, 3)
    attacker_rate = st.slider("Attacker flood: requests / sec", 0, 500, 80)
    server_capacity = st.slider("Server processing capacity (requests / sec)", 1, 200, 25)
    auth_timeout_s = st.slider("Auth attempt timeout (seconds)", 1, 10, 3)
    simulation_tick = st.slider("Simulation tick interval (ms)", 100, 2000, 300)
    st.markdown("---")
    if not st.session_state.sim_running:
        if st.button("Start simulation"):
            st.session_state.stop_event.clear()
            st.session_state.sim_running = True
    else:
        if st.button("Stop simulation"):
            st.session_state.stop_event.set()
            st.session_state.sim_running = False

    if st.button("Reset stats & queue"):
        # stop first
        st.session_state.stop_event.set()
        st.session_state.sim_running = False
        # clear request queue and event queue
        while not st.session_state.req_queue.empty():
            try: st.session_state.req_queue.get_nowait()
            except: break
        while not st.session_state.event_queue.empty():
            try: st.session_state.event_queue.get_nowait()
            except: break
        # reset stats
        st.session_state.stats = {
            "processed_total": 0,
            "processed_auth_success": 0,
            "processed_auth_failed": 0,
            "processed_fake": 0,
            "auth_timeouts": 0,
            "queue_lengths": deque(maxlen=200),
            "timestamps": deque(maxlen=200),
            "recent_logs": deque(maxlen=500),
        }
        st.success("Reset complete")

    st.markdown("---")
    st.checkbox("Auto-refresh UI (every 1s)", value=st.session_state.auto_refresh, key="auto_refresh")

# ---------- Server credentials (simulated) ----------
SERVER_CREDENTIALS = {"admin": "P@ssw0rd"}  # correct credentials for simulation

# ---------- Worker functions (they NEVER touch st.session_state directly) ----------
def legit_user_worker(stop_event, rate_per_sec, num_users, tick_ms, req_q, evt_q):
    if rate_per_sec <= 0:
        while not stop_event.is_set():
            time.sleep(0.2)
        return
    per_user_rate = rate_per_sec / max(1, num_users)
    next_fire = [time.time()] * num_users
    while not stop_event.is_set():
        now = time.time()
        for uid in range(num_users):
            if now >= next_fire[uid]:
                username = "admin" if random.random() < 0.9 else f"user{uid}"
                password = SERVER_CREDENTIALS.get("admin") if random.random() < 0.8 else "wrongpass"
                req = SimRequest("auth", user_id=uid, username=username, password=password)
                req_q.put(req)
                # push a log event
                evt_q.put({"type":"log","msg":f"{datetime.datetime.now().strftime('%H:%M:%S')} AUTH attempt from user{uid} (username={username})"})
                interval = 1.0 / per_user_rate if per_user_rate > 0 else 1.0
                next_fire[uid] = now + random.uniform(interval * 0.7, interval * 1.3)
        time.sleep(max(0.01, tick_ms / 1000.0))

def attacker_worker(stop_event, rate_per_sec, tick_ms, req_q, evt_q):
    if rate_per_sec <= 0:
        while not stop_event.is_set():
            time.sleep(0.2)
        return
    interval = 1.0 / rate_per_sec
    next_fire = time.time()
    while not stop_event.is_set():
        now = time.time()
        if now >= next_fire:
            bursts = random.choice([1,1,1,2,3])
            for _ in range(bursts):
                req_q.put(SimRequest("fake"))
            evt_q.put({"type":"log","msg":f"{datetime.datetime.now().strftime('%H:%M:%S')} ATTACKER sent {bursts} fake req(s)"})
            next_fire = now + random.uniform(interval * 0.8, interval * 1.2)
        time.sleep(max(0.001, tick_ms / 1000.0))

def server_worker(stop_event, capacity_per_sec, auth_timeout, req_q, evt_q):
    tick = 0.25  # seconds
    processed_per_tick_float = capacity_per_sec * tick
    remainder = 0.0
    while not stop_event.is_set():
        start = time.time()
        to_process = int(processed_per_tick_float)
        remainder += (processed_per_tick_float - to_process)
        if remainder >= 1.0:
            to_process += 1
            remainder -= 1.0
        for _ in range(to_process):
            if stop_event.is_set():
                break
            try:
                req = req_q.get(timeout=0.0)
            except Exception:
                break
            # process request *inside worker* and emit events (not update st.session_state)
            age = (datetime.datetime.now() - req.arrival).total_seconds()
            if req.req_type == "auth":
                if age > auth_timeout:
                    evt_q.put({"type":"result","kind":"auth_timeout","user_id":req.user_id})
                    evt_q.put({"type":"log","msg":f"{datetime.datetime.now().strftime('%H:%M:%S')} AUTH timeout for user{req.user_id}"})
                else:
                    correct = SERVER_CREDENTIALS.get(req.username)
                    if correct is not None and req.password == correct:
                        evt_q.put({"type":"result","kind":"auth_success","user_id":req.user_id})
                        evt_q.put({"type":"log","msg":f"{datetime.datetime.now().strftime('%H:%M:%S')} AUTH success user{req.user_id}"})
                    else:
                        evt_q.put({"type":"result","kind":"auth_failed","user_id":req.user_id})
                        evt_q.put({"type":"log","msg":f"{datetime.datetime.now().strftime('%H:%M:%S')} AUTH failed user{req.user_id}"})
            else:
                evt_q.put({"type":"result","kind":"fake_processed"})
        # push queue-length sample event for plotting
        evt_q.put({"type":"queue_sample","qlen":req_q.qsize(),"ts":datetime.datetime.now().strftime("%H:%M:%S")})
        elapsed = time.time() - start
        time.sleep(max(0.0, tick - elapsed))

# ---------- Thread lifecycle helpers ----------
def ensure_threads_running():
    if st.session_state.sim_running and (not st.session_state.threads or not any(t.is_alive() for t in st.session_state.threads)):
        st.session_state.stop_event.clear()
        st.session_state.threads = []
        t_legit = threading.Thread(target=legit_user_worker, args=(
            st.session_state.stop_event, auth_rate, num_legit_users, simulation_tick,
            st.session_state.req_queue, st.session_state.event_queue
        ), daemon=True)
        t_attack = threading.Thread(target=attacker_worker, args=(
            st.session_state.stop_event, attacker_rate, simulation_tick,
            st.session_state.req_queue, st.session_state.event_queue
        ), daemon=True)
        t_server = threading.Thread(target=server_worker, args=(
            st.session_state.stop_event, server_capacity, auth_timeout_s,
            st.session_state.req_queue, st.session_state.event_queue
        ), daemon=True)
        st.session_state.threads = [t_legit, t_attack, t_server]
        for t in st.session_state.threads:
            t.start()

def stop_threads():
    st.session_state.stop_event.set()

# Start/stop handling
if st.session_state.sim_running:
    ensure_threads_running()
else:
    stop_threads()

# ---------- MAIN THREAD: drain event queue and update session_state.stats safely ----------
def drain_events_and_apply(max_items=1000):
    applied = 0
    while not st.session_state.event_queue.empty() and applied < max_items:
        try:
            evt = st.session_state.event_queue.get_nowait()
        except Exception:
            break
        applied += 1
        t = evt.get("type")
        if t == "log":
            st.session_state.stats["recent_logs"].append(evt.get("msg", ""))
        elif t == "result":
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
        elif t == "queue_sample":
            st.session_state.stats["queue_lengths"].append(evt.get("qlen", 0))
            st.session_state.stats["timestamps"].append(evt.get("ts", datetime.datetime.now().strftime("%H:%M:%S")))
    # optionally return number processed
    return applied

# Drain events now (safe single-threaded)
drain_events_and_apply()

# ---------- UI display ----------
col1, col2, col3 = st.columns([1.2, 1, 1])
with col1:
    st.subheader("Server queue")
    qlen = st.session_state.req_queue.qsize()
    st.metric("Current queue length", qlen)
    st.write("Processing capacity (req/sec):", server_capacity)
    st.write("Legit rate (req/sec):", auth_rate)
    st.write("Attacker rate (req/sec):", attacker_rate)

with col2:
    st.subheader("Auth results")
    st.metric("Auth successes", st.session_state.stats["processed_auth_success"])
    st.metric("Auth failures", st.session_state.stats["processed_auth_failed"])
    st.metric("Auth timeouts", st.session_state.stats["auth_timeouts"])

with col3:
    st.subheader("Traffic & processing")
    st.metric("Processed total", st.session_state.stats["processed_total"])
    st.metric("Processed fake", st.session_state.stats["processed_fake"])

st.markdown("---")
chart_col, log_col = st.columns([2, 1])
with chart_col:
    st.subheader("Queue length over time")
    if st.session_state.stats["queue_lengths"]:
        import pandas as pd
        df = pd.DataFrame({
            "time": list(st.session_state.stats["timestamps"]),
            "queue": list(st.session_state.stats["queue_lengths"])
        })
        if not df.empty:
            df = df.set_index("time")
            st.line_chart(df)

with log_col:
    st.subheader("Recent events")
    logs = list(st.session_state.stats["recent_logs"])[-20:][::-1]
    for l in logs:
        st.write(l)

st.markdown("---")
st.subheader("Simulation details / what this models")
st.markdown(
    """
    - This is a behavioural simulator: **no network traffic** is generated.
    - Background threads only push events into queues; the main thread applies state updates.
    - This avoids thread-safety problems with Streamlit.
    """
)

st.markdown("----")
st.caption("Safe simulation for learning and testing. No real networking or attack code is present.")

# allow exporting stats snapshot
if st.button("Export stats snapshot (JSON)"):
    import json
    snapshot = {
        "processed_total": st.session_state.stats["processed_total"],
        "processed_auth_success": st.session_state.stats["processed_auth_success"],
        "processed_auth_failed": st.session_state.stats["processed_auth_failed"],
        "processed_fake": st.session_state.stats["processed_fake"],
        "auth_timeouts": st.session_state.stats["auth_timeouts"],
        "queue_length_now": st.session_state.req_queue.qsize(),
        "timestamp": datetime.datetime.now().isoformat(),
    }
    st.download_button("Download snapshot as JSON", data=json.dumps(snapshot, indent=2), file_name="dos_sim_snapshot.json", mime="application/json")

# Manual refresh button (safe)
refresh_col1, refresh_col2 = st.columns([1, 1])
with refresh_col1:
    if st.button("Refresh UI now"):
        # Drain events so latest info is present immediately
        drain_events_and_apply()
        # No experimental_rerun here; clicking causes a re-run naturally
with refresh_col2:
    if st.session_state.auto_refresh:
        # If auto-refresh enabled, re-run after 1 second by using st.experimental_sleep loop:
        # Note: rather than calling experimental_rerun from background, we let Streamlit finish and then re-run.
        drain_events_and_apply()
        time.sleep(1)
        # No direct call to experimental_rerun(); Streamlit will re-run periodically when widgets change or user interacts.
        # Some deployments may still require manual refresh; if you want a deterministic auto-reload we can add a JS component.

# Done. Important: background threads NEVER modify st.session_state directly.
