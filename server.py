#!/usr/bin/env python3
"""
DFR Dashboard — Intranet Web Server

Usage:
    py server.py                  # serve on port 8080
    py server.py --port 9000      # custom port
    py server.py --watch          # auto-regenerate when CSV changes (polls every 30s)
    py server.py --watch --interval 60  # check every 60s

Endpoints:
    /          → serves DFR_Dashboard_2026.html
    /refresh   → re-runs update_dashboard.py then redirects to /
    /health    → returns 200 OK (for uptime checks)

The server binds to 0.0.0.0 so it is reachable by any device on the same
local network. Windows Firewall will prompt the first time — allow access
on Private networks only to keep it intranet-only.
"""

import argparse
import http.server
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
HTML_FILE  = SCRIPT_DIR / 'DFR_Dashboard_2026.html'
CSV_FILE   = SCRIPT_DIR / 'DFRF2026YTD.csv'
UPDATE_PY  = SCRIPT_DIR / 'update_dashboard.py'

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def run_update(csv_path: Path | None = None) -> tuple[bool, str]:
    """Run update_dashboard.py and return (success, message)."""
    cmd = [sys.executable, str(UPDATE_PY)]
    if csv_path:
        cmd += ['--csv', str(csv_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPT_DIR), timeout=60)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, 'Update script timed out after 60s'
    except Exception as e:
        return False, str(e)

# ── HTTP handler ──────────────────────────────────────────────────────────────

class DFRHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        path = self.path.split('?')[0].rstrip('/')

        if path in ('', '/'):
            self._serve_html()
        elif path == '/refresh':
            self._handle_refresh()
        elif path == '/health':
            self._send_text(200, 'OK')
        else:
            self._send_text(404, '404 Not Found')

    # ── Route handlers ───────────────────────────────────────────────────────

    def _serve_html(self):
        if not HTML_FILE.exists():
            # Auto-generate if HTML missing
            ok, msg = run_update()
            if not ok:
                self._send_text(500, f'Dashboard HTML not found and auto-generation failed:\n{msg}')
                return

        try:
            data = HTML_FILE.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_text(500, f'Error reading dashboard: {e}')

    def _handle_refresh(self):
        ok, msg = run_update()
        if ok:
            # Redirect back to dashboard
            self.send_response(302)
            self.send_header('Location', '/')
            self.end_headers()
            print(f'[refresh] Dashboard regenerated OK')
        else:
            self._send_text(500,
                f'<h2>Update failed</h2><pre>{msg}</pre>'
                '<p><a href="/">Back to dashboard</a></p>',
                content_type='text/html; charset=utf-8')
            print(f'[refresh] Update failed: {msg}')

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _send_text(self, code: int, body: str, content_type: str = 'text/plain; charset=utf-8'):
        data = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f'  [{self.address_string()}] {fmt % args}')

# ── CSV watcher ───────────────────────────────────────────────────────────────

def csv_watcher(interval: int):
    """Background thread: polls CSV mtime and regenerates on change."""
    last_mtime = CSV_FILE.stat().st_mtime if CSV_FILE.exists() else 0
    while True:
        time.sleep(interval)
        try:
            mtime = CSV_FILE.stat().st_mtime
            if mtime != last_mtime:
                last_mtime = mtime
                print(f'\n[watcher] {CSV_FILE.name} changed — regenerating dashboard…')
                ok, msg = run_update()
                if ok:
                    print(f'[watcher] Dashboard updated successfully.')
                else:
                    print(f'[watcher] Update failed: {msg}')
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f'[watcher] Error: {e}')

# ── Banner ────────────────────────────────────────────────────────────────────

def print_banner(ip: str, port: int, watch: bool, interval: int = 30):
    lines = [
        'DFR Dashboard Server',
        '',
        f'Local:    http://localhost:{port}',
        f'Network:  http://{ip}:{port}',
        f'Refresh:  http://{ip}:{port}/refresh',
        f'Health:   http://{ip}:{port}/health',
        '',
        f'Serving:  {HTML_FILE.name}',
    ]
    if watch:
        lines.append(f'Watching: {CSV_FILE.name} for changes (every {interval}s)')
    lines += ['', 'Press Ctrl+C to stop']

    w = max(len(l) for l in lines) + 6
    sep = '+' + '-' * (w - 2) + '+'
    print(sep)
    for l in lines:
        print(f'|  {l:<{w-4}}|')
    print(sep)
    print()

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='DFR Dashboard intranet server.')
    parser.add_argument('--port',     type=int, default=8080,  help='Port to listen on (default: 8080)')
    parser.add_argument('--watch',    action='store_true',      help='Watch CSV for changes and auto-regenerate')
    parser.add_argument('--interval', type=int, default=30,     help='Watch poll interval in seconds (default: 30)')
    args = parser.parse_args()

    local_ip = get_local_ip()

    # If dashboard HTML doesn't exist yet, generate it now
    if not HTML_FILE.exists():
        print('Dashboard HTML not found — running update_dashboard.py first…')
        ok, msg = run_update()
        if ok:
            print('Dashboard generated.\n')
        else:
            print(f'WARNING: Could not generate dashboard: {msg}\n'
                  f'The server will start anyway; visit /refresh to retry.\n')

    if args.watch:
        watcher = threading.Thread(target=csv_watcher, args=(args.interval,), daemon=True)
        watcher.start()

    print_banner(local_ip, args.port, args.watch, args.interval)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('0.0.0.0', args.port), DFRHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\nServer stopped.')


if __name__ == '__main__':
    main()
