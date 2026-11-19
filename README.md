# CNT3004 File-Sharing Project (Required Features Only)

This version intentionally excludes the optional bonus task for interrupted-download recovery. It does not have a `resume` command or byte-offset download logic.

## Project files

- `server.py` - Starts the TCP server, authenticates users, handles client threads, and manages server files.
- `client.py` - Provides the commands used by a person connecting to the server.
- `protocol.py` - Sends JSON instructions and transfers file bytes in chunks.
- `analysis.py` - Records performance measurements and creates a transfer-speed graph.

## 1. Set up the project

Use Python 3.9 or newer. Keep all four Python files in the same project folder. The `storage`, `downloads`, and `results` folders are created automatically if they do not exist.

Install the graph package:

```bash
python -m pip install -r requirements.txt
```

## 2. Start the server

On the computer that will act as the server, open VS Code's terminal and run:

```bash
python server.py
```

The server listens on port `8080`. On Windows, run `ipconfig` on the server computer and find its IPv4 address. Allow Python through the server computer's firewall on the private network if Windows asks.

## 3. Start each client

On each of the two other computers, open the same project folder and run:

```bash
python client.py
```

At the `CloudClient>` prompt, enter:

```text
connect SERVER_IP 5001
login
```

Replace `SERVER_IP` with the server computer's IPv4 address.

## 4. Demonstration accounts

The server creates these demonstration accounts the first time it starts:

| Username | Password |
|---|---|
| `user1` | `password123` |
| `admin` | `adminpass` |

Change the demonstration passwords before submitting. To regenerate the account file after changing the values in `server.py`, stop the server, delete `accounts.json`, and start the server again. The account file stores salted PBKDF2 password keys, not the original passwords.

## 5. Client commands

```text
connect SERVER_IP [PORT]
login
upload "LOCAL_FILE_PATH" [SERVER_FILENAME]
download SERVER_FILENAME
delete SERVER_FILENAME
dir
subfolder create FOLDER_NAME
subfolder delete FOLDER_NAME
exit
```
