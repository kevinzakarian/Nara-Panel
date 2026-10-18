"""Loopback integration tests. Never changes routes, firewall, or host DNS."""
import copy
import http.client
import json
import os
import socket
import socketserver
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from nara.config import CLIENT_DNS_ADDRESS, build_config, client_config
from nara.runtime import Runtime, atomic_write
from nara.server import self_signed
from nara.store import Store
from tests.helpers import example_state, free_port

CORE = os.environ.get("SING_BOX_TEST_BINARY")


def diagnostic_categories(text):
    # Only fixed labels and counts may reach public CI output. Never emit log
    # lines, peer names, file contents, credentials, or configuration values.
    text = text.lower()
    labels = ('network is unreachable','connection refused','operation not permitted',
              'invalid argument','timeout','deadline exceeded','certificate','handshake',
              'no such host','no route','gso','obfs','dns','read udp','write udp','dial tcp','sendmsg',
              'inbound','outbound','exchange','response','query','cached','rejected','hijack',
              'eof','error','reset','stream','closed','cancel','not found','failed to','started',
              'invalid','unexpected','unpack','buffer','overflow','short','malformed','length',
              'header','protocol','message','empty','resource','permission','denied','splice',
              'tls','http','unknown','broken pipe','body','status','too many','compression')
    return {label:text.count(label) for label in labels if label in text}


class Target(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(self):
        payload = b"NARA traffic accounting test.\n" * 2048
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def dns_answer(query):
    """Answer fixture names locally; tests never need public DNS or Internet."""
    end = 12
    while query[end]:
        end += query[end] + 1
    end += 5
    qtype = struct.unpack("!H", query[end-4:end-2])[0]
    answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + socket.inet_aton("127.0.0.1") if qtype == 1 else b""
    return query[:2] + struct.pack("!HHHHH", 0x8180, 1, bool(answer), 0, 0) + query[12:end] + answer


class BootstrapDNS(socketserver.BaseRequestHandler):
    requests = 0
    def handle(self):
        BootstrapDNS.requests += 1
        query, sock = self.request
        sock.sendto(dns_answer(query), self.client_address)


class RemoteDNS(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    queries = []

    def do_POST(self):
        query = self.rfile.read(int(self.headers["Content-Length"]))
        self.queries.append(query)
        answer = dns_answer(query)
        self.send_response(200)
        self.send_header("Content-Type", "application/dns-message")
        self.send_header("Content-Length", str(len(answer)))
        self.end_headers()
        self.wfile.write(answer)

    def log_message(self, *args):
        pass


@unittest.skipUnless(CORE, "Set SING_BOX_TEST_BINARY for real-core integration tests")
class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = self_signed({"server_name": "127.0.0.1", "days": 1})
        cls.target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
        threading.Thread(target=cls.target.serve_forever, daemon=True).start()
        cls.dns_temp = tempfile.TemporaryDirectory()
        cert, key = Path(cls.dns_temp.name)/"cert.pem", Path(cls.dns_temp.name)/"key.pem"
        atomic_write(cert, cls.profile["certificate"])
        atomic_write(key, cls.profile["private_key"])
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        cls.remote_dns = ThreadingHTTPServer(("127.0.0.1", 0), RemoteDNS)
        cls.remote_dns.socket = tls.wrap_socket(cls.remote_dns.socket, server_side=True)
        cls.bootstrap_dns = socketserver.ThreadingUDPServer(("127.0.0.1", 0), BootstrapDNS)
        for server in (cls.remote_dns, cls.bootstrap_dns):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.target.shutdown()
        cls.target.server_close()
        for server in (cls.remote_dns, cls.bootstrap_dns):
            server.shutdown()
            server.server_close()
        cls.dns_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.runtime = Runtime(self.store, CORE, free_port())

    def tearDown(self):
        self.runtime.shutdown.set()
        with self.runtime.lock:
            self.runtime.stop()
        if os.environ.get('NARA_TEST_DIAGNOSTICS') == '1':
            result = getattr(self._outcome, 'result', None)
            failures = getattr(result, 'errors', []) + getattr(result, 'failures', [])
            if any(case.id().startswith(self.id()) for case, _ in failures):
                server = Path(self.temp.name)/'core.log'
                text = server.read_text(errors='replace') if server.exists() else ''
                clients = ''.join(path.read_text(errors='replace') for path in Path(self.temp.name).glob('*client.log'))
                print('Fixture error categories: '+json.dumps({'server':diagnostic_categories(text),'client':diagnostic_categories(clients)}))
        self.temp.cleanup()

    def local_client(self, state, fixture_dns=True):
        config = client_config(state, state["clients"][0], {})
        # Exercise the proxy without creating a VPN or changing host routes.
        config["inbounds"] = [i for i in config["inbounds"] if i["type"] != "tun"]
        # The fixture has no TUN or routing changes. Do not bind its local DNS
        # bootstrap to the host's external default interface on Linux.
        config["route"]["auto_detect_interface"] = False
        if os.environ.get('NARA_TEST_DIAGNOSTICS') == '1':
            config['log']['level'] = 'debug'
        port = free_port()
        config["inbounds"][0]["listen_port"] = port
        config["experimental"]["cache_file"]["path"] = str(Path(self.temp.name)/"client-cache.db")
        # Transport tests intentionally exercise proxy traffic even to loopback.
        config["experimental"]["clash_api"]["default_mode"] = "Global"
        config["dns"]["servers"][0] = {"type":"udp", "tag":"bootstrap", "server":"127.0.0.1",
                                          "server_port":self.bootstrap_dns.server_address[1]}
        if fixture_dns:
            config["dns"]["servers"][1] = {"type":"https", "tag":"remote", "server":"127.0.0.1",
                "server_port":self.remote_dns.server_port, "path":"/dns-query", "detour":config["route"]["final"],
                "tls":{"enabled":True, "server_name":"127.0.0.1", "certificate":[self.profile["certificate"]]}}
        return port, config

    def transfer(self, state, outbound=None):
        if outbound:
            port = free_port()
            config = {"log": {"level": "warn"}, "inbounds": [{"type": "mixed", "listen": "127.0.0.1", "listen_port": port}],
                      "outbounds": [outbound], "route": {"final": outbound["tag"]}}
        else:
            port, config = self.local_client(state)
        if os.environ.get('NARA_TEST_DIAGNOSTICS') == '1':
            config['log']['level'] = 'debug'
        path = Path(self.temp.name) / "client.json"
        atomic_write(path, json.dumps(config))
        with open(path.with_suffix('.client.log'), 'w') as client_log:
            process = subprocess.Popen([CORE, "run", "-c", str(path)], stdout=client_log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 8
            while True:
                try:
                    sock = socket.create_connection(("127.0.0.1", port), timeout=1)
                    break
                except OSError:
                    if time.monotonic() > deadline or process.poll() is not None:
                        self.fail("Client core did not start")
                    time.sleep(.1)
            with sock:
                sock.settimeout(8)
                request = "GET http://127.0.0.1:{}/ HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: keep-alive\r\n\r\n".format(self.target.server_port, self.target.server_port)
                sock.sendall(request.encode())
                # HTTP response framing defines completion. Waiting for a
                # tunnel EOF after Content-Length can stall legacy QUIC streams.
                response = http.client.HTTPResponse(sock)
                response.begin()
                self.assertEqual(response.status, 200)
                chunks = []
                try:
                    while chunk := response.read1(65536):
                        chunks.append(chunk)
                except TimeoutError:
                    self.fail("HTTP body stalled after " + str(sum(map(len, chunks))) + " bytes")
                data = b"".join(chunks)
                self.assertEqual(len(data), len(b"NARA traffic accounting test.\n") * 2048)
            self.assertIn(b"NARA traffic accounting test.", data)
        finally:
            process.terminate()
            process.wait(timeout=5)
        time.sleep(.2)
        self.runtime.collect()

    def test_complete_vpn_profiles_pass_core_check(self):
        for protocol in ("vless", "vmess", "trojan", "hysteria2", "tuic", "anytls"):
            with self.subTest(protocol=protocol):
                state = example_state(protocol, self.profile)
                path = Path(self.temp.name)/"vpn-check.json"
                atomic_write(path, json.dumps(client_config(state, state["clients"][0], {})))
                checked = subprocess.run([CORE, "check", "-c", str(path)], capture_output=True, text=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_hysteria2_salamander_client_hijacks_dns_through_proxy(self):
        state = example_state("hysteria2", self.profile)
        state["settings"]["block_private"] = False
        state["settings"]["server_address"] = "node.nara.test"
        if os.environ.get('NARA_TEST_DIAGNOSTICS') == '1':
            state['core_options']['log'] = {'level':'debug'}
        state["inbounds"][0]["server_options"] = {"obfs": {"type": "salamander", "password": "fixture-obfs"}}
        self.runtime.apply(state)
        port, config = self.local_client(state)
        path = Path(self.temp.name)/"dns-client.json"
        atomic_write(path, json.dumps(config))
        with open(path.with_suffix('.client.log'), 'w') as client_log:
            process = subprocess.Popen([CORE, "run", "-c", str(path)], stdout=client_log, stderr=subprocess.STDOUT)
        query = b"\x12\x34" + struct.pack("!HHHHH", 0x100, 1, 0, 0, 0) + b"\x03vpn\x04nara\x04test\x00" + struct.pack("!HH", 1, 1)
        before = len(RemoteDNS.queries)
        bootstrap_before = BootstrapDNS.requests
        try:
            deadline = time.monotonic()+8
            while True:
                try:
                    sock = socket.create_connection(("127.0.0.1", port), timeout=1)
                    break
                except OSError:
                    if time.monotonic()>deadline or process.poll() is not None:
                        self.fail("Client core did not start")
                    time.sleep(.1)
            with sock:
                sock.settimeout(15)
                sock.sendall(b"\x05\x01\x00")
                self.assertEqual(sock.recv(2), b"\x05\x00")
                sock.sendall(b"\x05\x01\x00\x01"+socket.inet_aton("1.1.1.1")+struct.pack("!H", 53))
                reply = sock.makefile("rb")
                self.assertEqual(reply.read(10)[:2], b"\x05\x00")
                sock.sendall(struct.pack("!H", len(query))+query)
                prefix = reply.read(2)
                self.assertEqual(len(prefix), 2, "DNS exchange closed before its response; bootstrap queries=" + str(BootstrapDNS.requests-bootstrap_before) + "; DoH queries=" + str(len(RemoteDNS.queries)-before))
                length = struct.unpack("!H", prefix)[0]
                answer = reply.read(length)
                self.assertEqual(answer[:2], query[:2])
                self.assertEqual(answer[-4:], socket.inet_aton("127.0.0.1"))
                reply.close()
            self.assertGreater(len(RemoteDNS.queries), before)
            time.sleep(.2)
            self.runtime.collect()
            self.assertGreater(self.store.totals()["user1"]["upload"], 0)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def start_client(self, config):
        path = Path(self.temp.name)/"mode-client.json"
        atomic_write(path, json.dumps(config))
        log = path.with_suffix('.client.log').open('w')
        process = subprocess.Popen([CORE, 'run', '-c', str(path)], stdout=log, stderr=subprocess.STDOUT)
        self.addCleanup(log.close)
        self.addCleanup(lambda: process.wait(timeout=5))
        self.addCleanup(process.terminate)
        ports = [config['inbounds'][0]['listen_port']]
        controller = config.get('experimental',{}).get('clash_api',{}).get('external_controller')
        if controller:
            ports.append(int(controller.rsplit(':',1)[1]))
        deadline = time.monotonic()+8
        while True:
            try:
                for port in ports:
                    with socket.create_connection(('127.0.0.1',port),.2):
                        pass
                return process
            except OSError:
                if process.poll() is not None or time.monotonic()>deadline:
                    self.fail('Client core did not start')
                time.sleep(.05)

    def query_client_dns(self, port, name):
        query = b'\x21\x43'+struct.pack('!HHHHH',0x100,1,0,0,0)+b''.join(bytes([len(part)])+part.encode() for part in name.split('.'))+b'\x00'+struct.pack('!HH',1,1)
        with socket.create_connection(('127.0.0.1',port),2) as sock:
            sock.settimeout(10)
            sock.sendall(b'\x05\x01\x00')
            self.assertEqual(sock.recv(2),b'\x05\x00')
            sock.sendall(b'\x05\x01\x00\x01'+socket.inet_aton(CLIENT_DNS_ADDRESS)+struct.pack('!H',53))
            stream = sock.makefile('rb')
            self.assertEqual(stream.read(10)[:2],b'\x05\x00')
            sock.sendall(struct.pack('!H',len(query))+query)
            try:
                prefix = stream.read(2)
                self.assertEqual(len(prefix),2,'DNS bridge closed without a response')
                answer = stream.read(struct.unpack('!H',prefix)[0])
            finally:
                stream.close()
            self.assertEqual(answer[:2],query[:2])
            self.assertEqual(answer[3]&15,0)
            return answer

    def test_client_dns_tracks_server_default_and_rules_without_reimport(self):
        state = example_state('hysteria2',self.profile)
        state['dns_servers'] = [
            {'id':'a','tag':'a','mode':'native','config':{'type':'udp','tag':'a','server':'127.0.0.1','server_port':self.bootstrap_dns.server_address[1]}},
            {'id':'b','tag':'b','mode':'native','config':{'type':'hosts','tag':'b','predefined':{'second.nara.test':['192.0.2.53'],'policy.nara.test':['192.0.2.54']}}}]
        state['settings']['dns_final'] = 'a'
        # Default private-network blocking stays ON throughout the bridge test.
        self.runtime.apply(state)
        port,config = self.local_client(state,fixture_dns=False)
        client = self.start_client(config)
        before = BootstrapDNS.requests
        self.assertEqual(self.query_client_dns(port,'first.nara.test')[-4:],socket.inet_aton('127.0.0.1'))
        self.assertGreater(BootstrapDNS.requests,before)
        state['settings']['dns_final'] = 'b'
        self.runtime.apply(state)
        # Applying server settings restarts the core. Reconnect the same profile
        # instead of depending on a stale pooled QUIC session's idle timeout.
        client.terminate();client.wait(timeout=5)
        client = self.start_client(config)
        before = BootstrapDNS.requests
        # Same exported profile, a fresh uncached name, and the new resolver.
        self.assertEqual(self.query_client_dns(port,'second.nara.test')[-4:],socket.inet_aton('192.0.2.53'))
        self.assertEqual(BootstrapDNS.requests,before)
        state['dns_rules'] = [{'id':'policy','mode':'native','config':{'domain':['policy.nara.test'],'action':'route','server':'a'}}]
        self.runtime.apply(state)
        client.terminate();client.wait(timeout=5)
        self.start_client(config)
        self.assertEqual(self.query_client_dns(port,'policy.nara.test')[-4:],socket.inet_aton('127.0.0.1'))
        self.assertGreater(BootstrapDNS.requests,before)

    def test_dns_rule_account_and_inbound_metadata_survive_managed_dns_hijack(self):
        from nara.clients import new_client
        state=example_state('hysteria2',self.profile)
        second=new_client({'name':'Second account','inbound_ids':['in1']})
        state['clients'].append(second)
        names=['account-one.nara.test','account-two.nara.test']
        state['dns_servers']=[{'id':key,'tag':key,'mode':'native','config':{'type':'hosts','tag':key,'predefined':{name:[address] for name in names}}} for key,address in [('selected','192.0.2.11'),('fallback','192.0.2.22')]]
        state['settings']['dns_final']='fallback'
        state['dns_rules']=[{'id':'account-policy','mode':'native','config':{'auth_user':['client-user1'],'inbound':['proxy-in'],'query_type':['A'],'domain_suffix':['nara.test'],'action':'route','server':'selected'}}]
        self.runtime.apply(state)
        for index,address in [(0,'192.0.2.11'),(1,'192.0.2.22')]:
            profile=copy.deepcopy(state);profile['clients']=[state['clients'][index]]
            port,config=self.local_client(profile,fixture_dns=False)
            process=self.start_client(config)
            self.assertEqual(self.query_client_dns(port,names[index])[-4:],socket.inet_aton(address))
            process.terminate();process.wait(timeout=5)

    def test_multiple_inbounds_and_clients_route_through_selected_gateway_and_dns(self):
        from nara import stats
        from nara.clients import new_client
        gateway_port,gateway_stats=free_port(),free_port()
        gateway=self.start_client({'log':{'level':'warn'},'inbounds':[{'type':'mixed','tag':'gateway','listen':'127.0.0.1','listen_port':gateway_port}],
            'outbounds':[{'type':'direct','tag':'direct'}],'route':{'final':'direct'},
            'experimental':{'v2ray_api':{'listen':'127.0.0.1:'+str(gateway_stats),'stats':{'enabled':True,'inbounds':['gateway']}}}})
        state=example_state('vless',self.profile);state['settings']['block_private']=False
        second=copy.deepcopy(state['inbounds'][0]);second.update(id='in2',tag='second-in',port=free_port());state['inbounds'].append(second)
        state['clients'][0]['inbound_ids']=['in1','in2']
        state['clients'] += [new_client({'name':name,'inbound_ids':['in1','in2']}) for name in ('Selected second','Unselected third')]
        selected=['client-'+client['id'] for client in state['clients'][:2]]
        state['outbounds']=[{'id':'gateway','mode':'native','tag':'alternate','config':{'type':'socks','tag':'alternate','server':'127.0.0.1','server_port':gateway_port,'version':'5'}}]
        state['route_rules']=[{'id':'source-route','mode':'native','config':{'inbound':['proxy-in','second-in'],'auth_user':selected,'action':'route','outbound':'alternate'}}]
        names=['source-'+str(index)+'.nara.test' for index in range(4)]
        state['dns_servers']=[{'id':key,'mode':'native','tag':key,'config':{'type':'hosts','tag':key,'predefined':{name:[ip] for name in names}}} for key,ip in [('selected','192.0.2.11'),('fallback','192.0.2.22')]]
        state['settings']['dns_final']='fallback'
        state['dns_rules']=[{'id':'source-dns','mode':'native','config':{'inbound':['proxy-in','second-in'],'auth_user':selected,'action':'route','server':'selected'}}]
        self.runtime.apply(state)
        for index,(client_index,inbound_index) in enumerate(((0,0),(0,1),(1,1),(2,0))):
            profile=copy.deepcopy(state);profile['clients']=[state['clients'][client_index]]
            if inbound_index:profile['inbounds'].reverse()
            before=sum(stats.query(gateway_stats).values())
            port,config=self.local_client(profile,fixture_dns=False);process=self.start_client(config)
            expected='192.0.2.11' if client_index<2 else '192.0.2.22'
            self.assertEqual(self.query_client_dns(port,names[index])[-4:],socket.inet_aton(expected))
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=8)
            try:
                connection.request('GET','http://127.0.0.1:'+str(self.target.server_port)+'/')
                response=connection.getresponse();self.assertEqual(response.status,200);self.assertIn(b'NARA traffic accounting test.',response.read())
            finally:connection.close();process.terminate();process.wait(timeout=5)
            after=sum(stats.query(gateway_stats).values())
            if client_index<2:self.assertGreater(after,before)
            else:self.assertEqual(after,before)
        self.assertIsNone(gateway.poll())

    def test_traffic_rule_matches_authenticated_account_independently_of_display_name(self):
        from nara.clients import new_client
        state=example_state('vless',self.profile);state['settings']['block_private']=False
        state['clients'][0]['name']='Renamed account'
        state['clients'].append(new_client({'name':'Other account','inbound_ids':['in1']}))
        state['route_rules']=[{'id':'account-policy','mode':'native','config':{'inbound':['proxy-in'],'auth_user':['client-user1'],'port':[self.target.server_port],'source_ip_cidr':['127.0.0.1/32'],'network':['tcp'],'action':'reject'}}]
        self.runtime.apply(state)
        port,config=self.local_client(state);process=self.start_client(config)
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        try:
            connection.request('GET','http://127.0.0.1:'+str(self.target.server_port)+'/')
            response=connection.getresponse();self.assertNotEqual(response.status,200)
        except (OSError,http.client.HTTPException):pass
        finally:connection.close();process.terminate();process.wait(timeout=5)
        profile=copy.deepcopy(state);profile['clients'].reverse();self.transfer(profile)

    def test_quota_removal_keeps_scoped_rules_inert_and_other_inbounds_running(self):
        from nara.clients import new_client
        state=example_state('vless',self.profile);state['settings']['block_private']=False
        state['clients'][0]['quota_bytes']=1
        second=copy.deepcopy(state['inbounds'][0]);second.update(id='in2',tag='second-in',port=free_port());state['inbounds'].append(second)
        state['clients'].append(new_client({'name':'Unaffected account','inbound_ids':['in2']}))
        state['route_rules']=[{'id':'policy','mode':'native','config':{'inbound':['proxy-in'],'auth_user':['client-user1'],'domain_suffix':['blocked.example'],'action':'reject'}}]
        state['dns_rules']=[{'id':'dns-policy','mode':'native','config':{'inbound':['proxy-in'],'auth_user':['client-user1'],'domain_suffix':['blocked.example'],'action':'reject'}}]
        self.runtime.apply(state);self.store.add_traffic([('user1','upload',1)])
        self.runtime.apply(state)
        self.assertTrue(self.runtime.running)
        active=build_config(state,self.store.totals(),self.runtime.run_dir,self.runtime.stats_port)
        self.assertEqual([row['tag'] for row in active['inbounds']],['second-in'])
        profile=copy.deepcopy(state);profile['clients']=[state['clients'][1]];self.transfer(profile)

    def test_managed_dns_bridge_works_for_every_account_protocol(self):
        for protocol in ('vless','vmess','trojan','hysteria2','tuic','anytls'):
            with self.subTest(protocol=protocol):
                state = example_state(protocol,self.profile)
                state['dns_servers'][0].update(server='127.0.0.1',port=self.bootstrap_dns.server_address[1])
                self.runtime.apply(state)
                port,config = self.local_client(state,fixture_dns=False)
                process = self.start_client(config)
                try:
                    self.assertEqual(self.query_client_dns(port,protocol+'.nara.test')[-4:],socket.inet_aton('127.0.0.1'))
                finally:
                    process.terminate();process.wait(timeout=5)
                self.runtime.stop()

    def test_authenticated_live_presence_and_private_api_authentication(self):
        from nara import presence
        import grpc
        state = example_state('vless', self.profile)
        state['settings']['block_private'] = False
        self.runtime.apply(state)
        port, config = self.local_client(state)
        client = self.start_client(config)
        release, received = threading.Event(), threading.Event()
        target = socket.socket()
        target.bind(('127.0.0.1', 0));target.listen(1);target.settimeout(5)
        def hold():
            try:
                peer, _ = target.accept()
                with peer:
                    peer.settimeout(5)
                    if peer.recv(32):received.set()
                    release.wait(5)
            except OSError:
                pass
        worker = threading.Thread(target=hold, daemon=True);worker.start()
        try:
            with socket.create_connection(('127.0.0.1', port), 3) as connection:
                connection.settimeout(5)
                address = '127.0.0.1:' + str(target.getsockname()[1])
                connection.sendall(('CONNECT '+address+' HTTP/1.1\r\nHost: '+address+'\r\n\r\n').encode())
                self.assertIn(b'200', connection.recv(4096))
                connection.sendall(b'presence-probe')
                self.assertTrue(received.wait(3))
                self.assertGreaterEqual(presence.query(self.runtime.presence_port, self.runtime.presence_secret).get('user1', 0), 1)
                self.runtime.collect_presence()
                snapshot = self.runtime.presence_status()
                self.assertTrue(snapshot['available'])
                self.assertGreaterEqual(snapshot['counts'].get('user1', 0), 1)
                with self.assertRaises(grpc.RpcError):
                    presence.query(self.runtime.presence_port, 'invalid-test-secret')
            release.set()
            for _ in range(20):
                self.runtime.collect_presence()
                if not self.runtime.presence_counts.get('user1'):break
                time.sleep(.1)
            self.assertEqual(self.runtime.presence_counts.get('user1', 0), 0)
            self.runtime.stop()
            self.assertFalse(self.runtime.presence_status()['counts'])
        finally:
            release.set();target.close();worker.join(timeout=2)
            client.terminate();client.wait(timeout=5)

    def test_client_modes_change_traffic_path_and_preserve_selection(self):
        state = example_state('hysteria2',self.profile)
        state['settings']['block_private'] = False
        state['inbounds'].append({**state['inbounds'][0],'id':'backup','tag':'backup','port':free_port()})
        state['clients'][0]['inbound_ids'].append('backup')
        self.runtime.apply(state)
        port,config = self.local_client(state)
        config['experimental']['clash_api']['default_mode'] = 'Rule'
        controller = free_port()
        config['experimental']['clash_api']['external_controller'] = '127.0.0.1:'+str(controller)
        client = self.start_client(config)
        def api(method,path,body=None):
            connection = http.client.HTTPConnection('127.0.0.1',controller,timeout=5)
            connection.request(method,path,json.dumps(body) if body else None,{'Content-Type':'application/json'})
            response = connection.getresponse()
            status,data = response.status,response.read()
            connection.close()
            self.assertIn(status,(200,204))
            return json.loads(data) if data else None
        def transfer():
            with socket.create_connection(('127.0.0.1',port),2) as sock:
                sock.settimeout(8)
                sock.sendall(('GET http://127.0.0.1:%d/ HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n'%self.target.server_port).encode())
                response = http.client.HTTPResponse(sock)
                response.begin()
                self.assertEqual(response.status,200)
                self.assertEqual(len(response.read()),len(b'NARA traffic accounting test.\n')*2048)
            time.sleep(.2)
            self.runtime.collect()
            return sum(self.store.totals().get('user1',{}).values())
        self.assertEqual(api('GET','/configs')['mode'],'Rule')
        self.assertEqual(api('GET','/proxies/'+config['route']['final'])['type'],'Selector')
        # LAN addresses bypass in Rule, proxy in Global, and bypass in Direct.
        self.assertEqual(transfer(),0)
        api('PUT','/proxies/'+config['route']['final'],{'name':'backup'})
        self.assertEqual(api('GET','/proxies/'+config['route']['final'])['now'],'backup')
        api('PATCH','/configs',{'mode':'Global'})
        proxied = transfer()
        self.assertGreater(proxied,1000)
        api('PATCH','/configs',{'mode':'Direct'})
        self.assertEqual(transfer(),proxied)
        self.assertEqual(api('GET','/configs')['mode'],'Direct')
        remote_before,bootstrap_before = len(RemoteDNS.queries),BootstrapDNS.requests
        self.assertEqual(self.query_client_dns(port,'direct.nara.test')[-4:],socket.inet_aton('127.0.0.1'))
        self.assertEqual(len(RemoteDNS.queries),remote_before)
        self.assertGreater(BootstrapDNS.requests,bootstrap_before)
        client.terminate();client.wait(timeout=5)
        self.start_client(config)
        self.assertEqual(api('GET','/configs')['mode'],'Direct')
        self.assertEqual(api('GET','/proxies/'+config['route']['final'])['now'],'backup')

    def test_all_protocols_transfer_and_account(self):
        for protocol in ("vless", "vmess", "trojan", "hysteria2", "tuic", "anytls"):
            with self.subTest(protocol=protocol):
                state = example_state(protocol, self.profile)
                state["settings"]["block_private"] = False
                self.runtime.apply(state)
                before = self.store.totals().get("user1", {}).get("download", 0)
                self.transfer(state)
                self.assertGreater(self.store.totals()["user1"]["download"], before + 1000)
                self.assertGreater(self.store.totals()["user1"]["upload"], 0)
                with self.store.connect() as db:
                    recorded=db.execute("SELECT SUM(download) FROM traffic_history WHERE kind='inbound' AND id='in1' AND step=3600").fetchone()[0]
                self.assertGreater(recorded, before+1000)
                self.runtime.stop()

    def test_new_standalone_protocols_transfer(self):
        # Hysteria 1 Brutal derives its window from configured bandwidth * RTT.
        # Linux loopback RTT is microseconds: a WAN rate can make the window
        # smaller than one datagram. Use a loopback-appropriate fixture rate.
        # This changes no generated production defaults or host networking.
        cases = [
            ("http", {"users": [{"username": "fixture", "password": "fixture-password"}]},
             {"type": "http", "username": "fixture", "password": "fixture-password"}),
            ("mixed", {"users": [{"username": "fixture", "password": "fixture-password"}]},
             {"type": "http", "username": "fixture", "password": "fixture-password"}),
            ("socks", {"users": [{"username": "fixture", "password": "fixture-password"}]},
             {"type": "socks", "version": "5", "username": "fixture", "password": "fixture-password"}),
            ("shadowsocks", {"method": "aes-128-gcm", "password": "fixture-password"},
             {"type": "shadowsocks", "method": "aes-128-gcm", "password": "fixture-password"}),
            ("snell", {"version": 5, "psk": "fixture-password"}, {"type": "snell", "version": 4, "psk": "fixture-password"}),
            ("snell", {"version": 6, "psk": "fixture-password", "mode": "unshaped"},
             {"type": "snell", "version": 6, "psk": "fixture-password", "mode": "unshaped"}),
            ("hysteria", {"up_mbps": 10000, "down_mbps": 10000, "users": [{"name": "fixture", "auth_str": "fixture-password"}]},
             {"type": "hysteria", "up_mbps": 10000, "down_mbps": 10000, "auth_str": "fixture-password"}),
            ("hysteria", {"up_mbps": 10000, "down_mbps": 10000, "users": [{"name": "fixture", "auth_str": "fixture-password"}], "obfs": "fixture-obfs"},
             {"type": "hysteria", "up_mbps": 10000, "down_mbps": 10000, "auth_str": "fixture-password", "obfs": "fixture-obfs"}),
        ]
        from nara.config import initial_state
        for protocol, server, outbound in cases:
            with self.subTest(protocol=protocol, version=server.get("version"), obfs=bool(server.get("obfs"))):
                port = free_port()
                state = initial_state()
                state["settings"]["block_private"] = False
                state["tls"] = [self.profile]
                if os.environ.get('NARA_TEST_DIAGNOSTICS') == '1':
                    state['core_options']['log'] = {'level':'debug'}
                conf = {"type": protocol, "tag": "native", "listen": "127.0.0.1", "listen_port": port, **server}
                state["inbounds"] = [{"id": "native", "mode": "native", "enabled": True, "tag": "native", "type": protocol,
                                      "config": conf, "tls_id": self.profile["id"] if protocol == "hysteria" else ""}]
                self.runtime.apply(state)
                outbound = {"tag": "proxy", "server": "127.0.0.1", "server_port": port, **outbound}
                if protocol == "hysteria":
                    outbound["tls"] = {"enabled": True, "server_name": "127.0.0.1", "certificate": [self.profile["certificate"]]}
                self.transfer(state, outbound)
                self.runtime.stop()

    def test_advanced_client_tls_verification_keeps_self_signed_trust(self):
        profile = copy.deepcopy(self.profile)
        profile['insecure'] = True
        state = example_state('trojan', profile)
        state['settings']['block_private'] = False
        state['inbounds'][0]['extra_client_options'] = {'tls': {'insecure': False}}
        exported = client_config(state,state['clients'][0],{})
        self.assertEqual(exported['outbounds'][1]['tls']['certificate'],[profile['certificate']])
        self.runtime.apply(state)
        self.transfer(state)

    def test_native_dns_hosts_rule_and_routing_hijack_answer_udp(self):
        from nara.config import initial_state
        from tests.test_native import row
        state=initial_state()
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as reserve:
            reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        state['inbounds']=[row({'type':'direct','tag':'dns-in','listen':'127.0.0.1','listen_port':port,
                               'network':'udp','override_address':'1.1.1.1','override_port':53})]
        state['dns_servers'].append(row({'type':'hosts','tag':'hosts','predefined':{'demo.nara.test':['192.0.2.42']}},'hosts'))
        state['dns_rules']=[row({'domain_suffix':['nara.test'],'action':'route','server':'hosts'})]
        state['route_rules']=[row({'inbound':['dns-in'],'action':'hijack-dns'})]
        self.runtime.apply(state)
        query=b'\x34\x56'+struct.pack('!HHHHH',0x100,1,0,0,0)+b'\x04demo\x04nara\x04test\x00'+struct.pack('!HH',1,1)
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.settimeout(5);sock.sendto(query,('127.0.0.1',port));answer,_=sock.recvfrom(4096)
        self.assertEqual(answer[:2],query[:2])
        self.assertEqual(answer[-4:],socket.inet_aton('192.0.2.42'))

    def test_user_space_wireguard_destination_routes_selected_traffic(self):
        from nara import warp
        from nara.config import initial_state
        from tests.test_native import row
        private, public = warp.keypair(CORE)
        remote_private, remote_public = warp.keypair(CORE)
        peer_port, proxy_port = free_port(), free_port()
        peer_config = {"log":{"level":"warn"}, "endpoints":[{
            "type":"wireguard", "tag":"fixture-peer", "system":False, "mtu":1280,
            "address":["10.88.0.2/32"], "private_key":remote_private, "listen_port":peer_port,
            "peers":[{"public_key":public, "allowed_ips":["10.88.0.1/32"]}]}],
            "outbounds":[{"type":"direct", "tag":"direct"}], "route":{"final":"direct", "rules":[{"action":"route","outbound":"direct","override_address":"127.0.0.1"}]}}
        peer_path=Path(self.temp.name)/'peer.json'
        atomic_write(peer_path,json.dumps(peer_config))
        with open(Path(self.temp.name)/'peer.client.log','w') as log:
            peer=subprocess.Popen([CORE,'run','-c',str(peer_path)],stdout=log,stderr=subprocess.STDOUT)
        try:
            time.sleep(.25)
            self.assertIsNone(peer.poll(),'User-space WireGuard peer did not start')
            config={"type":"wireguard","tag":"warp","system":False,"mtu":1280,
                    "address":["10.88.0.1/32"],"private_key":private,
                    "peers":[{"address":"127.0.0.1","port":peer_port,"public_key":remote_public,
                              "allowed_ips":["0.0.0.0/0"],"persistent_keepalive_interval":25,"reserved":[1,2,255]}]}
            state=initial_state();state['settings']['block_private']=False
            state['inbounds']=[row({'type':'mixed','tag':'local','listen':'127.0.0.1','listen_port':proxy_port})]
            state['endpoints']=[row(config,'warp')]
            state['route_rules']=[row({'port':[self.target.server_port],'action':'route','outbound':'warp'})]
            self.runtime.apply(state)
            def fetch(port):
                connection=http.client.HTTPConnection('127.0.0.1',proxy_port,timeout=8)
                try:
                    destination='192.0.2.1' if port==self.target.server_port else '127.0.0.1'
                    connection.request('GET','http://'+destination+':'+str(port)+'/')
                    response=connection.getresponse()
                    return response.status,response.read()
                finally: connection.close()
            status,data=fetch(self.target.server_port)
            self.assertEqual(status,200);self.assertIn(b'NARA traffic accounting test.',data)
            # Only the matching rule uses the endpoint. Direct traffic survives
            # an unreachable peer, proving this never replaces the host route.
            direct_target=ThreadingHTTPServer(('127.0.0.1',0),Target)
            threading.Thread(target=direct_target.serve_forever,daemon=True).start()
            try:
                peer.terminate();peer.wait(timeout=5)
                self.assertEqual(fetch(direct_target.server_port)[0],200)
                with self.assertRaises((OSError,http.client.HTTPException)):
                    fetch(self.target.server_port)
            finally:
                direct_target.shutdown();direct_target.server_close()
        finally:
            if peer.poll() is None: peer.terminate();peer.wait(timeout=5)

    def test_dns_rule_actions_order_and_default_answer_real_queries(self):
        from nara.config import initial_state
        from tests.test_native import row
        state=initial_state();state['settings']['block_private']=False
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as reserve:
            reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        state['inbounds']=[row({'type':'direct','tag':'dns-in','listen':'127.0.0.1','listen_port':port,
                               'network':'udp','override_address':'1.1.1.1','override_port':53})]
        state['dns_servers']=[row({'type':'hosts','tag':'fallback','predefined':{'default.nara.test':['192.0.2.30']}},'fallback'),
                              row({'type':'hosts','tag':'chosen','predefined':{'chosen.nara.test':['192.0.2.40']}},'chosen')]
        state['settings']['dns_final']='fallback'
        state['route_rules']=[row({'inbound':['dns-in'],'action':'hijack-dns'})]
        state['dns_rules']=[row({'action':'route-options','disable_cache':True},'options'),
                            row({'domain':['blocked.nara.test'],'action':'predefined','rcode':'NXDOMAIN'},'block'),
                            row({'domain':['chosen.nara.test'],'action':'route','server':'chosen'},'choose'),
                            row({'domain':['answer.nara.test'],'action':'predefined','rcode':'NOERROR',
                                 'answer':['answer.nara.test. 30 IN A 192.0.2.50']},'answer')]
        self.runtime.apply(state)
        def query(name):
            message=b'\x34\x56'+struct.pack('!HHHHH',0x100,1,0,0,0)+b''.join(bytes([len(x)])+x.encode() for x in name.split('.'))+b'\0'+struct.pack('!HH',1,1)
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                sock.settimeout(5);sock.sendto(message,('127.0.0.1',port));answer,_=sock.recvfrom(4096)
            return answer
        self.assertEqual(query('blocked.nara.test')[3]&15,3)
        for name,ip in [('chosen','192.0.2.40'),('answer','192.0.2.50'),('default','192.0.2.30')]:
            self.assertEqual(query(name+'.nara.test')[-4:],socket.inet_aton(ip))
        # A catch-all blocks later rules until they are moved before it.
        state['dns_rules'].insert(1,row({'action':'predefined','rcode':'REFUSED'},'catch-all'))
        self.runtime.apply(state)
        self.assertEqual(query('chosen.nara.test')[3]&15,5)
        state['dns_rules'].insert(0,state['dns_rules'].pop(3))
        self.runtime.apply(state)
        self.assertEqual(query('chosen.nara.test')[-4:],socket.inet_aton('192.0.2.40'))

    def test_protocol_specific_settings_transfer_and_account(self):
        cases = [
            ("vless", {"flow": "xtls-rprx-vision"}, {}, {}),
            ("vmess", {"alter_id": 0}, {"security": "chacha20-poly1305", "global_padding": True, "authenticated_length": True}, {"enabled": True, "padding": True, "protocol": "h2mux", "max_streams": 8}),
            ("trojan", {"fallback": {"server": "127.0.0.1", "server_port": self.target.server_port}}, {}, {}),
            ("hysteria2", {"obfs": {"type": "salamander", "password": "local-obfs-test"}, "up_mbps": 30, "down_mbps": 50, "masquerade": {"type": "string", "status_code": 404, "content": "Not found"}}, {}, {}),
            ("hysteria2", {"up_mbps": 30, "down_mbps": 50, "ignore_client_bandwidth": True}, {}, {}),
            ("hysteria2", {"obfs": {"type": "gecko", "password": "local-gecko-test", "min_packet_size": 512, "max_packet_size": 1200}, "bbr_profile": "standard", "idle_timeout": "30s", "stream_receive_window": "8 MB", "connection_receive_window": "20 MB"}, {}, {}),
            ("tuic", {"congestion_control": "bbr", "auth_timeout": "5s", "heartbeat": "1s"}, {"udp_relay_mode": "quic"}, {}),
            ("anytls", {"padding_scheme": ["stop=3", "0=30-30", "1=100-400", "2=400-500"]}, {"idle_session_check_interval": "5s", "idle_session_timeout": "10s", "min_idle_session": 1}, {})
        ]
        for protocol, server, client, multiplex in cases:
            with self.subTest(protocol=protocol, options=server):
                state = example_state(protocol, self.profile)
                state["settings"]["block_private"] = False
                state["inbounds"][0].update(server_options=server, client_options=client, multiplex=multiplex)
                self.runtime.apply(state)
                before = self.store.totals().get("user1", {}).get("download", 0)
                self.transfer(state)
                self.assertGreater(self.store.totals()["user1"]["download"], before + 1000)
                self.runtime.stop()

    def test_v2ray_transports_transfer(self):
        for kind, settings in (("ws", {"max_early_data": 2048, "early_data_header_name": "Sec-WebSocket-Protocol"}),
                               ("grpc", {"idle_timeout": "30s", "ping_timeout": "10s"}),
                               ("http", {"host": ["vpn.example.com"], "method": "POST"}),
                               ("httpupgrade", {"host": "vpn.example.com"}), ("quic", {})):
            with self.subTest(transport=kind):
                state = example_state("vless", self.profile)
                state["settings"]["block_private"] = False
                state["inbounds"][0].update(transport=kind, path="/nara-test", transport_options=settings)
                self.runtime.apply(state)
                self.transfer(state)
                self.runtime.stop()

    def test_dns_cache_rules_and_quic_resolvers_validate(self):
        state = example_state("vless", self.profile)
        state["settings"]["dns_options"] = {"strategy": "prefer_ipv4", "cache_capacity": 4096, "independent_cache": True, "reverse_mapping": True}
        state["dns_servers"] += [
            {"id": "doq", "tag": "doq", "type": "quic", "server": "1.1.1.1", "port": 853, "server_name": "cloudflare-dns.com"},
            {"id": "h3", "tag": "h3", "type": "h3", "server": "1.1.1.1", "port": 443, "path": "/dns-query", "server_name": "cloudflare-dns.com"}]
        state["dns_rules"] = [
            {"id": "r1", "match": "domain_regex", "values": [r"^ads\\."], "action": "reject", "options": {"invert": False}},
            {"id": "r2", "match": "query_type", "values": ["AAAA"], "action": "route", "server": "bootstrap", "options": {"ip_version": 6, "disable_cache": True, "rewrite_ttl": 60}}]
        directory, config = self.runtime.prepare(state)
        self.assertEqual(config["dns"]["cache_capacity"], 4096)
        self.assertEqual(config["dns"]["rules"][1]["rewrite_ttl"], 60)
        import shutil
        shutil.rmtree(directory)

    def test_unassigned_inbound_is_checked_by_core(self):
        state = example_state("anytls", self.profile)
        state["clients"] = []
        state["inbounds"][0].update(enabled=False, server_options={"padding_scheme": ["stop=not-a-number"]})
        with self.assertRaisesRegex(ValueError, "Sing-box rejected"):
            self.runtime.prepare(state)

    def test_usage_persists_across_restarts_without_double_counting(self):
        state = example_state("vless", self.profile)
        state["settings"]["block_private"] = False
        state["settings"]["server_address"] = "localhost"
        self.runtime.apply(state)
        self.transfer(state)
        before = self.store.totals()
        self.runtime.collect()
        self.assertEqual(before, self.store.totals())
        self.runtime.apply(state)
        self.assertEqual(before, self.store.totals())
        self.transfer(state)
        self.assertGreater(self.store.totals()["user1"]["download"], before["user1"]["download"])

    def test_failed_start_restores_previous_core(self):
        state = example_state("vless", self.profile)
        self.runtime.apply(state)
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            changed = copy.deepcopy(state)
            changed["inbounds"][0]["port"] = occupied.getsockname()[1]
            with self.assertRaises(ValueError):
                self.runtime.apply(changed)
        self.assertTrue(self.runtime.running)
        self.assertEqual(self.runtime.active, state)

    def test_quota_worker_removes_listener(self):
        state = example_state("vless", self.profile)
        state["settings"]["block_private"] = False
        state["clients"][0]["quota_bytes"] = 1000
        self.runtime.apply(state)
        self.transfer(state)
        self.store.set("autostart", False)
        # Exercise periodic enforcement, without the worker's initial autostart path.
        thread = threading.Thread(target=self.runtime.worker, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with self.runtime.lock:
                current = json.loads((self.runtime.generation / "config.json").read_text())
            if current["inbounds"] == []:
                break
            time.sleep(.2)
        self.assertEqual(current["inbounds"], [])
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", state["inbounds"][0]["port"]), timeout=1)
        self.runtime.shutdown.set()
        thread.join(timeout=5)

    def test_expiry_worker_removes_listener(self):
        import datetime as dt
        state = example_state("vless", self.profile)
        state["clients"][0]["expires_at"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=3)).isoformat()
        self.runtime.apply(state)
        self.store.set("autostart", False)
        thread = threading.Thread(target=self.runtime.worker, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with self.runtime.lock:
                    current = json.loads((self.runtime.generation / "config.json").read_text())
                if not current["inbounds"]:
                    break
                time.sleep(.2)
            self.assertEqual(current["inbounds"], [])
        finally:
            self.runtime.shutdown.set()
            thread.join(timeout=5)
