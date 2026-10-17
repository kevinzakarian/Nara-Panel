"""Consumer WARP registration and native user-space WireGuard endpoints.

The consumer registration interface is not a supported public Cloudflare API.
Never retry registration automatically, disable TLS checks, or expose its response.
"""
import base64
import binascii
import datetime
import ipaddress
import json
import subprocess
import uuid
from urllib import error, request

API_URL = 'https://api.cloudflareclient.com/v0a5641/reg'
TERMS_URL = 'https://www.cloudflare.com/application/terms/'
MAX_RESPONSE = 131072


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def decode_key(value, size=32):
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) != size:
            raise ValueError()
        return raw
    except (ValueError, TypeError, binascii.Error):
        raise ValueError('Cloudflare returned an invalid WireGuard key or client ID') from None


def keypair(binary):
    try:
        result = subprocess.run([binary, 'generate', 'wg-keypair'], capture_output=True, text=True, timeout=10)
        values = dict(line.split(':', 1) for line in result.stdout.splitlines() if ':' in line)
        private, public = values.get('PrivateKey', '').strip(), values.get('PublicKey', '').strip()
        if result.returncode or not private or not public:
            raise ValueError()
        decode_key(private)
        decode_key(public)
        return private, public
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ValueError('The installed core could not generate WireGuard keys; install the compatible NARA core') from None


def register(public_key):
    payload = {'key': public_key, 'key_type': 'curve25519', 'tunnel_type': 'wireguard',
               'install_id': '', 'fcm_token': '', 'serial_number': '', 'locale': 'en_US',
               'model': 'NARA', 'os_version': '16.0.0',
               'tos': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}
    req = request.Request(API_URL, data=json.dumps(payload).encode(), method='POST', headers={
        'Content-Type': 'application/json; charset=UTF-8',
        'User-Agent': '1.1.1.1/6.38.9-5641 (Android 16.0.0)', 'CF-Client-Version': 'a-6.38.9-5641'})
    try:
        # No environment proxy or redirects: only send the public key to this fixed TLS host.
        with request.build_opener(request.ProxyHandler({}), NoRedirect()).open(req, timeout=20) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if response.status not in (200, 201) or len(raw) > MAX_RESPONSE:
                raise ValueError('Cloudflare returned an unexpected registration response')
            return json.loads(raw)
    except error.HTTPError as exc:
        code = exc.code
        exc.close()
        if code == 429:
            raise ValueError('Cloudflare rate-limited registration. Wait before trying again, or import an existing WireGuard endpoint.') from None
        raise ValueError('Cloudflare rejected WARP registration (HTTP %s). Its consumer API may restrict this server; import an existing WireGuard endpoint in Core features.' % code) from None
    except (error.URLError, OSError):
        raise ValueError('Could not reach Cloudflare WARP registration. Check this server’s outbound HTTPS access and try again.') from None
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError('Cloudflare returned an invalid registration response') from None


def endpoint(response, private_key):
    try:
        if response.get('tunnel_type', 'wireguard') != 'wireguard':
            raise ValueError()
        config = response['config']
        addresses = config['interface']['addresses']
        local = []
        for name, version in (('v4', 4), ('v6', 6)):
            if not addresses.get(name):
                continue
            address = ipaddress.ip_address(addresses[name])
            if address.version != version or address.is_unspecified or address.is_multicast or address.is_loopback:
                raise ValueError()
            local.append(str(address) + ('/32' if version == 4 else '/128'))
        if not local:
            raise ValueError()
        peer = config['peers'][0]
        decode_key(peer['public_key'])
        reserved = list(decode_key(config['client_id'], 3))
        remote = peer['endpoint']
        # Prefer an API-provided literal IPv4 to avoid hostname bootstrap cycles.
        value = remote.get('v4') or remote.get('v6')
        ports = remote.get('ports') or [2408]
        if not isinstance(ports, list) or type(ports[0]) is not int:
            raise ValueError()
        port = ports[0]
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            from urllib.parse import urlsplit
            parsed = urlsplit('//'+value)
            address = ipaddress.ip_address(parsed.hostname)
            port = parsed.port or port
        if not address.is_global or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError()
        return {'type': 'wireguard', 'system': False, 'mtu': 1280, 'address': local,
                'private_key': private_key, 'peers': [{'address': str(address), 'port': int(port),
                'public_key': peer['public_key'], 'allowed_ips': ['0.0.0.0/0', '::/0'],
                'persistent_keepalive_interval': 25, 'reserved': reserved}]}
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        raise ValueError('Cloudflare did not return a usable WireGuard configuration. Existing settings were kept.') from None


def create(binary):
    private, public = keypair(binary)
    return endpoint(register(public), private)


def record(config, state):
    tags = {'direct'} | {row.get('config', {}).get('tag', row.get('tag'))
                         for name in ('outbounds', 'endpoints', 'inbounds') for row in state[name]}
    tag, number = 'warp', 1
    while tag in tags:
        number += 1
        tag = 'warp-' + str(number)
    config = {**config, 'tag': tag}
    return {'id': uuid.uuid4().hex, 'mode': 'native', 'enabled': True, 'label': 'Cloudflare WARP',
            'provider': 'cloudflare-warp', 'type': 'wireguard', 'tag': tag, 'config': config}
