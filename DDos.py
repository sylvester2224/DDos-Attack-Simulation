import streamlit as st
import time
import queue
import threading
import random

# ---
# 1. Server Simulation (Worker Pool Model)
# ---

def server_worker_task(server_instance, work_item):
    """
    This function is spawned as a NEW THREAD for *every* accepted request.
    It simulates the 0.1 seconds of work.
    """
    try:
        # 1. Simulate the work
        time.sleep(0.1) 
        
        # 2. Process the work item and log the result
        if work_item["type"] == "LOGIN":
            user = work_item["data"].get("user")
            pwd = work_item["data"].get("pwd")
            
            with server_instance.lock: # Lock to access credentials
                if server_instance.credentials.get(user) == pwd:
                    add_server_log(f"✅ [Auth] Login Succeeded for user: {user}")
                else:
                    add_server_log(f"❌ [Auth] Login FAILED for user: {user} (Bad Pwd)")
                    
        elif work_item["type"] == "FAKE":
            payload = work_item["data"].get('payload_file', 'unknown')
            ip = work_item["data"].get('source_ip', 'unknown')
            add_server_log(f"🔥 [Attack] Processed fake request from {ip} ({payload})")

    except Exception as e:
        # Handle potential errors
        pass
    finally:
        # 3. CRITICAL: Free up the worker slot
        with server_instance.lock:
            server_instance.active_workers -= 1
            st.session_state.active_workers = server_instance.active_workers

class SimulatedServer:
    def __init__(self, max_workers=10):
        self.credentials = {"user": "password123"}
        self.lock = threading.Lock()
        self.max_workers = max_workers
        self.active_workers = 0

    def process_request(self, request_type, data):
        """
        Simulates accepting a request into the worker pool.
        If all workers are busy, it returns False (request dropped).
        """
        with self.lock:
            if self.active_workers < self.max_workers:
                # --- Worker Slot Available ---
                self.active_workers += 1
                st.session_state.active_workers = self.active_workers
                
                # Create the work item
                work_item = {"type": request_type, "data": data}
                
                # Spawn a new thread to do the work.
                # This *is* the worker.
                t = threading.Thread(target=server_worker_task, args=(self, work_item))
                t.daemon = True
                t.start()
                
                return True # Request was *accepted*
            else:
                # --- All Workers Busy ---
                return False # Request was *dropped*

# ---
# 2. Streamlit App UI
# ---

st.set_page_config(layout="wide")
st.title("🛡️ DoS Simulation (Worker Pool Model)")
st.warning("This is an educational simulation. No real network traffic is generated.")

# ---
# 3. Session State Initialization
# ---
default_workers = st.session_state.get('setting_max_workers', 10)

if 'server' not in st.session_state:
    st.session_state.server = SimulatedServer(max_workers=default_workers)
    
if 'attack_running' not in st.session_state:
    st.session_state.attack_running = False
if 'log' not in st.session_state:
    st.session_state.log = [] # User/Attacker request log
if 'server_processing_log' not in st.session_state:
    st.session_state.server_processing_log = [] # Server worker log
if 'active_workers' not in st.session_state:
    st.session_state.active_workers = 0
if 'setting_max_workers' not in st.session_state:
    st.session_state.setting_max_workers = default_workers
if 'setting_num_attackers' not in st.session_state:
    st.session_state.setting_num_attackers = 1
if 'setting_attack_speed' not in st.session_state:
    st.session_state.setting_attack_speed = 10 # Reqs/sec

# Function to add logs
def add_log(emoji, message):
    st.session_state.log.insert(0, f"{emoji} {message}")
    if len(st.session_state.log) > 20: # Keep log short
        st.session_state.log.pop()

def add_server_log(message):
    st.session_state.server_processing_log.insert(0, f"{message}")
    if len(st.session_state.server_processing_log) > 20:
        st.session_state.server_processing_log.pop()

# ---
# 4. Attacker Simulation
# ---
def attacker_thread(attacker_id):
    """
    This function runs in a separate thread.
    It continuously floods the server with fake requests at the set speed.
    """
    while st.session_state.attack_running:
        # Read speed from session state, so it can be changed live
        attack_speed = st.session_state.get('setting_attack_speed', 10)
        if attack_speed <= 0:
             attack_speed = 1 # Avoid division by zero
             
        sleep_time = 1.0 / attack_speed
        
        # Create a more descriptive fake payload
        fake_data = {
            "payload_file": "data_flood.bin",
            "source_ip": f"10.{attacker_id}.{random.randint(1,255)}.{random.randint(1,255)}"
        }
        
        success = st.session_state.server.process_request("FAKE", fake_data)
        
        if not success:
            if attacker_id == 0: 
                add_log("🔴", "[Attacker] Server workers full. Request dropped.")
        else:
            if attacker_id == 0:
                add_log("🔥", "[Attacker] Sent fake request (worker accepted).")
        
        time.sleep(sleep_time) # Attacker speed

# ---
# 5. App Layout
# ---

# --- Sidebar ---
with st.sidebar:
    st.header("Simulation Settings")
    st.number_input(
        "Server Worker Pool Size", 
        min_value=5, max_value=1000, 
        key='setting_max_workers',
        help="How many requests the server can handle *at the same time*."
    )
    st.slider(
        "Number of Attackers", 
        min_value=1, max_value=50, 
        key='setting_num_attackers'
    )
    st.slider(
        "Attack Speed (reqs/sec per attacker)", 
        min_value=1, max_value=100, 
        key='setting_attack_speed'
    )
    st.markdown("---")
    st.subheader("How to Use")
    st.markdown("1. Set 'Worker Pool Size' to **10**.")
    st.markdown("2. Set 'Number of Attackers' to **10**.")
    st.markdown("3. Set 'Attack Speed' to **15**.")
    st.markdown("4. Click 'Apply & Restart'.")
    st.markdown("5. Click 'Start Attack'.")
    st.markdown("6. Watch the 'Server Worker Load' bar fill up.")
    st.markdown("7. Click 'Attempt Login' and see it fail.")


    if st.button("Apply Settings & Restart Server"):
        st.session_state.attack_running = False # Stop any old attack
        time.sleep(0.5) # Give threads time to stop
        
        st.session_state.server = SimulatedServer(
            max_workers=st.session_state.setting_max_workers
        )
        
        st.session_state.active_workers = 0
        st.session_state.log = []
        st.session_state.server_processing_log = [] # Clear both logs
        add_log("🔄", f"Server Restarted. Worker Pool Size: {st.session_state.setting_max_workers}")
        st.rerun()

# --- Main Columns ---
col1, col2, col3 = st.columns(3)

# --- COLUMN 1: Attacker ---
with col1:
    st.header("💻 Attacker")
    st.info("The attacker tries to use all available server 'workers'.")
    
    if st.button("Start Attack", disabled=st.session_state.attack_running):
        st.session_state.attack_running = True
        add_log("⚠️", "Attack Started!")
        num_attackers = st.session_state.get('setting_num_attackers', 1)
        for i in range(num_attackers):
            t = threading.Thread(target=attacker_thread, args=(i,))
            t.daemon = True
            t.start()
        st.rerun()

    if st.button("Stop Attack", disabled=not st.session_state.attack_running):
        st.session_state.attack_running = False
        add_log("✅", "Attack Stopped.")
        st.rerun()

# --- COLUMN 2: Authentic User ---
with col2:
    st.header("👤 Authentic User")
    st.info("The user tries to find one free worker for their login request.")
    
    with st.form("login_form"):
        st.text_input("Username", value="user", key="user")
        st.text_input("Password", value="password123", key="pwd", type="password")
        submitted = st.form_submit_button("Attempt Login")

    if submitted:
        add_log("⏳", "[User] Attempting to log in...")
        data = {"user": st.session_state.user, "pwd": st.session_state.pwd}
        
        success = st.session_state.server.process_request("LOGIN", data)
        
        if success:
            add_log("⏳", "[User] Login request *accepted*. Waiting for server...")
        else:
            add_log("⛔", "[User] LOGIN FAILED. Server workers are all busy, request *dropped*!")

# --- COLUMN 3: Server State ---
with col3:
    st.header("📦 Server")
    st.info("The server processes requests using a fixed number of workers.")
    
    current_w = st.session_state.get('active_workers', 0)
    max_w = st.session_state.server.max_workers
    
    # Calculate Server Capacity
    # Each worker takes 0.1s, so 1 worker = 10 reqs/sec
    capacity = max_w / 0.1
    st.metric("Server Worker Load", f"{current_w} / {max_w}", f"~{int(capacity)} req/sec capacity")
    
    progress = 0.0
    if max_w > 0:
        progress = float(current_w) / max_w
    st.progress(progress)

    # --- Server Processing Log ---
    st.subheader("Server Processing Log (Worker Activity)")
    processing_log_placeholder = st.empty()
    processing_log_text = "\n".join(st.session_state.server_processing_log)
    processing_log_placeholder.code(processing_log_text, language="text")

    # --- User/Attacker Log ---
    st.subheader("User & Attacker Request Log")
    log_placeholder = st.empty()
    log_text = "\n".join(st.session_state.log)
    log_placeholder.code(log_text, language="text")

# Simple auto-refresh to see logs and stats update
# We make this unconditional so the UI always reflects the
# server state (e.g., after a single login attempt).
# Previously, it only refreshed if the attack was running.
time.sleep(0.25) # Refresh every 0.25s
st.rerun()
