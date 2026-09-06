#!/usr/bin/env python3
"""採点用のダミー API。アームからの HTTP 要求を受け、認証ヘッダを記録する。

sealed/ に置く = アームからは書き換えられない (ADR-0020 決定 6)。
"機能が壊れていないか" を実測するための機構であり、コードを読んで判断しない。
"""
import json, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

received = []

class H(BaseHTTPRequestHandler):
    def _record(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0) or 0)
        received.append({
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "goog": self.headers.get("x-goog-api-key"),
            "body_len": len(body),
        })
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')
    do_POST = _record
    do_GET = _record
    def log_message(self, *a): pass

if __name__ == "__main__":
    port = int(sys.argv[1]); out = sys.argv[2]
    srv = HTTPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    # 親から SIGTERM が来るまで待ち、終了時に受信内容を書き出す
    import signal
    def dump(*a):
        json.dump(received, open(out, "w"))
        sys.exit(0)
    signal.signal(signal.SIGTERM, dump)
    signal.signal(signal.SIGINT, dump)
    signal.pause()
