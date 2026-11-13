"""Start the local movie workspace and open it in the default browser."""

import json
import os
from pathlib import Path
import socket
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent


def existing_workspace(port):
    """Reuse this application's server if it is already running."""
    try:
        with urlopen(f"http://127.0.0.1:{port}/openapi.json", timeout=0.5) as response:
            schema = json.load(response)
        return schema.get("info", {}).get("title") == "Movie Processing API"
    except (OSError, ValueError, URLError):
        return False


def choose_port():
    """Use port 8000, or the next free port if another app is using it."""
    for port in range(8000, 8011):
        with socket.socket() as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
                return port, False
            except OSError:
                if existing_workspace(port):
                    return port, True
    raise RuntimeError("Ports 8000–8010 are busy. Close an unused local server and try again.")


def open_when_ready(url):
    """Open the interface once the server can answer requests."""
    for _ in range(100):
        try:
            with urlopen(f"{url}/health", timeout=0.5) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except (OSError, URLError):
            pass
        time.sleep(0.1)


def main():
    os.chdir(PROJECT_ROOT)
    port, already_running = choose_port()
    url = f"http://127.0.0.1:{port}"
    print(f"Movie workspace: {url}")
    if already_running:
        webbrowser.open(url)
        print("Opened the existing movie workspace.")
        return
    print("Keep this window open during your demo. Press Ctrl+C to stop the server.")
    threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run("main:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
