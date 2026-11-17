"""Record network performance and create a simple transfer-speed graph."""

import csv
import time
from pathlib import Path
from threading import Lock

# =============================================================================
# RESULTS LOCATION AND CSV COLUMNS
# Each computer saves its own measurements.
# =============================================================================
RESULTS_FOLDER = Path(__file__).resolve().parent / "results"
CSV_FIELDS = [
    "time",
    "side",
    "operation",
    "filename",
    "size_bytes",
    "transfer_seconds",
    "speed_mbps",
    "response_time_ms",
]
CSV_LOCK = Lock()


# =============================================================================
# START THE ANALYSIS MODULE
# The server calls this when it starts so the results folder is ready.
# =============================================================================
def initialize_analysis():
    """Make sure the folder for performance results exists."""
    RESULTS_FOLDER.mkdir(exist_ok=True)


# =============================================================================
# SAVE A PERFORMANCE MEASUREMENT
# Record file size, transfer time, calculated speed, and response time.
# =============================================================================
def record_result(side, operation, filename, size_bytes, transfer_seconds,
                  response_seconds):
    """Append one measurement to the client or server CSV file."""
    initialize_analysis()
    csv_file = RESULTS_FOLDER / f"{side}_stats.csv"

    # Convert the transferred bytes into megabytes, then divide by seconds.
    if transfer_seconds > 0:
        speed = (size_bytes / (1024 * 1024)) / transfer_seconds
    else:
        speed = 0

    row = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "side": side,
        "operation": operation,
        "filename": filename,
        "size_bytes": size_bytes,
        "transfer_seconds": round(transfer_seconds, 4),
        "speed_mbps": round(speed, 3),
        "response_time_ms": round(response_seconds * 1000, 2),
    }

    # The lock prevents two server threads writing to the same CSV at once.
    with CSV_LOCK:
        file_exists = csv_file.exists()
        with open(csv_file, "a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)


# =============================================================================
# DISPLAY THE SAVED RESULTS
# quick way to inspect the measurements after testing.
# =============================================================================
def show_results():
    """Print all measurements saved on this computer."""
    for side in ("client", "server"):
        csv_file = RESULTS_FOLDER / f"{side}_stats.csv"
        if not csv_file.exists():
            continue

        print(f"\n{side.upper()} MEASUREMENTS")
        with open(csv_file, "r", newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                print(row)


# =============================================================================
# CREATE A GRAPH FOR THE REPORT
# The graph compares average upload and download speeds from recorded tests.
# =============================================================================
def create_graph():
    """Create a bar graph of average upload and download speeds."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("Install matplotlib to create the graph: pip install matplotlib")
        return

    labels = []
    averages = []

    for side in ("client", "server"):
        csv_file = RESULTS_FOLDER / f"{side}_stats.csv"
        if not csv_file.exists():
            continue

        speeds = {}
        with open(csv_file, "r", newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                # Directory and delete commands do not transfer file data.
                if row["operation"] not in ("UPLOAD", "DOWNLOAD"):
                    continue
                speeds.setdefault(row["operation"], []).append(
                    float(row["speed_mbps"])
                )

        for operation, values in speeds.items():
            labels.append(f"{side} {operation}")
            averages.append(sum(values) / len(values))

    if not labels:
        print("No upload or download measurements are available yet.")
        return

    plt.figure(figsize=(9, 5))
    plt.bar(labels, averages)
    plt.ylabel("Average speed (MB/s)")
    plt.title("File Transfer Performance")
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()

    graph_path = RESULTS_FOLDER / "transfer_performance.png"
    plt.savefig(graph_path)
    plt.close()
    print(f"Graph saved to {graph_path}")


# =============================================================================
# RUN ANALYSIS WHEN THIS FILE IS OPENED DIRECTLY
# Starting the server also calls initialize_analysis() automatically.
# =============================================================================
if __name__ == "__main__":
    show_results()
    create_graph()
