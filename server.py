from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Qubit OK")
    def log_message(self, *args):
        pass

def start():
    port = int(__import__("os").environ.get("PORT", 8080))
    threading.Thread(
        target=lambda: HTTPServer(("0.0.0.0", port), Health).serve_forever(),
        daemon=True,
    ).start()