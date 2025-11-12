import streamlit as st
import time
import queue
import threading

# ---
# 1. Server Simulation
# ---
# This is not a real server, just a Python class to simulate one.
# It has a "request queue" with a limited size (e.g., 10 slots).
class SimulatedServer:
    def __init__(self, queue_size=10):
        self.request_queue = queue.Queue(maxsize=queue_size)
        self.credentials = {"user": "password123"}
        self.lock = threading.Lock()

    def process_request(self, request_type, data):
        """
        Simulates the server trying to process a request.
        If the queue is full, it returns False (request dropped).
        """
        with self.lock:
            if self.request_queue.full():
                return False  # Request dropped
            
            # If it's a login, check credentials
            if request_type == "LOGIN":
                user = data.get("user")
                pwd = data.get("pwd")
                if self.credentials.get(user) == pwd:
                    result = "Login Successful"
                else:
                    result = "Login Failed"
            else:
                # Fake requests are just processed
                result = "Fake Request Processed"
            
            # Add to queue and simulate work
            self.request_queue.put(result)
            # Simulate work by just removing it after a moment
            # In a real app, this would be a worker thread
            time.sleep(0.1) 
            self.request_queue.get()
            return True

# ---
# 2. Streamlit App UI
# ---

st.set_page_config(layout="wide")
st.title("🛡️ Conceptual DoS Attack Simulation")
st.warning("This is an educational simulation. No real network traffic is generated.")

# Initialize server in session state
if 'server' not in st.session_state:
    st.session_state.server = SimulatedServer(queue_size=20)
if 'attack_running' not in st.session_state:
    st.session_state.attack_running = False
if 'log' not in st.session_state:
    st.session_state.log = []

# Function to add logs
def add_log(emoji, message):
    st.session_state.log.insert(0, f"{emoji} {message}")
    if len(st.session_state.log) > 20: # Keep log short
        st.session_state.log.pop()

# ---
# 3. Attacker Simulation
# ---
def attacker_thread():
    """
    This function runs in a separate thread.
    It continuously floods the server with fake requests.
    """
    while st.session_state.attack_running:
        success = st.session_state.server.process_request("FAKE", {})
        if not success:
            add_log("🔴", "[Attacker] Server queue full. Request dropped.")
        else:
            add_log("🔥", "[Attacker] Sent fake request.")
        time.sleep(0.05) # Attacker is very fast

# ---
# 4. App Layout
# ---
col1, col2, col3 = st.columns(3)

# --- COLUMN 1: Attacker ---
with col1:
    st.header("💻 Attacker")
    st.info("The attacker tries to flood the server's request queue with fake traffic.")
    
    if st.button("Start Attack", disabled=st.session_state.attack_running):
        st.session_state.attack_running = True
        add_log("⚠️", "Attack Started!")
        # Start the attacker in a separate thread
        t = threading.Thread(target=attacker_thread)
        t.daemon = True # Ensure thread closes when app stops
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
            add_log("✅", "[User] Login request sent successfully!")
        else:
            add_log("❌", "[User] LOGIN FAILED. Server is busy (queue is full).")

# --- COLUMN 3: Server State ---
with col3:
    st.header("📦 Server")
    st.info("The server has a limited queue. If it's full, it drops new requests.")
    
    # We can't directly show the queue size from another thread easily
    # So we'll show the log of activities as the "state"
    st.subheader("Server Activity Log")
    log_placeholder = st.empty()
    
    log_text = "\n".join(st.session_state.log)
    log_placeholder.code(log_text, language="text")

# Simple auto-refresh to see logs update
if st.session_state.attack_running:
    time.sleep(1)
    st.rerun()
