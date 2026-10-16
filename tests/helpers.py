import secrets
import socket
import uuid
from nara.config import initial_state


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def example_state(protocol="vless", tls=None):
    state = initial_state()
    state["settings"]["server_address"] = "127.0.0.1"
    state["inbounds"] = [{"id": "in1", "tag": "proxy-in", "type": protocol, "port": free_port(),
                           "listen": "127.0.0.1", "enabled": True, "transport": "tcp", "tls_id": tls["id"] if tls else ""}]
    state["clients"] = [{"id": "user1", "name": "Test client", "uuid": str(uuid.uuid4()),
                          "password": secrets.token_urlsafe(24), "token": secrets.token_urlsafe(32),
                          "inbound_ids": ["in1"], "quota_bytes": 0, "expires_at": "", "enabled": True}]
    if tls:
        state["tls"] = [tls]
    return state
