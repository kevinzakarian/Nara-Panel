"""Bound the threads and idle sockets used by both public listeners."""
import threading
import sys
from http.server import ThreadingHTTPServer


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32
    max_connections = 32
    socket_timeout = 15

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(self.max_connections)
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(self.socket_timeout)
        return connection, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            # A saturated listener must return a bounded HTTP error, not empty JSON.
            body = b'{"error":"The panel is busy. Wait a moment and try again."}'
            response = (b'HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\n'
                        b'Connection: close\r\nCache-Control: no-store\r\nRetry-After: 1\r\nContent-Length: '
                        + str(len(body)).encode() + b'\r\n\r\n' + body)
            try:
                request.settimeout(.1)
                request.sendall(response)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, TimeoutError)):
            return  # Client/proxy disconnects are expected; the slot still releases.
        super().handle_error(request, client_address)
