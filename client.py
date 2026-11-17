"""Command-line client used by people connecting to the file server."""

import getpass
import hashlib
import hmac
import shlex
import socket
import time
from pathlib import Path

from protocol import send_message, receive_message, send_file, receive_file
from analysis import record_result

# =============================================================================
# CLIENT SETTINGS
# The client uses the server's IP address and port to request a connection.
# =============================================================================
DEFAULT_PORT = 8080
DOWNLOAD_FOLDER = Path(__file__).resolve().parent / "downloads"
DOWNLOAD_FOLDER.mkdir(exist_ok=True)


# =============================================================================
# CLIENT CONNECTION AND LOGIN
# CloudClient keeps the socket open and provides one method for each command.
# =============================================================================
class CloudClient:
    """Manage one connection between a client computer and the server."""

    def __init__(self):
        self.socket = None
        self.logged_in = False

    def connect(self, server_ip, port=DEFAULT_PORT):
        """Open a TCP connection and receive the server's login prompt."""
        self.socket = socket.create_connection((server_ip, int(port)), timeout=20)
        self.socket.settimeout(None)
        greeting = receive_message(self.socket)

        if greeting.get("status") != "login_required":
            self.socket.close()
            self.socket = None
            raise ConnectionError("The server sent an unexpected response.")

        print("Connected. Enter the login command next.")

    def login(self, username, password):
        """Authenticate without sending the actual password to the server."""
        if not self.socket:
            print("Connect to the server first.")
            return False

        send_message(self.socket, {"action": "login", "username": username})
        challenge = receive_message(self.socket)

        if challenge.get("status") != "challenge":
            print(challenge.get("message", "Login failed."))
            self.disconnect()
            return False

        salt = bytes.fromhex(challenge["salt"])
        random_challenge = bytes.fromhex(challenge["challenge"])
        rounds = int(challenge["rounds"])

        # Create the same password key the server created when it saved the account.
        password_key = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, rounds
        )
        # Send proof of the password, not the password itself.
        proof = hmac.new(password_key, random_challenge, hashlib.sha256).hexdigest()
        send_message(self.socket, {"proof": proof})

        answer = receive_message(self.socket)
        self.logged_in = answer.get("status") == "success"
        print(answer.get("message", "Login failed."))

        if not self.logged_in:
            self.disconnect()
        return self.logged_in

    def ready(self):
        """Check that the client is connected and logged in before a command."""
        if not self.socket or not self.logged_in:
            print("Connect and log in first.")
            return False
        return True

    # =========================================================================
    # UPLOAD A FILE TO THE SERVER
    # The client first sends the file name and size. It sends file bytes only
    # after the server replies that the upload is ready.
    # =========================================================================
    def upload(self, local_path, server_name=None):
        """Upload one local file to the server."""
        if not self.ready():
            return

        file_path = Path(local_path).expanduser()
        if not file_path.is_file():
            print("That local file does not exist.")
            return

        filename = server_name or file_path.name
        file_size = file_path.stat().st_size
        request_started = time.perf_counter()

        send_message(self.socket, {
            "action": "upload",
            "filename": filename,
            "filesize": file_size,
        })
        answer = receive_message(self.socket)

        # If the server already has this name, ask the user before replacing it.
        if answer.get("status") == "exists":
            choice = input(answer["message"] + " ").strip().lower()
            send_message(self.socket, {"overwrite": choice == "y"})
            answer = receive_message(self.socket)

        if answer.get("status") != "ready":
            print(answer.get("message", answer.get("status")))
            return

        transfer_started = time.perf_counter()
        send_file(self.socket, file_path)
        result = receive_message(self.socket)
        transfer_seconds = time.perf_counter() - transfer_started
        response_seconds = time.perf_counter() - request_started

        if result.get("status") == "success":
            record_result("client", "UPLOAD", filename, file_size,
                          transfer_seconds, response_seconds)
            speed = (file_size / (1024 * 1024)) / max(transfer_seconds, 0.000001)
            print(f"Upload complete: {filename} ({speed:.2f} MB/s).")
        else:
            print(result.get("message", "Upload failed."))

    # =========================================================================
    # DOWNLOAD A FILE FROM THE SERVER
    # The server sends the file size first. The client then receives exactly
    # that many bytes and saves them in the downloads folder.
    # =========================================================================
    def download(self, filename):
        """Download a complete file from the server."""
        if not self.ready():
            return

        local_name = Path(filename).name
        final_path = DOWNLOAD_FOLDER / local_name
        temporary_path = DOWNLOAD_FOLDER / (local_name + ".downloading")
        request_started = time.perf_counter()

        send_message(self.socket, {"action": "download", "filename": filename})
        answer = receive_message(self.socket)

        if answer.get("status") != "ready":
            print(answer.get("message", "Download failed."))
            return

        file_size = int(answer["filesize"])

        # Tell the server that the client is ready to receive the file bytes.
        send_message(self.socket, {"action": "download_ready"})
        transfer_started = time.perf_counter()

        try:
            receive_file(self.socket, temporary_path, file_size)
            # Show the completed filename only after all expected bytes arrive.
            temporary_path.replace(final_path)
        except (ConnectionError, OSError) as error:
            if temporary_path.exists():
                temporary_path.unlink()
            print(f"Download failed: {error}")
            self.disconnect()
            return

        transfer_seconds = time.perf_counter() - transfer_started
        response_seconds = time.perf_counter() - request_started
        record_result("client", "DOWNLOAD", filename, file_size,
                      transfer_seconds, response_seconds)
        speed = (file_size / (1024 * 1024)) / max(transfer_seconds, 0.000001)
        print(f"Download complete: {final_path}")
        print(f"Average speed: {speed:.2f} MB/s.")

    # =========================================================================
    # OTHER REQUIRED FILE AND DIRECTORY COMMANDS
    # These commands send a small JSON request and display the server response.
    # =========================================================================
    def delete(self, filename):
        """Ask the server to delete a file."""
        if not self.ready():
            return
        started = time.perf_counter()
        send_message(self.socket, {"action": "delete", "filename": filename})
        answer = receive_message(self.socket)
        elapsed = time.perf_counter() - started
        record_result("client", "DELETE", filename, 0, 0, elapsed)
        print(answer.get("message", answer.get("status")))

    def list_files(self):
        """Ask the server for the names of files in its storage folder."""
        if not self.ready():
            return
        started = time.perf_counter()
        send_message(self.socket, {"action": "dir"})
        answer = receive_message(self.socket)
        elapsed = time.perf_counter() - started
        record_result("client", "DIR", "", 0, 0, elapsed)

        if answer.get("status") == "success":
            print("Files on the server:")
            for filename in answer.get("files", []):
                print(" -", filename)
        else:
            print(answer.get("message", "Could not list files."))

    def subfolder(self, operation, folder_name):
        """Ask the server to create or delete a folder in server storage."""
        if not self.ready():
            return
        started = time.perf_counter()
        send_message(self.socket, {
            "action": "subfolder",
            "operation": operation,
            "path": folder_name,
        })
        answer = receive_message(self.socket)
        elapsed = time.perf_counter() - started
        record_result("client", "SUBFOLDER", folder_name, 0, 0, elapsed)
        print(answer.get("message", answer.get("status")))

    # =========================================================================
    # CLOSE THE CONNECTION
    # Send a disconnect request, then close the local socket.
    # =========================================================================
    def disconnect(self):
        """Close the client connection safely."""
        if self.socket:
            try:
                if self.logged_in:
                    send_message(self.socket, {"action": "disconnect"})
                    receive_message(self.socket)
            except (OSError, ConnectionError):
                pass
            finally:
                self.socket.close()
                self.socket = None
                self.logged_in = False


# =============================================================================
# COMMAND-LINE MENU
# Read what the user types and call the matching CloudClient method.
# =============================================================================
def run_client():
    """Run the command prompt used to control the file-sharing client."""
    client = CloudClient()
    print("File Sharing Client")
    print("Commands: connect, login, upload, download, delete, dir,")
    print("          subfolder create|delete, exit")

    try:
        while True:
            command_line = input("CloudClient> ")
            # shlex supports quoted paths, such as "C:/My Files/report.txt".
            parts = shlex.split(command_line)
            if not parts:
                continue

            command = parts[0].lower()

            if command == "connect":
                if len(parts) not in (2, 3):
                    print("Usage: connect SERVER_IP [PORT]")
                    continue
                port = parts[2] if len(parts) == 3 else DEFAULT_PORT
                try:
                    client.connect(parts[1], port)
                except OSError as error:
                    print(f"Connection failed: {error}")

            elif command == "login":
                username = input("Username: ").strip()
                password = getpass.getpass("Password: ")
                client.login(username, password)

            elif command == "upload":
                if len(parts) not in (2, 3):
                    print('Usage: upload "LOCAL_PATH" [SERVER_FILENAME]')
                else:
                    server_name = parts[2] if len(parts) == 3 else None
                    client.upload(parts[1], server_name)

            elif command == "download":
                if len(parts) != 2:
                    print("Usage: download SERVER_FILENAME")
                else:
                    client.download(parts[1])

            elif command == "delete":
                if len(parts) != 2:
                    print("Usage: delete SERVER_FILENAME")
                else:
                    client.delete(parts[1])

            elif command == "dir":
                client.list_files()

            elif command == "subfolder":
                if len(parts) != 3:
                    print("Usage: subfolder create|delete FOLDER_NAME")
                else:
                    client.subfolder(parts[1].lower(), parts[2])

            elif command == "exit":
                break

            else:
                print("Unknown command. Type one of the listed commands.")

    except (EOFError, KeyboardInterrupt):
        print("Closing client.")
    finally:
        client.disconnect()


# =============================================================================
# PROGRAM ENTRY POINT
# This starts the client menu only when client.py is run directly.
# =============================================================================
if __name__ == "__main__":
    run_client()
