import argparse
import os
from pathlib import Path
import webbrowser

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Run the private pre-match scanner on localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path, help="Local settings/database directory (default .data)")
    parser.add_argument("--open", action="store_true", help="Open the dashboard in your default browser")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535")
    if args.data_dir:
        os.environ["ARBSCANNER_DATA_DIR"] = str(args.data_dir.resolve())
    from .app import create_app
    if args.open:
        webbrowser.open(f"http://127.0.0.1:{args.port}")
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
