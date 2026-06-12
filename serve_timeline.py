#!/usr/bin/env python3
"""Serve the local economic timeline web page without requiring npm.

This script is intentionally dependency-free so the timeline can be opened even
when Node.js/npm is unavailable or when `npm run ...` fails in a local checkout.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path


DEFAULT_PORT = 8000
TIMELINE_DIR = Path(__file__).resolve().parent / "public" / "economic-timeline"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the economic timeline static web app.")
    parser.add_argument("--host", default="127.0.0.1", help="Host/interface to bind. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to bind. Default: {DEFAULT_PORT}")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    parser.add_argument("--check", action="store_true", help="Validate required files and exit without starting a server.")
    return parser


def validate_timeline_dir() -> None:
    required_files = ["index.html", "styles.css", "app.js", "app-data.js"]
    missing = [name for name in required_files if not (TIMELINE_DIR / name).is_file()]
    if missing:
        missing_list = ", ".join(missing)
        raise FileNotFoundError(f"Missing timeline files in {TIMELINE_DIR}: {missing_list}")


def serve(host: str, port: int, open_browser: bool) -> None:
    validate_timeline_dir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(TIMELINE_DIR))
    socketserver.TCPServer.allow_reuse_address = True

    with socketserver.TCPServer((host, port), handler) as httpd:
        url = f"http://{host}:{port}/"
        print(f"경제·투자 이벤트 타임라인을 실행합니다: {url}")
        print("종료하려면 Ctrl+C를 누르세요.")
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n서버를 종료합니다.")


def main() -> int:
    args = build_parser().parse_args()
    try:
        validate_timeline_dir()
    except FileNotFoundError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    if args.check:
        print(f"OK: timeline files found in {TIMELINE_DIR}")
        return 0

    serve(args.host, args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
