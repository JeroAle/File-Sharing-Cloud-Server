"""Shared communication tools used by both sides of the file-sharing system."""

import json
import struct

# =============================================================================
# NETWORK SETTINGS
# Both computers use the same chunk size when moving file data.
# A 64 KB chunk keeps memory use low, even for a 2 GB video.
# =============================================================================
CHUNK_SIZE = 64 * 1024
MAX_MESSAGE_SIZE = 1024 * 1024


# =============================================================================
# RECEIVING COMPLETE CONTROL MESSAGES
# TCP sends a stream of bytes. It does not promise that one recv() call
# will contain one complete message, so receive_exact() keeps reading.
# =============================================================================
def receive_exact(sock, number_of_bytes):
    """Read exactly the requested number of bytes from a socket."""
    data = bytearray()

    while len(data) < number_of_bytes:
        part = sock.recv(number_of_bytes - len(data))
        if not part:
            raise ConnectionError("The other computer disconnected.")
        data.extend(part)

    return bytes(data)


# =============================================================================
# SENDING AND RECEIVING JSON INSTRUCTIONS
# JSON is used for short instructions such as login, upload, download, and dir.
# A four-byte length header tells the receiver how many JSON bytes to expect.
# =============================================================================
def send_message(sock, message):
    """Send one length-prefixed JSON message."""
    message_bytes = json.dumps(message).encode("utf-8")
    if len(message_bytes) > MAX_MESSAGE_SIZE:
        raise ValueError("Message is too large.")

    header = struct.pack("!I", len(message_bytes))
    sock.sendall(header + message_bytes)


def receive_message(sock):
    """Receive one complete JSON message, using its length header."""
    header = receive_exact(sock, 4)
    message_length = struct.unpack("!I", header)[0]

    if message_length > MAX_MESSAGE_SIZE:
        raise ValueError("Message is too large.")

    message_bytes = receive_exact(sock, message_length)
    return json.loads(message_bytes.decode("utf-8"))


# =============================================================================
# SENDING FILE CONTENT
# File data is sent as raw bytes after both sides agree on the file size.
# We read and write one chunk at a time instead of loading the whole file.
# =============================================================================
def send_file(sock, file_path):
    """Send a file in chunks over the already-open socket."""
    with open(file_path, "rb") as file:
        while True:
            chunk = file.read(CHUNK_SIZE)
            if not chunk:
                break
            sock.sendall(chunk)


def receive_file(sock, file_path, total_bytes):
    """Receive exactly total_bytes and save them as a new file."""
    bytes_left = total_bytes

    with open(file_path, "wb") as file:
        while bytes_left > 0:
            chunk = sock.recv(min(CHUNK_SIZE, bytes_left))
            if not chunk:
                raise ConnectionError("The connection ended during file transfer.")
            file.write(chunk)
            bytes_left -= len(chunk)
