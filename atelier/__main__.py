import argparse
import socket
import threading
import time
import webbrowser
import uvicorn

from .server import create_app


def main():
    parser = argparse.ArgumentParser(description="Lancer l'atelier multi-agents local.")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    try:
        app = create_app()
    except RuntimeError as error:
        print(str(error), flush=True)
        return
    print(f"Atelier : http://127.0.0.1:{args.port}", flush=True)
    if args.open_browser:
        def open_when_ready():
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", args.port), timeout=.2):
                        webbrowser.open(f"http://127.0.0.1:{args.port}")
                        return
                except OSError:
                    time.sleep(.1)
        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
