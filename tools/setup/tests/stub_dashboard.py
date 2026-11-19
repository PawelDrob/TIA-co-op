"""Stands in for a dashboard in the tests of the setup window: answers /api/about as the app it is given, with whether it
has a console, and / with a heading. Ends after a minute at most, should a test fail to end it.

    pythonw stub_dashboard.py APP PORT [HEADING]
"""
import ctypes
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

app, port = sys.argv[1], int(sys.argv[2])
heading = sys.argv[3] if len(sys.argv) > 3 else ''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/about' and app:
            body = json.dumps({'app': app, 'clone': 'C:\\stub', 'console': bool(ctypes.windll.kernel32.GetConsoleWindow())})
        elif self.path == '/' and heading:
            body = f'<html><body><h1>{heading}</h1></body></html>'
        else:
            self.send_error(404)
            return
        data = body.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
threading.Timer(60, server.shutdown).start()
server.serve_forever()
