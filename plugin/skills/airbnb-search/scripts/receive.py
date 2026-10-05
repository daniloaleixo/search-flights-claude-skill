"""Local receiver for harvested data (see step 3 in harvest.js).

    python3 scripts/receive.py <run_dir>/raw      # run in the background

POST /<filename> writes the body to <dir>/<filename>. Binds to 127.0.0.1 only.
"""
import http.server
import os
import sys

OUT = sys.argv[1]
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8765


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        name = os.path.basename(self.path.strip("/")) or "dump.txt"
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(body)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok %d" % n)

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"receiver ready")


http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
