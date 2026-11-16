%%writefile client.py
import socket
import os
import hashlib
import json
import time
import csv

BUFFER_SIZE = 4096
STATS_FILE = 'network_stats.csv'

def save_stats(op_type, filename, size_bytes, duration, rate_mbs, response_time):
    # Save metrics for reporting offline
    fields = ['timestamp', 'operation', 'filename', 'size_bytes', 'duration_seconds', 'rate_mbs', 'response_time_ms']
    file_exists = os.path.exists(STATS_FILE)
    with open(STATS_FILE, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'operation': op_type,
            'filename': filename,
            'size_bytes': size_bytes,
            'duration_seconds': round(duration, 4),
            'rate_mbs': round(rate_mbs, 4),
            'response_time_ms': round(response_time * 1000, 2)
        })

def calculate_sha256(filepath):
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(BUFFER_SIZE), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

class CloudClient:
    def __init__(self):
        self.sock = None
        self.authenticated = False

    def connect(self, host, port):
        t0 = time.time()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, int(port)))
        r_time = time.time() - t0
        print(f"Successfully connected to server {host}:{port} in {round(r_time * 1000, 2)} ms.")

    def login(self, username, password):
        if not self.sock:
            print("Please connect to the server first.")
            return False
        
        # Secure Hashing
        hashed_pass = hashlib.sha256(password.encode()).hexdigest()
        payload = {"action": "login", "username": username, "password": hashed_pass}
        
        t0 = time.time()
        self.sock.sendall(json.dumps(payload).encode())
        res = json.loads(self.sock.recv(BUFFER_SIZE).decode())
        r_time = time.time() - t0

        if res.get("status") == "success":
            self.authenticated = True
            print("Authentication successful.")
            return True
        else:
            print(f"Authentication failed: {res.get('message')}")
            return False

    def upload(self, filepath):
        if not os.path.exists(filepath):
            print("Local file does not exist.")
            return
        
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        
        t_start = time.time()
        payload = {"action": "upload", "filename": filename, "filesize": filesize, "overwrite": False}
        self.sock.sendall(json.dumps(payload).encode())
        res = json.loads(self.sock.recv(BUFFER_SIZE).decode())
        
        if res.get("status") == "exists":
            ans = input(res.get("message") + " ")
            if ans.lower().strip() == 'y':
                payload["overwrite"] = True
                self.sock.sendall(json.dumps(payload).encode())
                res = json.loads(self.sock.recv(BUFFER_SIZE).decode())
            else:
                print("Upload cancelled by user.")
                return
                
        if res.get("status") == "ready":
            print("Starting upload stream...")
            transfer_start = time.time()
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(BUFFER_SIZE)
                    if not chunk:
                        break
                    self.sock.sendall(chunk)
                    
            final_res = json.loads(self.sock.recv(BUFFER_SIZE).decode())
            duration = time.time() - transfer_start
            resp_time = time.time() - t_start
            
            if final_res.get("status") == "success":
                rate_mbs = (filesize / (1024 * 1024)) / duration if duration > 0 else 0
                print(f"{final_res.get('message')} Speed: {round(rate_mbs, 2)} MB/s, Time: {round(duration, 2)}s")
                save_stats('UPLOAD', filename, filesize, duration, rate_mbs, resp_time)
            else:
                print(f"Upload failed: {final_res.get('message')}")

    def download(self, filename, resume=False):
        t_start = time.time()
        offset = 0
        local_path = f"downloaded_{filename}"
        
        if resume and os.path.exists(local_path):
            offset = os.path.getsize(local_path)
            print(f"Resuming download. Current local size is {offset} bytes.")

        payload = {"action": "download", "filename": filename, "offset": offset}
        self.sock.sendall(json.dumps(payload).encode())
        res = json.loads(self.sock.recv(BUFFER_SIZE).decode())

        if res.get("status") == "ready":
            server_size = res.get("filesize")
            expected_hash = res.get("sha256")
            
            self.sock.sendall("start".encode())
            
            transfer_start = time.time()
            mode = 'ab' if offset > 0 else 'wb'
            received_bytes = offset
            
            with open(local_path, mode) as f:
                while received_bytes < server_size:
                    chunk = self.sock.recv(min(BUFFER_SIZE, server_size - received_bytes))
                    if not chunk:
                        break
                    f.write(chunk)
                    received_bytes += len(chunk)
            
            duration = time.time() - transfer_start
            resp_time = time.time() - t_start
            
            # Verify Integrity
            client_hash = calculate_sha256(local_path)
            if client_hash == expected_hash:
                rate_mbs = ((server_size - offset) / (1024 * 1024)) / duration if duration > 0 else 0
                print(f"Download complete. Integrity Verified (SHA-256 match).")
                print(f"Downloaded {server_size - offset} bytes in {round(duration, 2)}s at {round(rate_mbs, 2)} MB/s.")
                save_stats('DOWNLOAD', filename, server_size - offset, duration, rate_mbs, resp_time)
            else:
                print("Warning: File downloaded successfully but integrity validation failed (SHA mismatch)!")
        else:
            print(f"Error: {res.get('message')}")

    def delete(self, filename):
        payload = {"action": "delete", "filename": filename}
        self.sock.sendall(json.dumps(payload).encode())
        res = json.loads(self.sock.recv(BUFFER_SIZE).decode())
        print(res.get("message") or res.get("status"))

    def list_dir(self):
        payload = {"action": "dir"}
        self.sock.sendall(json.dumps(payload).encode())
        res = json.loads(self.sock.recv(BUFFER_SIZE).decode())
        if res.get("status") == "success":
            print("--- Server Storage Files ---")
            for f in res.get("files", []):
                print(f"- {f}")
        else:
            print(f"Error listing directory: {res.get('message')}")

    def subfolder(self, op, path):
        payload = {"action": "subfolder", "operation": op, "path": path}
        self.sock.sendall(json.dumps(payload).encode())
        res = json.loads(self.sock.recv(BUFFER_SIZE).decode())
        print(res.get("message") or res.get("status"))

# CLI Loop helper
def run_cli():
    client = CloudClient()
    print("Cloud File Sharing System CLI started. Available commands: connect, login, upload, download, resume, delete, dir, subfolder, exit")
    while True:
        cmd_input = input("CloudClient> ").strip().split()
        if not cmd_input:
            continue
        cmd = cmd_input[0].lower()
        
        if cmd == "connect":
            if len(cmd_input) < 3:
                print("Usage: connect [IP] [Port]")
                continue
            client.connect(cmd_input[1], cmd_input[2])
        elif cmd == "login":
            user = input("Username: ")
            pswd = input("Password: ")
            client.login(user, pswd)
        elif cmd == "upload":
            if len(cmd_input) < 2:
                print("Usage: upload [filepath]")
                continue
            client.upload(cmd_input[1])
        elif cmd == "download":
            if len(cmd_input) < 2:
                print("Usage: download [filename]")
                continue
            client.download(cmd_input[1], resume=False)
        elif cmd == "resume":
            if len(cmd_input) < 2:
                print("Usage: resume [filename]")
                continue
            client.download(cmd_input[1], resume=True)
        elif cmd == "delete":
            if len(cmd_input) < 2:
                print("Usage: delete [filename]")
                continue
            client.delete(cmd_input[1])
        elif cmd == "dir":
            client.list_dir()
        elif cmd == "subfolder":
            if len(cmd_input) < 3:
                print("Usage: subfolder [create|delete] [path]")
                continue
            client.subfolder(cmd_input[1], cmd_input[2])
        elif cmd == "exit":
            break
        else:
            print("Unknown command.")

if __name__ == '__main__':
    run_cli()