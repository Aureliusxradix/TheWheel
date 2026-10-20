"""A plain static server for the cross-origin test, plus the slow pixel that holds the page's load for the screenshot."""
import sys
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".wasm": "application/wasm", ".js": "text/javascript"}

    def do_GET(self):
        if self.path.startswith("/__wait"):
            time.sleep(8)
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[2])), partial(Handler, directory=sys.argv[1])).serve_forever()
