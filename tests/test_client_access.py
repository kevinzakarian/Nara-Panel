import copy
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import smtplib
import tempfile
import threading
import time
import unittest
from unittest import mock
from http.server import ThreadingHTTPServer
from nara import client_portal as portal, client_delivery as delivery, destination_import as imports, portable
from nara.access import Access
from nara.config import validate
from nara.runtime import Runtime
from nara.server import make_handler
from nara.store import Store
from tests.helpers import example_state


class ClientAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.state=example_state();self.client=self.state['clients'][0]
        self.client.update(email='customer@example.com',telegram_id='@customer')
        self.state['settings'].update(public_url='https://panel.example.com',subscription_url='https://sub.example.com/Access')
        self.store.set('state',self.state);self.access=Access(self.store.directory,{'NARA_SUB_PATH':'/Access','NARA_SUB_PORT':'10001'})
        self.runtime=Runtime(self.store,'/nonexistent');self.worker=delivery.Worker(self.store,self.runtime,self.access)
        self.store.set('telegram',{'bot_token':'123456:fake-token-not-used-for-network'})
    def tearDown(self):self.temp.cleanup()
    def enable(self,**patch):
        value=delivery.settings(self.store);value.update(smtp_enabled=True,host='smtp.example.com',from_email='nara@example.com',bot_enabled=True,bot_username='nara_test_bot',bot_fingerprint=delivery.bot_hash(self.store),**patch);self.store.set('client_delivery',value);return value
    def model(self):return portal.data(self.state,self.access,'https://example.com',self.client,{'user1':{'upload':10,'download':20}})
    def update(self,text,chat=123):return {'update_id':1,'message':{'date':int(time.time()),'chat':{'type':'private','id':chat},'from':{'id':chat,'is_bot':False},'text':text}}
    def test_portal_capability_is_distinct_scoped_and_rotates_with_subscription(self):
        cap=portal.token(self.client);self.assertNotEqual(cap,self.client['token']);self.assertEqual(len(cap),64)
        self.assertEqual(portal.find(self.state,cap)['id'],'user1');self.assertIsNone(portal.find(self.state,self.client['token']))
        other=copy.deepcopy(self.client);other.update(id='other',token=secrets.token_urlsafe(32));self.state['clients'].append(other)
        self.assertNotEqual(portal.token(other),cap);self.client['token']=secrets.token_urlsafe(32);self.assertIsNone(portal.find(self.state,cap))
    def test_exhausted_or_expired_portal_reports_actual_balance_without_admin_secrets(self):
        self.client.update(quota_bytes=25,email='private@example.com',telegram_id='@private')
        result=self.model();self.assertEqual(result['remaining'],0);self.assertEqual(result['status'],'Traffic limit reached');self.assertFalse(result['enabled'])
        self.assertTrue(result['links']);self.assertNotIn('email',result);self.assertNotIn('telegram_id',result)
        self.assertNotIn('private_key',json.dumps(result));self.assertNotIn('bot_token',json.dumps(result))
    def test_contact_validation_rejects_header_injection_and_invalid_telegram_identifiers(self):
        for value in ['a@example.com\r\nBcc: b@example.com','a@example.com\n','invalid','a..b@example.com']:
            with self.subTest(value=value),self.assertRaises(ValueError):portal.contact(value,'email')
        for value in ['-123','@ab','123\n456','x'*200]:
            with self.subTest(value=value),self.assertRaises(ValueError):portal.contact(value,'telegram')
        self.client['email']='user@example.com';validate(self.state)
    def test_template_placeholders_are_allowlisted_and_expansion_is_bounded(self):
        for text in ['{username.__class__}','{unknown}','{username!r}','{username:1000000000}']:
            with self.subTest(text=text),self.assertRaises(ValueError):delivery.check_template(text)
        with self.assertRaises(ValueError):delivery.format_template('{username}'*20,{'username':'x'*100},1000)
        self.assertEqual(delivery.format_template('Hi {username}',{'username':'Alice'},100),'Hi Alice')
    def test_smtp_has_verified_tls_no_plaintext_fallback_and_sanitized_errors(self):
        value=self.enable();smtp=mock.MagicMock()
        with mock.patch.object(delivery.smtplib,'SMTP',return_value=smtp) as factory:
            connection=delivery.smtp_connect(value);factory.assert_called_once_with('smtp.example.com',587,timeout=12);smtp.starttls.assert_called_once()
            context=smtp.starttls.call_args.kwargs['context'];self.assertTrue(context.check_hostname);self.assertEqual(context.verify_mode,2);self.assertIs(connection,smtp)
        with mock.patch.object(delivery.smtplib,'SMTP',side_effect=smtplib.SMTPException('secret-password')):
            with self.assertRaisesRegex(ValueError,'SMTP connection failed') as error:delivery.smtp_connect(value)
            self.assertNotIn('secret-password',str(error.exception))
        with self.assertRaises(ValueError):delivery.validate({'security':'plain'},value)
    def test_email_escapes_html_and_contains_decodable_png_qr_attachments(self):
        value=self.enable();model=self.model();model['name']='<img src=x onerror=alert(1)>'
        message=delivery.email_message(value,'customer@example.com',dict(delivery.DEFAULT_TEMPLATE),model)
        html_part=next(part for part in message.walk() if part.get_content_type()=='text/html').get_content()
        self.assertNotIn('<img src=x',html_part);self.assertIn('&lt;img',html_part)
        images=[part for part in message.walk() if part.get_content_type()=='image/png'];self.assertGreaterEqual(len(images),2)
        for part in images:self.assertTrue(part.get_payload(decode=True).startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertIn('https://sub.example.com',html_part);self.assertNotIn(value['password'],html_part) if value['password'] else None
    def test_pairing_requires_one_use_capability_and_username_alone_never_discloses_service(self):
        self.enable();nonce=delivery.pair(self.store,self.client)['url'].split('start=')[1]
        with mock.patch.object(delivery.notifications,'send') as send:
            self.worker.process_update(self.update(self.client['name']));self.assertNotIn(self.client['token'],send.call_args.args[2]);self.assertNotIn('Traffic used:',send.call_args.args[2])
            self.worker.chat_times.clear();self.worker.process_update(self.update('/start '+nonce));self.assertEqual(delivery.binding(self.store,self.client),'123')
            self.worker.chat_times.clear();self.worker.process_update(self.update('/start '+nonce,456));self.assertEqual(delivery.binding(self.store,self.client),'123')
            self.worker.chat_times.clear();self.worker.process_update(self.update('/status',456));self.assertNotIn('Traffic used:',send.call_args.args[2])
            self.worker.chat_times.clear();self.worker.process_update(self.update('/status'));self.assertIn('Traffic used:',send.call_args.args[2])
            self.worker.chat_times.clear();self.worker.process_update(self.update(self.client['name']));self.assertIn('Traffic remaining:',send.call_args.args[2])
            self.client['token']=secrets.token_urlsafe(32);self.store.set('state',self.state);self.assertIsNone(delivery.binding(self.store,self.client))
    def test_group_chats_forwarded_messages_expired_pairs_and_changed_bots_cannot_bind(self):
        self.enable();nonce=delivery.pair(self.store,self.client)['url'].split('start=')[1]
        with mock.patch.object(delivery.notifications,'send') as send:
            update=self.update('/start '+nonce);update['message']['chat']['type']='group';self.worker.process_update(update);send.assert_not_called()
            update=self.update('/start '+nonce);update['message']['forward_origin']={'type':'user'};self.worker.process_update(update);send.assert_not_called()
            with self.store.connect() as db:db.execute('UPDATE client_bot_pairs SET expires=0')
            self.worker.process_update(self.update('/start '+nonce));self.assertIsNone(delivery.binding(self.store,self.client))
        self.store.set('telegram',{'bot_token':'123456:changed-test-token'})
        with self.assertRaises(ValueError):delivery.pair(self.store,self.client)
    def test_queue_checks_recipient_cancels_changed_contacts_and_limits_duplicate_sends(self):
        self.enable();delivery.enqueue(self.store,self.client,'email')
        with self.assertRaisesRegex(ValueError,'30 seconds'):delivery.enqueue(self.store,self.client,'email')
        self.client['email']='new@example.com';self.store.set('state',self.state)
        with mock.patch.object(delivery,'smtp_connect') as connect:self.worker.deliver();connect.assert_not_called()
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT status FROM client_messages').fetchone()[0],'cancelled')
        with self.assertRaisesRegex(ValueError,'pair'):delivery.enqueue(self.store,self.client,'telegram')
    def test_delivery_settings_secrets_are_hidden_and_backups_disable_outbound_features(self):
        value=self.enable();value['password']='private-smtp-test';self.store.set('client_delivery',value)
        public=delivery.public_settings(self.store);self.assertNotIn('password',public);self.assertTrue(public['password_configured'])
        backup=portable.document(self.store);self.assertEqual(backup['client_delivery']['password'],'private-smtp-test');portable.prepare(backup,self.state)
        self.assertNotIn('public_url',backup['state']['settings']);self.assertIn('email',backup['state']['clients'][0])

    def test_link_command_only_sends_qr_to_paired_owner_and_token_changes_disable_client_bot(self):
        self.enable();nonce=delivery.pair(self.store,self.client)['url'].split('start=')[1]
        with mock.patch.object(delivery.notifications,'send'),mock.patch.object(delivery.notifications,'send_photo') as photo:
            self.worker.process_update(self.update('/start '+nonce));self.worker.chat_times.clear()
            self.worker.process_update(self.update('/links',456));photo.assert_not_called();self.worker.chat_times.clear()
            self.worker.process_update(self.update('/links'));self.assertEqual(photo.call_args.args[1],'123');self.assertTrue(photo.call_args.args[2].startswith(b'\x89PNG'))
        previous=delivery.notifications.settings(self.store)
        delivery.notifications.save_settings(self.store,{**previous,'bot_token':'123456:replacement-fake-token'},previous)
        self.assertFalse(delivery.settings(self.store)['bot_enabled'])
        self.assertIsNone(delivery.binding(self.store,self.client))

    def test_bot_discovery_keeps_channels_without_answering_service_requests_in_groups(self):
        self.enable();update={'update_id':1,'channel_post':{'chat':{'id':-123,'type':'channel','title':'Admin channel'},'text':'/status'}}
        self.worker.remember_chats(update)
        with mock.patch.object(delivery.notifications,'send') as send:self.worker.process_update(update);send.assert_not_called()
        self.assertEqual(self.store.get('client_bot_chats'),[{'id':'-123','name':'Admin channel'}])


class DestinationImportTests(unittest.TestCase):
    def test_connection_links_roundtrip_passwords_tls_transport_and_obfuscation(self):
        uri='hysteria2://pa%3Ass%40word@example.com:8443?insecure=1&sni=example.com&obfs=salamander&obfs-password=hidden#My%20proxy'
        config=imports.preview(uri)['destinations'][0];self.assertEqual(config['password'],'pa:ss@word');self.assertEqual(config['server_port'],8443)
        self.assertTrue(config['tls']['insecure']);self.assertEqual(config['obfs']['password'],'hidden');self.assertEqual(config['tag'],'My-proxy')
        uri='vless://00000000-0000-4000-8000-000000000001@example.com:443?security=tls&type=ws&path=%2Fproxy&host=cdn.example#Web'
        config=imports.preview(uri)['destinations'][0];self.assertEqual(config['transport']['path'],'/proxy');self.assertEqual(config['transport']['headers']['Host'],'cdn.example')
    def test_realty_shadowsocks_and_base64_subscription_are_parsed_without_fetching(self):
        import base64
        config=imports.preview('vless://00000000-0000-4000-8000-000000000001@example.com:443?security=reality&pbk='+'A'*43+'&sid=1234&fp=chrome')['destinations'][0]
        self.assertTrue(config['tls']['reality']['enabled']);self.assertNotIn('insecure',config['tls'])
        auth=base64.urlsafe_b64encode(b'aes-128-gcm:secret').decode().rstrip('=')
        config=imports.preview('ss://'+auth+'@example.com:8388#Test')['destinations'][0];self.assertEqual(config['password'],'secret')
        source='trojan://secret@example.com:443#One\ntrojan://secret@example.org:443#One'
        result=imports.preview(base64.b64encode(source.encode()).decode());self.assertEqual([row['tag'] for row in result['destinations']],['One','One-2'])
    def test_json_only_extracts_proxies_and_rejects_local_resource_references(self):
        base={'type':'trojan','tag':'proxy','server':'example.com','server_port':443,'password':'secret','tls':{'enabled':True}}
        config=imports.preview(json.dumps({'outbounds':[{'type':'direct','tag':'direct'},base]}))['destinations'];self.assertEqual(len(config),1)
        for patch in [{'tls':{'key_path':'/etc/shadow'}},{'detour':'local'},{'routing_mark':1},{'command':'do-something'}]:
            with self.subTest(patch=patch),self.assertRaises(ValueError):imports.preview(json.dumps({**base,**patch}))
    def test_ssrf_blocks_all_private_mixed_loopback_mapped_ipv6_and_metadata_addresses_before_connect(self):
        for address in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1','192.168.1.1','100.64.0.1']:
            with self.subTest(address=address),mock.patch.object(imports.socket,'getaddrinfo',return_value=[(2,1,6,'',(address,80))]),mock.patch.object(imports.http.client,'HTTPConnection') as connect:
                with self.assertRaisesRegex(ValueError,'public Internet'):imports.fetch('http://external.example/sub')
                connect.assert_not_called()
        with mock.patch.object(imports.socket,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',80)),(2,1,6,'',('127.0.0.1',80))]):
            with self.assertRaises(ValueError):imports.public_addresses('mixed.example',80)
    def test_fetch_revalidates_redirects_pins_connection_and_bounds_size(self):
        connection=mock.MagicMock();response=mock.MagicMock();connection.getresponse.return_value=response;response.status=302
        response.getheader.return_value='http://internal.example/sub'
        with mock.patch.object(imports,'public_addresses',side_effect=[['8.8.8.8'],ValueError('private host blocked')]) as resolve,mock.patch.object(imports.http.client,'HTTPConnection',return_value=connection) as connect:
            with self.assertRaisesRegex(ValueError,'private host'):imports.fetch('http://public.example/sub')
            connect.assert_called_once_with('8.8.8.8',80,timeout=mock.ANY);self.assertEqual(resolve.call_count,2)
        response.status=200;response.getheader.side_effect=lambda name,default=None:'999999999' if name=='Content-Length' else default
        with mock.patch.object(imports,'public_addresses',return_value=['8.8.8.8']),mock.patch.object(imports.http.client,'HTTPConnection',return_value=connection):
            with self.assertRaisesRegex(ValueError,'too large'):imports.fetch('http://public.example/sub')
        with self.assertRaises(ValueError):imports.fetch('https://user:secret@example.com/sub')


class PublicPortalHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.state=example_state();self.store.set('state',self.state);self.runtime=Runtime(self.store,'/nonexistent')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.store,self.runtime,Path('web'),web_path='/Access',role='subscription'))
        threading.Thread(target=self.server.serve_forever,daemon=True).start();self.path='/Access/portal/'+portal.token(self.state['clients'][0])+'/'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.temp.cleanup()
    def request(self,path,method='GET',body=None,headers=None):
        connection=http.client.HTTPConnection(*self.server.server_address,timeout=10);connection.request(method,path,body,headers or {});response=connection.getresponse();result=response.status,response.read(),dict(response.getheaders());connection.close();return result
    def test_public_page_scoped_data_assets_headers_and_revocation(self):
        status,body,headers=self.request(self.path);self.assertEqual(status,200);self.assertIn(b'Your private service',body);self.assertEqual(headers['Referrer-Policy'],'no-referrer');self.assertEqual(headers['Cache-Control'],'no-store');self.assertEqual(headers['X-Frame-Options'],'DENY')
        status,body,_=self.request(self.path+'api');self.assertEqual(status,200);self.assertEqual(json.loads(body)['name'],'Test client')
        for asset in ['style.css','portal.js','qrcodegen.js','subscription-qr.js']:self.assertEqual(self.request('/Access/portal-assets/'+asset)[0],200)
        for path in ['/Access/api/state','/Access/index.html','/Access/portal-assets/../index.html',self.path+'admin',self.path+'api/other']:
            self.assertEqual(self.request(path)[0],404)
        self.state['clients'][0]['token']=secrets.token_urlsafe(32);self.store.set('state',self.state);self.assertEqual(self.request(self.path+'api')[0],404)
    def test_pairing_post_enforces_capability_origin_and_request_shape(self):
        settings=delivery.settings(self.store);settings.update(bot_enabled=True,bot_username='nara_test_bot',bot_fingerprint=delivery.bot_hash(self.store));self.store.set('client_delivery',settings)
        host='127.0.0.1:'+str(self.server.server_port)
        headers={'Content-Type':'application/json','Origin':'https://evil.example'}
        self.assertEqual(self.request(self.path+'pair','POST','{}',headers)[0],400)
        headers['Origin']='http://'+host
        status,body,_=self.request(self.path+'pair','POST','{}',headers);self.assertEqual(status,200);self.assertTrue(json.loads(body)['url'].startswith('https://t.me/nara_test_bot?start='))
        self.assertEqual(self.request('/Access/api/state','POST','{}',headers)[0],404)

class SMTPTransportTests(unittest.TestCase):
    def test_real_tls_and_starttls_deliver_mime_with_inline_qr_on_loopback(self):
        import base64
        import queue
        import socketserver
        import ssl
        from nara.server import self_signed
        for mode in ('tls','starttls'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                profile=self_signed({'server_name':'127.0.0.1','days':1})
                cert=Path(directory)/'smtp.crt';key=Path(directory)/'smtp.key';cert.write_text(profile['certificate']);key.write_text(profile['private_key'])
                context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
                trusted=ssl.create_default_context(cafile=str(cert));received=queue.Queue()
                class SMTPHandler(socketserver.StreamRequestHandler):
                    def finish(self):
                        try:super().finish()
                        finally:self.connection.close()
                    def handle(self):
                        encrypted=mode=='tls';self.connection.settimeout(8);self.wfile.write(b'220 localhost NARA test SMTP\r\n')
                        while line:=self.rfile.readline(4096):
                            command=line.split(b' ',1)[0].strip().upper()
                            if command in (b'EHLO',b'HELO'):
                                self.wfile.write(b'250-localhost\r\n250 AUTH PLAIN\r\n' if encrypted else b'250-localhost\r\n250 STARTTLS\r\n')
                            elif command==b'STARTTLS':
                                self.wfile.write(b'220 Ready for TLS\r\n');self.wfile.flush();self.rfile.close();self.wfile.close()
                                self.connection=context.wrap_socket(self.connection,server_side=True);self.rfile=self.connection.makefile('rb');self.wfile=self.connection.makefile('wb',buffering=0);encrypted=True
                            elif command==b'AUTH':
                                auth=line.strip().split(b' ',2)
                                if encrypted and len(auth)==3 and base64.b64decode(auth[2])==b'\0fixture-user\0fixture-password':self.wfile.write(b'235 Authenticated\r\n')
                                else:self.wfile.write(b'535 Rejected\r\n')
                            elif command in (b'MAIL',b'RCPT'):self.wfile.write(b'250 OK\r\n')
                            elif command==b'DATA':
                                self.wfile.write(b'354 Send message\r\n');chunks=[]
                                while (part:=self.rfile.readline(65536)) not in (b'.\r\n',b''):
                                    chunks.append(part)
                                received.put(b''.join(chunks));self.wfile.write(b'250 Accepted\r\n')
                            elif command==b'QUIT':self.wfile.write(b'221 Bye\r\n');return
                            else:self.wfile.write(b'250 OK\r\n')
                server=socketserver.ThreadingTCPServer(('127.0.0.1',0),SMTPHandler);server.daemon_threads=True
                if mode=='tls':server.socket=context.wrap_socket(server.socket,server_side=True)
                threading.Thread(target=server.serve_forever,daemon=True).start()
                try:
                    store=Store(Path(directory)/'data');state=example_state();state['clients'][0]['email']='recipient@example.com';state['settings']['subscription_url']='https://sub.example.com/Access';store.set('state',state)
                    config=delivery.settings(store);config.update(smtp_enabled=True,host='127.0.0.1',port=server.server_address[1],security=mode,username='fixture-user',password='fixture-password',from_email='nara@example.com');store.set('client_delivery',config)
                    delivery.enqueue(store,state['clients'][0],'email')
                    worker=delivery.Worker(store,Runtime(store,'/nonexistent'),Access(store.directory,{}))
                    with mock.patch.object(delivery.ssl,'create_default_context',return_value=trusted):worker.deliver()
                    raw=received.get(timeout=3);self.assertIn(b'Content-Type: image/png',raw);self.assertIn(b'Content-ID: <nara-connection-',raw)
                    with store.connect() as db:self.assertEqual(db.execute('SELECT status FROM client_messages').fetchone()[0],'sent')
                finally:server.shutdown();server.server_close()
