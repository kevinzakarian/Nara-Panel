import datetime as dt
import io
import json
import tempfile
import threading
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest import mock
from nara import notifications
from nara.store import Store
from nara.config import initial_state
from tests.helpers import example_state
from tests import test_api

TOKEN='123456:FIXTURE_TOKEN_NOT_A_REAL_TELEGRAM_BOT'


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.runtime=SimpleNamespace(running=True,shutdown=threading.Event())
        self.worker=notifications.Worker(self.store,self.runtime)
    def tearDown(self):self.temp.cleanup()
    def enable(self,events=None):
        value=notifications.settings(self.store);value.update(enabled=True,bot_token=TOKEN,chat_id='123456',events=events or list(notifications.EVENTS))
        self.store.set('telegram',value)
    def rows(self):
        with self.store.connect() as db:return db.execute('SELECT event,payload,status,attempts,available FROM notifications ORDER BY id').fetchall()

    def test_disabled_by_default_and_all_useful_events_selected(self):
        config=notifications.settings(self.store);self.assertFalse(config['enabled']);self.assertNotIn('test',config['events'])
        self.assertIn('daily_summary',config['events']);self.assertIn('clients_updated',config['events'])
        self.assertFalse(notifications.enqueue(self.store,'login','Test'));self.assertEqual(self.rows(),[])
        self.enable(['core_down']);self.assertFalse(notifications.enqueue(self.store,'login','Test'))
        self.assertTrue(notifications.enqueue(self.store,'core_down','Stopped'))
        self.assertNotIn(TOKEN,json.dumps(notifications.public_settings(self.store)))

    def test_daily_quota_expiry_and_state_change_notices_are_deduplicated(self):
        self.enable();state=example_state();now=dt.datetime(2026,10,18,12,tzinfo=dt.timezone.utc).timestamp()
        state['clients'][0].update(quota_bytes=1000,expires_at=dt.datetime.fromtimestamp(now+3600,dt.timezone.utc).isoformat())
        self.store.set('state',state);self.store.add_traffic([('user1','download',900)])
        self.worker.metrics.read=mock.Mock(return_value={'cpu_percent':10,'memory_total':100,'memory_used':10,'disk_total':100,'disk_used':10})
        with mock.patch('nara.notifications.time.time',return_value=now):
            self.worker.poll(now);self.worker.poll(now)
            events=[row[0] for row in self.rows()]
            self.assertEqual(events.count('quota_warning'),1);self.assertEqual(events.count('expiry_warning'),1);self.assertEqual(events.count('daily_summary'),1)
            self.runtime.running=False;self.worker.poll(now);self.runtime.running=True;self.worker.poll(now)
        events=[row[0] for row in self.rows()];self.assertIn('core_down',events);self.assertIn('core_up',events)
        private=state['clients'][0]['password'];self.assertNotIn(private,str(self.rows()));self.assertNotIn(state['clients'][0]['token'],str(self.rows()))

    def test_resource_alert_requires_sustained_usage_and_recovers_once(self):
        self.enable(['resource_alert','resource_recovery']);self.worker.metrics.read=mock.Mock(return_value={'cpu_percent':95,'memory_total':100,'memory_used':10,'disk_total':100,'disk_used':10})
        for _ in range(2):self.worker.poll()
        self.assertEqual(self.rows(),[]);self.worker.poll();self.worker.poll()
        self.assertEqual([row[0] for row in self.rows()],['resource_alert'])
        self.worker.metrics.read.return_value['cpu_percent']=20;self.worker.poll();self.worker.poll()
        self.assertEqual([row[0] for row in self.rows()],['resource_alert','resource_recovery'])

    def test_delivery_retries_rate_limits_without_exposing_bot_token(self):
        self.enable();notifications.enqueue(self.store,'login','Administrator signed in')
        with mock.patch('nara.notifications.send',side_effect=notifications.DeliveryError('Rate limited',120)):
            self.worker.deliver()
        self.assertEqual(self.rows()[0][2],'queued');self.assertEqual(self.rows()[0][3],1)
        with mock.patch('nara.notifications.send') as send:self.worker.deliver();send.assert_not_called()
        with self.store.connect() as db:db.execute('UPDATE notifications SET available=0')
        self.store.set('telegram_throttle',0)
        with mock.patch('nara.notifications.send') as send:self.worker.deliver();send.assert_called_once()
        self.assertEqual(self.rows()[0][2],'sent');self.assertNotIn(TOKEN,json.dumps(notifications.public_settings(self.store)))

    def test_telegram_transport_is_fixed_tls_bounded_and_sanitizes_errors(self):
        opener=mock.Mock();response=mock.MagicMock(status=200);response.__enter__.return_value=response;response.read.return_value=b'{"ok":true,"result":{"message_id":1}}';opener.open.return_value=response
        with mock.patch.object(notifications.request,'build_opener',return_value=opener):notifications.send(TOKEN,'123','Test')
        req=opener.open.call_args.args[0];self.assertEqual(req.full_url,'https://api.telegram.org/bot'+TOKEN+'/sendMessage');self.assertEqual(json.loads(req.data)['text'],'Test')
        self.assertNotIn(TOKEN,req.data.decode());self.assertEqual(opener.open.call_args.kwargs['timeout'],10)
        for code in (400,401,403,429,500):
            opener.open.side_effect=HTTPError(req.full_url,code,'SECRET '+TOKEN,{},io.BytesIO(b'{"parameters":{"retry_after":120}}'))
            with mock.patch.object(notifications.request,'build_opener',return_value=opener),self.assertRaises(notifications.DeliveryError) as caught:notifications.send(TOKEN,'123','Test')
            self.assertNotIn(TOKEN,str(caught.exception));self.assertNotIn('SECRET',str(caught.exception))

    def test_discovery_returns_only_unique_chat_ids_and_names(self):
        with mock.patch('nara.notifications.call',return_value=[{'message':{'chat':{'id':123,'first_name':'Owner'},'text':'PRIVATE_MESSAGE'}},{'message':{'chat':{'id':123,'first_name':'Owner'}}}]):
            self.assertEqual(notifications.chats(TOKEN),[{'id':'123','name':'Owner'}])


class TelegramAPITests(unittest.TestCase):
    setUp=test_api.APITests.setUp;tearDown=test_api.APITests.tearDown;request=test_api.APITests.request;login=test_api.APITests.login;web_path=''
    def test_configuration_requires_reauthentication_and_test_is_queued_only(self):
        self.login();config=notifications.settings(self.store);config.update(enabled=True,bot_token=TOKEN,chat_id='123456')
        with mock.patch('nara.notifications.send') as send:
            self.assertEqual(self.request('/api/telegram',{'settings':config})[0],400)
            self.assertEqual(self.request('/api/telegram',{'current':'test-password-123','settings':config})[0],200)
            self.assertEqual(self.request('/api/telegram/test',{'current':'test-password-123'})[0],200)
            send.assert_not_called()
        visible=self.request('/api/telegram')[1];self.assertNotIn(TOKEN,json.dumps(visible));self.assertTrue(visible['token_configured'])
        self.assertEqual(self.request('/api/telegram',{'current':'test-password-123','settings':{**config,'bot_token':'','chat_id':'789'}})[0],200)
        self.assertEqual(self.store.get('telegram')['bot_token'],TOKEN)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT status FROM notifications').fetchone()[0],'cancelled')
