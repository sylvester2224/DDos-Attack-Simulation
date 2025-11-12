import streamlit as st
import time
import queue
import threading

# ---
# 1. Server Simulation
# ---

def server_worker(server_instance):
    """
    This runs in a separate thread, simulating the server's *actual* work.
    It pulls from the queue, processes the item, and logs the *result*.
    """
    while True:
        try:
            # Get an item from the queue (this blocks until an item is available)
            work_item = server_instance.request_queue.get()
            
            # Simulate the work (e.g., 0.1 seconds)
            time.sleep(0.1) 
            
            # --- Process the work item ---
            if work_item["type"] == "LOGIN":
                user = work_item["data"].get("user")
                pwd = work_item["data"].get("pwd")
                
                with server_instance.lock: # Access credentials safely
                    if server_instance.credentials.get(user) == pwd:
                        add_server_log(f"✅ [Auth] Login Succeeded for user: {user}")
                    else:
                        add_server_log(f"❌ [Auth] Login FAILED for user: {user} (Bad Pwd)")
                        
            elif work_item["type"] == "FAKE":
                payload = work_item["data"].get('payload_file', 'unknown')
                ip = work_item["data"].get('source_ip', 'unknown')
                add_server_log(f"🔥 [Flood] Processed fake request from {ip} ({payload})")

            # Mark the task as done
            server_instance.request_queue.task_done()
            
            # Update the UI after processing
            with server_instance.lock:
                st.session_state.current_queue_size = server_instance.request_queue.qsize()
                
        except Exception as e:
            # Handle potential errors
            pass

class SimulatedServer:
    def __init__(self, queue_size=10):
        self.request_queue = queue.Queue(maxsize=queue_size)
        self.credentials = {"user": "password123"}
        self.lock = threading.Lock()
        self.max_size = queue_size # Store max size for reporting

    def process_request(self, request_type, data):
        """
        Simulates *accepting* a request into the queue.
        If the queue is full, it returns False (request dropped).
        This function is thread-safe and *fast*.
        It NO LONGER checks credentials; the worker does.
        """
        with self.lock:
            # Update queue size for UI
            st.session_state.current_queue_size = self.request_queue.qsize()
            
            if self.request_queue.full():
                return False  # Request dropped
            
            # Just create the work item and queue it
            item_to_queue = {"type": request_type, "data": data}
            
            # Add to queue for the *worker* to process
            self.request_queue.put(item_to_queue)
            st.session_state.current_queue_size = self.request_queue.qsize() # Update UI
            return True # Request was *queued*

# ---
# 2. Streamlit App UI
# ---

st.set_page_config(layout="wide")
st.title("🛡️ Interactive DoS Attack Simulation")
st.warning("This is an educational simulation. No real network traffic is generated.")

# ---
# 3. Session State Initialization
# ---
default_queue_size = st.session_state.get('setting_queue_size', 20)

if 'server' not in st.session_state:
    st.session_state.server = SimulatedServer(queue_size=default_queue_size)
    # Start the server's background worker thread
    worker_t = threading.Thread(target=server_worker, args=(st.session_state.server,))
    worker_t.daemon = True
    worker_t.start()
    
if 'attack_running' not in st.session_state:
    st.session_state.attack_running = False
if 'log' not in st.session_state:
    st.session_state.log = [] # This is the main "User/Attacker" log
if 'server_processing_log' not in st.session_state:
    st.session_state.server_processing_log = [] # This is the new "Server Worker" log
if 'current_queue_size' not in st.session_state:
    st.session_state.current_queue_size = 0
if 'setting_queue_size' not in st.session_state:
    st.session_state.setting_queue_size = default_queue_size
if 'setting_num_attackers' not in st.session_state:
    st.session_state.setting_num_attackers = 1
if 'setting_attack_speed' not in st.session_state:
    st.session_state.setting_attack_speed = 20 # Reqs/sec

# Function to add logs
def add_log(emoji, message):
    st.session_state.log.insert(0, f"{emoji} {message}")
    if len(st.session_state.log) > 20: # Keep log short
        st.session_state.log.pop()

# NEW function for the server worker log
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
    It continuously floods the server with fake requests.
    """
    while st.session_state.attack_running:
        attack_speed = st.session_state.get('setting_attack_speed', 20)
        sleep_time = 1.0 / attack_speed
        
        # Create a more descriptive fake payload
        fake_data = {
            "payload_file": "data_flood.bin",
            "source_ip": f"10.{attacker_id}.{attacker_id % 255}.{attacker_id % 100}"
        }
        
        success = st.session_state.server.process_request("FAKE", fake_data)
        
        if not success:
            if attacker_id == 0: 
                add_log("🔴", "[Attacker] Server queue full. Request dropped.")
        else:
            if attacker_id == 0:
                add_log("🔥", "[Attacker] Sent fake request.")
        
        time.sleep(sleep_time) # Attacker speed

# ---
# 5. App Layout
# ---

# --- Sidebar ---
with st.sidebar:
    st.header("Simulation Settings")
    st.number_input("Server Queue Size", min_value=10, max_value=1000, key='setting_queue_size')
    st.slider("Number of Attackers", min_value=1, max_value=50, key='setting_num_attackers')
    st.slider("Attack Speed (reqs/sec per attacker)", min_value=1, max_value=100, key='setting_attack_speed')

    if st.button("Apply Settings & Restart Server"):
        st.session_state.attack_running = False # Stop any old attack
        time.sleep(0.5) # Give threads time to stop
        
        st.session_state.server = SimulatedServer(queue_size=st.session_state.setting_queue_size)
        
        worker_t = threading.Thread(target=server_worker, args=(st.session_state.server,))
        worker_t.daemon = True
        worker_t.start()
        
        st.session_state.current_queue_size = 0
        st.session_state.log = []
        st.session_state.server_processing_log = [] # Clear both logs
        add_log("🔄", f"Server Restarted. Queue Size: {st.session_state.setting_queue_size}")
        add_log("🚀", "Server worker thread started.")
        st.rerun()

# --- Main Columns ---
col1, col2, col3 = st.columns(3)

# --- COLUMN 1: Attacker ---
with col1:
    st.header("💻 Attacker")
    st.info("The attacker tries to flood the server's request queue with fake traffic.")
    
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
    st.info("The user tries to send a single, valid login request.")
    
    with st.form("login_form"):
        st.text_input("Username", value="user", key="user")
        st.text_input("Password", value="password123", key="pwd", type="password")
        submitted = st.form_submit_button("Attempt Login")

    if submitted:
        add_log("⏳", "[User] Attempting to log in...")
        data = {"user": st.session_state.user, "pwd": st.session_state.pwd}
        
        success = st.session_state.server.process_request("LOGIN", data)
        
        if success:
            add_log("✅", "[User] Login request *queued*!")
        else:
            add_log("❌", "[User] LOGIN FAILED. Server is busy (queue is full).")

# --- COLUMN 3: Server State ---
with col3:
    st.header("📦 Server")
    st.info("A background worker processes ~10 reqs/sec. If the queue fills, requests are dropped.")
    
    current_q = st.session_state.get('current_queue_size', 0)
    max_q = st.session_state.server.max_size
    st.metric("Server Queue Load", f"{current_q} / {max_q}")
    
    progress = 0.0
    if max_q > 0:
        progress = float(current_q) / max_q
    st.progress(progress)

    # --- NEW: Server Processing Log ---
    st.subheader("Server Processing Log (Worker Thread)")
    processing_log_placeholder = st.empty()
    processing_log_text = "\n".join(st.session_state.server_processing_log)
    processing_log_placeholder.code(processing_log_text, language="text")

    # --- Renamed: User/Attacker Log ---
    st.subheader("User & Attacker Request Log")
    log_placeholder = st.empty()
    log_text = "\n".join(st.session_state.log)
    log_placeholder.code(log_text, language="text")

# Simple auto-refresh to see logs and stats update
if st.session_state.attack_running:
    time.sleep(0.5) # Refresh every 0.5s
    st.rerun()
