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
connect SERVER_IP 8080
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

Examples using the required type prefixes:

```text
upload "C:/Project/Samples/notes.txt" TS001.txt
upload "C:/Project/Samples/audio.wav" AU001.wav
upload "C:/Project/Samples/video.mp4" VD001.mp4
dir
download TS001.txt
delete TS001.txt
subfolder create ClassFiles
subfolder delete ClassFiles
```

For `.txt`, `.wav`, and `.mp4` uploads, the server checks for the naming pattern `TS001.txt`, `AU001.wav`, or `VD001.mp4`. Other extensions are not assigned these three prefixes by the current code.

Downloads are saved in the client's `downloads/` folder. Uploads are saved in the server's `storage/` folder. If a server filename already exists, the client is asked whether it should be overwritten.

## 6. Performance analysis

The client and server each save measurements in `results/`:

- `client_stats.csv`
- `server_stats.csv`

The measurements include operation, filename, file size, transfer duration, average transfer speed in MB/s, and response time in milliseconds.

Run this on a computer that has the CSV results:

```bash
python analysis.py
```

It prints the saved measurements and creates `results/transfer_performance.png` when upload/download measurements are available. Since each physical computer writes its own local CSV files, copy the CSVs from the server and client computers into one results folder when preparing the final combined analysis.

## 7. Required testing checklist

- [ ] Run the server on one physical computer.
- [ ] Run Client 1 on a second physical computer.
- [ ] Run Client 2 on a third physical computer.
- [ ] Connect all three computers to the same personal hotspot or private wireless network. Do not use Florida Poly Wi-Fi for the project demonstration.
- [ ] Connect both clients to the server at the same time.
- [ ] Test login with a valid account and an invalid password.
- [ ] Upload a 25 MB `.txt` file using a `TS###.txt` name.
- [ ] Upload a 1 GB `.wav` file using an `AU###.wav` name.
- [ ] Upload a 2 GB `.mp4` file using a `VD###.mp4` name.
- [ ] Test the overwrite question.
- [ ] Download each sample file.
- [ ] Test deleting an existing file and a file that does not exist.
- [ ] Test `dir`.
- [ ] Test creating and deleting a subfolder.
- [ ] Collect CSV performance data and create the graph.

## Security note

The login process uses salted PBKDF2 and a random challenge with HMAC so the password itself is not sent in clear text. This version does not use TLS to encrypt all network traffic or file contents. Use the private network required by the assignment for your demonstration; TLS would be an additional security improvement.
