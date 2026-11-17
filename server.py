"""Central TCP server for the CNT3004 networked file-sharing project."""

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import threading
import time
from pathlib import Path

from protocol import receive_message, send_message, send_file, CHUNK_SIZE
from analysis import initialize_analysis, record_result

# =============================================================================
# SERVER SETTINGS AND SHARED DATA
# The server listens on every network interface so other computers on the
# private network can connect. All uploaded files go into the storage folder.
# =============================================================================
HOST = "0.0.0.0"
PORT = int(os.environ.get("CNT3004_PORT", "8080"))
STORAGE_FOLDER = Path(__file__).resolve().parent / "storage"
ACCOUNT_FILE = Path(__file__).resolve().parent / "accounts.json"
PASSWORD_ROUNDS = 200_000

STORAGE_FOLDER.mkdir(exist_ok=True)
# The set stores file paths currently being transferred.
ACTIVE_FILES = set()
# The lock keeps multiple client threads from changing that set at once.
ACTIVE_LOCK = threading.Lock()

# These prefixes identify text, audio, and video files on the server.
FILE_PREFIXES = {".txt": "TS", ".wav": "AU", ".mp4": "VD"}


# =============================================================================
# CREATE DEMONSTRATION USER ACCOUNTS
# Passwords are salted and processed with PBKDF2 before being stored.
# The real password is not written to accounts.json.
# =============================================================================
def create_accounts():
    """Create two example accounts the first time the server is started."""
    if ACCOUNT_FILE.exists():
        return

    demo_passwords = {
        "user1": "password123",
        "admin": "adminpass",
    }
    accounts = {}

    for username, password in demo_passwords.items():
        salt = secrets.token_bytes(16)
        password_key = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, PASSWORD_ROUNDS
        )
        accounts[username] = {
            "salt": salt.hex(),
            "key": password_key.hex(),
            "rounds": PASSWORD_ROUNDS,
        }

    with open(ACCOUNT_FILE, "w", encoding="utf-8") as file:
        json.dump(accounts, file, indent=4)


# =============================================================================
# CHECK FILE PATHS AND FILE NAMES
# get_safe_path() prevents a client from reaching files outside server storage.
# check_file_name() applies the professor's TS, AU, and VD naming examples.
# =============================================================================
def get_safe_path(name):
    """Return a storage path only if it stays inside the storage folder."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("A filename or folder name is required.")

    storage_root = STORAGE_FOLDER.resolve()
    requested_path = (storage_root / name).resolve()

    if requested_path == storage_root or storage_root not in requested_path.parents:
        raise ValueError("That path is outside the server storage folder.")

    return requested_path


def check_file_name(filename):
    """Check the TS001.txt, AU001.wav, or VD001.mp4 naming pattern."""
    extension = Path(filename).suffix.lower()
    prefix = FILE_PREFIXES.get(extension)

    if prefix:
        pattern = rf"{prefix}\d{{3}}{re.escape(extension)}"
        if not re.fullmatch(pattern, Path(filename).name, flags=re.IGNORECASE):
            raise ValueError(
                f"Use a name such as {prefix}001{extension}."
            )


def send_error(client_socket, message):
    """Send a standard error response to the client."""
    send_message(client_socket, {"status": "error", "message": message})


# =============================================================================
# AUTHENTICATE A CLIENT
# The server sends a random challenge. The client proves it knows the password
# by returning an HMAC value. The password itself is never sent in clear text.
# =============================================================================
def verify_user(client_socket):
    """Check one username and its challenge-response proof."""
    send_message(client_socket, {"status": "login_required"})
    login_request = receive_message(client_socket)

    if login_request.get("action") != "login":
        send_error(client_socket, "Please log in first.")
        return False

    username = login_request.get("username", "")
    with open(ACCOUNT_FILE, "r", encoding="utf-8") as file:
        accounts = json.load(file)

    account = accounts.get(username)
    if not account:
        send_error(client_socket, "Invalid username or password.")
        return False

    salt = bytes.fromhex(account["salt"])
    password_key = bytes.fromhex(account["key"])
    rounds = account["rounds"]
    challenge = secrets.token_bytes(32)

    send_message(client_socket, {
        "status": "challenge",
        "salt": salt.hex(),
        "challenge": challenge.hex(),
        "rounds": rounds,
    })

    answer = receive_message(client_socket)
    received_proof = answer.get("proof", "")
    correct_proof = hmac.new(password_key, challenge, hashlib.sha256).hexdigest()

    if hmac.compare_digest(received_proof, correct_proof):
        send_message(client_socket, {
            "status": "success",
            "message": "Login successful.",
        })
        print(f"[LOGIN] {username} logged in.")
        return True

    send_error(client_socket, "Invalid username or password.")
    return False


# =============================================================================
# PREVENT FILE OPERATIONS FROM CLASHING
# The server marks a file as busy during an upload or download. This helps
# prevent a second client from deleting or replacing that file at the same time.
# =============================================================================
def lock_file(path):
    """Mark a file as busy. Return False if another operation already uses it."""
    key = str(path)
    with ACTIVE_LOCK:
        if key in ACTIVE_FILES:
            return False
        ACTIVE_FILES.add(key)
        return True


def unlock_file(path):
    """Mark a file as available after its operation finishes."""
    with ACTIVE_LOCK:
        ACTIVE_FILES.discard(str(path))


# =============================================================================
# RECEIVE AN UPLOAD
# The client sends the file name and size first. The server checks the name,
# asks before overwriting, then receives exactly that many bytes in chunks.
# =============================================================================
def upload_file(client_socket, request):
    """Receive one file and save it in server storage."""
    request_started = time.perf_counter()
    filename = request.get("filename", "")
    file_size = request.get("filesize")

    if not isinstance(file_size, int) or isinstance(file_size, bool) or file_size < 0:
        send_error(client_socket, "Invalid file size.")
        return

    try:
        check_file_name(Path(filename).name)
        destination = get_safe_path(filename)
        destination.parent.mkdir(parents=True, exist_ok=True)
    except (ValueError, OSError) as error:
        send_error(client_socket, str(error))
        return

    if not lock_file(destination):
        send_error(client_socket, "This file is already being processed.")
        return

    temporary_file = destination.with_name(destination.name + ".uploading")

    try:
        if destination.exists():
            send_message(client_socket, {
                "status": "exists",
                "message": f"{filename} already exists. Overwrite? (y/n)",
            })
            answer = receive_message(client_socket)
            if not answer.get("overwrite", False):
                send_message(client_socket, {
                    "status": "cancelled",
                    "message": "Upload cancelled.",
                })
                return

        send_message(client_socket, {"status": "ready"})
        transfer_started = time.perf_counter()
        bytes_received = 0

        with open(temporary_file, "wb") as file:
            while bytes_received < file_size:
                amount = min(CHUNK_SIZE, file_size - bytes_received)
                chunk = client_socket.recv(amount)
                if not chunk:
                    raise ConnectionError("Client disconnected during upload.")
                file.write(chunk)
                bytes_received += len(chunk)

        # Only replace the final filename after the full upload has arrived.
        os.replace(temporary_file, destination)
        transfer_seconds = time.perf_counter() - transfer_started
        response_seconds = time.perf_counter() - request_started

        record_result("server", "UPLOAD", filename, file_size,
                      transfer_seconds, response_seconds)
        send_message(client_socket, {
            "status": "success",
            "message": "File uploaded successfully.",
        })
        print(f"[UPLOAD] Received {filename} ({file_size} bytes).")

    except Exception:
        if temporary_file.exists():
            temporary_file.unlink()
        raise
    finally:
        unlock_file(destination)


# =============================================================================
# SEND A DOWNLOAD
# The server tells the client the file size, waits for its ready message, and
# then sends the complete file in chunks. This is the normal required download.
# =============================================================================
def download_file(client_socket, request):
    """Send one complete file from server storage to the client."""
    request_started = time.perf_counter()
    filename = request.get("filename", "")

    try:
        file_path = get_safe_path(filename)
    except ValueError as error:
        send_error(client_socket, str(error))
        return

    if not file_path.is_file():
        send_error(client_socket, "File does not exist on the server.")
        return

    if not lock_file(file_path):
        send_error(client_socket, "This file is already being processed.")
        return

    try:
        file_size = file_path.stat().st_size
        send_message(client_socket, {"status": "ready", "filesize": file_size})

        # Wait until the client is ready so file bytes do not mix with JSON.
        answer = receive_message(client_socket)
        if answer.get("action") != "download_ready":
            return

        transfer_started = time.perf_counter()
        send_file(client_socket, file_path)
        transfer_seconds = time.perf_counter() - transfer_started
        response_seconds = time.perf_counter() - request_started

        record_result("server", "DOWNLOAD", filename, file_size,
                      transfer_seconds, response_seconds)
        print(f"[DOWNLOAD] Sent {filename} ({file_size} bytes).")
    finally:
        unlock_file(file_path)


# =============================================================================
# DIRECTORY AND DELETE OPERATIONS
# These are short requests. The server sends back a JSON success or error reply.
# =============================================================================
def list_files(client_socket):
    """Send the list of files stored on the server."""
    files = []
    for path in STORAGE_FOLDER.rglob("*"):
        # Ignore hidden support files such as .gitkeep in the displayed listing.
        if path.is_file() and not path.name.startswith(".") and not path.name.endswith(".uploading"):
            files.append(path.relative_to(STORAGE_FOLDER).as_posix())
    send_message(client_socket, {"status": "success", "files": sorted(files)})


def change_subfolder(client_socket, request):
    """Create a folder or delete an empty folder inside server storage."""
    operation = request.get("operation")

    try:
        folder = get_safe_path(request.get("path", ""))
        if operation == "create":
            folder.mkdir(parents=True, exist_ok=True)
            send_message(client_socket, {"status": "success", "message": "Folder created."})
        elif operation == "delete":
            folder.rmdir()
            send_message(client_socket, {"status": "success", "message": "Empty folder deleted."})
        else:
            send_error(client_socket, "Use create or delete.")
    except (ValueError, OSError) as error:
        send_error(client_socket, str(error))


def delete_file(client_socket, request):
    """Delete a file only if it exists and is not in another operation."""
    try:
        file_path = get_safe_path(request.get("filename", ""))
    except ValueError as error:
        send_error(client_socket, str(error))
        return

    # Use the same file lock as upload/download to avoid deleting a busy file.
    if not lock_file(file_path):
        send_error(client_socket, "File is currently being processed.")
        return

    try:
        if file_path.is_file():
            file_path.unlink()
            send_message(client_socket, {"status": "success", "message": "File deleted."})
        else:
            send_error(client_socket, "File does not exist.")
    except OSError as error:
        send_error(client_socket, str(error))
    finally:
        unlock_file(file_path)


# =============================================================================
# HANDLE ONE CONNECTED CLIENT
# Each worker thread runs this function for its own client. It authenticates
# that client, then waits for upload/download/delete/dir/subfolder commands.
# =============================================================================
def handle_client(client_socket, address):
    """Authenticate one client and process its commands until disconnect."""
    print(f"[CONNECTION] Client connected: {address}")

    try:
        if not verify_user(client_socket):
            return

        while True:
            request = receive_message(client_socket)
            if not isinstance(request, dict):
                send_error(client_socket, "Invalid request format.")
                continue

            action = request.get("action")

            if action == "upload":
                upload_file(client_socket, request)
            elif action == "download":
                download_file(client_socket, request)
            elif action == "delete":
                delete_file(client_socket, request)
            elif action == "dir":
                list_files(client_socket)
            elif action == "subfolder":
                change_subfolder(client_socket, request)
            elif action == "disconnect":
                send_message(client_socket, {
                    "status": "success",
                    "message": "Disconnected.",
                })
                break
            else:
                send_error(client_socket, "Unknown command.")

    except (ConnectionError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[CLIENT ERROR] {address}: {error}")
    finally:
        client_socket.close()
        print(f"[DISCONNECTION] Client disconnected: {address}")


# =============================================================================
# START THE SERVER
# The main server accepts each new connection and starts a separate thread.
# This lets the server keep accepting clients while other clients are working.
# =============================================================================
def start_server():
    """Start listening for client connections."""
    create_accounts()
    initialize_analysis()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen()

    print(f"Server is listening on port {PORT}...")
    print(f"Files are stored in: {STORAGE_FOLDER}")
    print("Performance logging is ready.")

    try:
        while True:
            client_socket, address = server_socket.accept()
            client_thread = threading.Thread(
                target=handle_client,
                args=(client_socket, address),
                daemon=True,
            )
            client_thread.start()
    except KeyboardInterrupt:
        print("Server is shutting down.")
    finally:
        server_socket.close()


# =============================================================================
# PROGRAM ENTRY POINT
# Run start_server() only when this file is launched directly.
# =============================================================================
if __name__ == "__main__":
    start_server()
