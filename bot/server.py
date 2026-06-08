from http.server import HTTPServer, BaseHTTPRequestHandler
import threading, os

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Qubit OK")
    def log_message(self, *args):
        pass

def start():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Health)
    print(f"Health server on port {port}")  # ← helps Render detect it
    threading.Thread(target=server.serve_forever, daemon=True).start()