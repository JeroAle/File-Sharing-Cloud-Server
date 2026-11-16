%%writefile server.py
import socket
import threading
import os
import hashlib
import json
import time

# Configure Server
HOST = '0.0.0.0'  # Listen on all interfaces
PORT = 8080
BUFFER_SIZE = 4096
STORAGE_DIR = './server_storage'
ACCOUNTS_FILE = './accounts.json'

# Create storage directory if it doesn't exist
os.makedirs(STORAGE_DIR, exist_ok=True)

# Dummy Account Database (Pre-hashed passwords with SHA-256)
def initialize_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        # Password for both is 'password123' and 'adminpass'
        accounts = {
            "user1": hashlib.sha256("password123".encode()).hexdigest(),
            "admin": hashlib.sha256("adminpass".encode()).hexdigest()
        }
        with open(ACCOUNTS_FILE, 'w') as f:
            json.dump(accounts, f, indent=4)

initialize_accounts()

def verify_login(username, hashed_password):
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, 'r') as f:
            accounts = json.load(f)
        return accounts.get(username) == hashed_password
    return False

def calculate_sha256(filepath):
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def handle_client(conn, addr):
    print(f"[NEW CONNECTION] Connected to client at {addr}")
    authenticated = False
    username = ""

    try:
        while True:
            # Receive control headers
            header = conn.recv(BUFFER_SIZE).decode()
            if not header:
                break
            
            try:
                request = json.loads(header)
            except json.JSONDecodeError:
                conn.sendall(json.dumps({"status": "error", "message": "Invalid command format."}).encode())
                continue

            action = request.get("action")

            # Authentication check
            if not authenticated and action != "login":
                conn.sendall(json.dumps({"status": "error", "message": "Authentication required."}).encode())
                continue

            if action == "login":
                username = request.get("username")
                pass_hash = request.get("password")
                if verify_login(username, pass_hash):
                    authenticated = True
                    print(f"[AUTH] User '{username}' authenticated successfully from {addr}.")
                    conn.sendall(json.dumps({"status": "success", "message": "Login successful."}).encode())
                else:
                    conn.sendall(json.dumps({"status": "error", "message": "Invalid credentials."}).encode())

            elif action == "dir":
                # List storage files
                files = []
                for root, dirs, filenames in os.walk(STORAGE_DIR):
                    for name in filenames:
                        rel_path = os.path.relpath(os.path.join(root, name), STORAGE_DIR)
                        files.append(rel_path)
                conn.sendall(json.dumps({"status": "success", "files": files}).encode())

            elif action == "subfolder":
                op = request.get("operation")
                sub_path = os.path.normpath(request.get("path"))
                target_path = os.path.join(STORAGE_DIR, sub_path)

                # Prevent Directory Traversal
                if not target_path.startswith(os.path.abspath(STORAGE_DIR)):
                    conn.sendall(json.dumps({"status": "error", "message": "Access Denied: Path escape detected."}).encode())
                    continue

                if op == "create":
                    os.makedirs(target_path, exist_ok=True)
                    conn.sendall(json.dumps({"status": "success", "message": f"Directory {sub_path} created."}).encode())
                elif op == "delete":
                    if os.path.exists(target_path) and os.path.isdir(target_path):
                        try:
                            os.rmdir(target_path) # strictly remove empty folders
                            conn.sendall(json.dumps({"status": "success", "message": f"Directory {sub_path} deleted."}).encode())
                        except OSError:
                            conn.sendall(json.dumps({"status": "error", "message": "Directory is not empty."}).encode())
                    else:
                        conn.sendall(json.dumps({"status": "error", "message": "Directory does not exist."}).encode())

            elif action == "delete":
                filename = os.path.basename(request.get("filename"))
                filepath = os.path.normpath(os.path.join(STORAGE_DIR, filename))
                
                if not filepath.startswith(os.path.abspath(STORAGE_DIR)):
                    conn.sendall(json.dumps({"status": "error", "message": "Access Denied."}).encode())
                    continue

                if os.path.exists(filepath) and os.path.isfile(filepath):
                    os.remove(filepath)
                    conn.sendall(json.dumps({"status": "success", "message": f"File '{filename}' deleted."}).encode())
                else:
                    conn.sendall(json.dumps({"status": "error", "message": "File not found."}).encode())

            elif action == "upload":
                filename = os.path.basename(request.get("filename"))
                filesize = request.get("filesize")
                filepath = os.path.join(STORAGE_DIR, filename)
                overwrite_confirmed = request.get("overwrite", False)

                if os.path.exists(filepath) and not overwrite_confirmed:
                    conn.sendall(json.dumps({"status": "exists", "message": "File already exists on the server. Overwrite? (y/n)"}).encode())
                    continue
                
                conn.sendall(json.dumps({"status": "ready"}).encode())
                
                # Receive the file in chunks
                received_bytes = 0
                with open(filepath, 'wb') as f:
                    while received_bytes < filesize:
                        chunk = conn.recv(min(BUFFER_SIZE, filesize - received_bytes))
                        if not chunk:
                            break
                        f.write(chunk)
                        received_bytes += len(chunk)
                
                conn.sendall(json.dumps({"status": "success", "message": "File uploaded successfully."}).encode())
                print(f"[FILE] '{filename}' successfully received from client.")

            elif action == "download":
                filename = os.path.basename(request.get("filename"))
                filepath = os.path.join(STORAGE_DIR, filename)
                offset = request.get("offset", 0)  # For resuming downloads

                if not os.path.exists(filepath) or not os.path.isfile(filepath):
                    conn.sendall(json.dumps({"status": "error", "message": "File not found."}).encode())
                    continue

                filesize = os.path.getsize(filepath)
                file_hash = calculate_sha256(filepath)
                
                # Send ready signal along with details for download/resume verification
                conn.sendall(json.dumps({"status": "ready", "filesize": filesize, "sha256": file_hash}).encode())
                
                # Wait for acknowledgment from client before starting streaming
                ack = conn.recv(BUFFER_SIZE).decode()
                if "start" in ack:
                    with open(filepath, 'rb') as f:
                        f.seek(offset)
                        while True:
                            chunk = f.read(BUFFER_SIZE)
                            if not chunk:
                                break
                            conn.sendall(chunk)
                    print(f"[FILE] '{filename}' transfer completed starting from offset {offset}.")

    except Exception as e:
        print(f"[ERROR] Exception occurred with connection {addr}: {e}")
    finally:
        conn.close()
        print(f"[DISCONNECTED] Client at {addr} disconnected.")

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[STARTING] Server is listening on {HOST}:{PORT}...")

    while True:
        conn, addr = server.accept()
        thread = threading.create_thread = threading.Thread(target=handle_client, args=(conn, addr))
        thread.start()

if __name__ == '__main__':
    main()