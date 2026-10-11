"""Start OMR Reader: runs a small local server and opens it in your browser."""
import sys
import threading
import time
import webbrowser

from omr.server import create_app, default_data_dir

PORT = 5757


def main():
    app = create_app()
    url = f"http://127.0.0.1:{PORT}"
    print(f"OMR Reader running at {url}")
    print(f"Your data is stored in: {default_data_dir()}")
    print("Close this window to stop the program.")
    threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    try:
        from waitress import serve
        serve(app, host="127.0.0.1", port=PORT, threads=8, max_request_body_size=1024 ** 3)
    except ImportError:
        app.run(host="127.0.0.1", port=PORT, threaded=True)


if __name__ == "__main__":
    sys.exit(main())
