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

class TimeZoneTests(unittest.TestCase):
    setUp=NotificationTests.setUp;tearDown=NotificationTests.tearDown;enable=NotificationTests.enable;rows=NotificationTests.rows
    def configure_zone(self, name, hour=9, minute=0):
        self.enable(['daily_summary'])
        state=initial_state();state['settings']['time_zone']=name;self.store.set('state',state)
        config=notifications.settings(self.store);config.update(summary_hour=hour,summary_minute=minute);self.store.set('telegram',config)

    def poll_at(self, value):
        now=dt.datetime.fromisoformat(value).timestamp()
        with mock.patch('nara.notifications.time.time',return_value=now):self.worker.poll(now)

    def test_tehran_half_hour_offset_and_minute_precision(self):
        self.configure_zone('Asia/Tehran',9,15)
        self.poll_at('2026-10-18T05:44:59+00:00');self.assertEqual(self.rows(),[])
        self.poll_at('2026-10-18T05:45:00+00:00');self.poll_at('2026-10-18T19:00:00+00:00')
        self.assertEqual(len(self.rows()),1)

    def test_summary_uses_local_date_across_utc_midnight(self):
        self.configure_zone('Asia/Tokyo',0,15)
        self.poll_at('2026-10-17T15:15:00+00:00');self.poll_at('2026-10-18T00:30:00+00:00')
        self.assertEqual(len(self.rows()),1)
        self.poll_at('2026-10-18T15:15:00+00:00');self.assertEqual(len(self.rows()),2)

    def test_dst_spring_skipped_hour_catches_up_and_fall_repeated_hour_deduplicates(self):
        self.configure_zone('America/New_York',2,30)
        self.poll_at('2026-03-08T06:59:00+00:00');self.assertEqual(self.rows(),[])
        self.poll_at('2026-03-08T07:00:00+00:00');self.assertEqual(len(self.rows()),1)
        self.configure_zone('America/New_York',1,30)
        self.poll_at('2026-11-01T05:30:00+00:00');self.poll_at('2026-11-01T06:30:00+00:00')
        self.assertEqual(len(self.rows()),2)

    def test_zone_change_and_restart_keep_same_day_deduplication(self):
        self.configure_zone('UTC',9)
        self.poll_at('2026-10-18T10:00:00+00:00')
        self.configure_zone('Asia/Tehran',9)
        self.worker=notifications.Worker(self.store,self.runtime)
        self.poll_at('2026-10-18T10:01:00+00:00');self.assertEqual(len(self.rows()),1)
        # Switching from UTC+14 to UTC-12 can revisit a date after 26 hours.
        self.configure_zone('Pacific/Kiritimati',0)
        self.poll_at('2026-12-19T10:00:00+00:00');self.assertEqual(len(self.rows()),2)
        self.configure_zone('Etc/GMT+12',0)
        self.poll_at('2026-12-20T12:00:00+00:00');self.assertEqual(len(self.rows()),2)

    def test_legacy_defaults_and_summary_time_validation(self):
        from nara import timezones
        from nara.config import validate,build_config
        state=initial_state();del state['settings']['time_zone'];validate(state)
        self.assertEqual(timezones.name(state),'UTC')
        before=build_config(state,{},'/tmp',1234)
        state['settings']['time_zone']='Asia/Tehran';validate(state)
        self.assertEqual(before,build_config(state,{},'/tmp',1234))
        for value in ('',None,3,False,'../UTC','/etc/passwd','Not/AZone','x'*129):
            state['settings']['time_zone']=value
            with self.subTest(zone=value),self.assertRaises(ValueError):validate(state)
        config=notifications.settings(self.store);del config['summary_minute']
        self.assertEqual(notifications.validate_settings({},config)['summary_minute'],0)
        for value in (-1,60,True,'15',None):
            with self.subTest(minute=value),self.assertRaises(ValueError):notifications.validate_settings({'summary_minute':value},config)

    def test_notification_timestamp_uses_panel_zone(self):
        self.configure_zone('Asia/Tehran')
        notifications.enqueue(self.store,'test','Test')
        with mock.patch('nara.notifications.send') as send:self.worker.deliver()
        message=send.call_args.args[2]
        self.assertIn('+0330 · Asia/Tehran',message)


class TimeZoneAPITests(unittest.TestCase):
    setUp=TelegramAPITests.setUp;tearDown=TelegramAPITests.tearDown;request=TelegramAPITests.request;login=TelegramAPITests.login;web_path=""
    def test_settings_zone_is_persisted_and_invalid_zone_keeps_previous_state(self):
        self.login();state=self.store.get('state');settings={**state['settings'],'time_zone':'Asia/Tehran'}
        status,data,_=self.request('/api/settings',{'revision':state['revision'],'settings':settings})
        self.assertEqual(status,200,data)
        visible=self.request('/api/state')[1]
        self.assertEqual(visible['settings']['time_zone'],'Asia/Tehran')
        status,data,_=self.request('/api/settings',{'revision':visible['revision'],'settings':{**settings,'time_zone':'Invalid/Zone'}})
        self.assertEqual(status,400,data)
        self.assertEqual(self.store.get('state'),visible)
        self.assertIn('Asia/Tehran',self.request('/api/options')[1]['time_zones'])

class NotificationSaveConcurrencyTests(unittest.TestCase):
    setUp=TelegramAPITests.setUp;tearDown=TelegramAPITests.tearDown;request=TelegramAPITests.request;login=TelegramAPITests.login;web_path=''

    def test_clear_then_select_all_remain_responsive_while_bot_delivery_is_blocked(self):
        import time
        self.login();all_events=[key for key in notifications.EVENTS if key!='test']
        config={**notifications.settings(self.store),'enabled':True,'bot_token':TOKEN,'chat_id':'123456'}
        def save(events):
            status,data,_=self.request('/api/telegram',{'current':'test-password-123','settings':{**config,'events':events}})
            self.assertEqual(status,200,data)
            self.assertEqual(self.request('/api/telegram')[1]['events'],events)
        save([]);save(all_events)
        worker=notifications.Worker(self.store,self.runtime);worker.last_poll=time.time()
        entered=threading.Event();release=threading.Event()
        def slow_send(*args):
            entered.set();release.wait(8)
            raise notifications.DeliveryError('Fixture delivery unavailable')
        with mock.patch('nara.notifications.send',side_effect=slow_send):
            thread=threading.Thread(target=worker.run,daemon=True);thread.start()
            try:
                self.assertTrue(entered.wait(3),'No queued startup notification reached delivery')
                start=time.monotonic();save([]);save(all_events)
                self.assertLess(time.monotonic()-start,3)
                self.assertEqual(self.request('/api/dashboard')[0],200)
                self.assertTrue(thread.is_alive())
            finally:
                self.runtime.shutdown.set();self.store.notification_wakeup.set();release.set();thread.join(3)
                self.assertFalse(thread.is_alive())

class NotificationPreferenceTests(unittest.TestCase):
    setUp=NotificationTests.setUp;tearDown=NotificationTests.tearDown;enable=NotificationTests.enable;rows=NotificationTests.rows

    def test_clear_cancels_deselected_queue_atomically_and_select_all_does_not_replay_it(self):
        self.enable();previous=notifications.settings(self.store)
        notifications.enqueue(self.store,'login','Fixture');notifications.enqueue(self.store,'test','Fixture')
        clear={**previous,'events':[]};notifications.save_settings(self.store,clear,previous)
        self.assertEqual([(row[0],row[2]) for row in self.rows()],[('login','cancelled'),('test','queued')])
        notifications.save_settings(self.store,previous,clear)
        self.assertEqual(self.rows()[0][2],'cancelled')
        self.assertEqual(notifications.settings(self.store)['events'],previous['events'])

    def test_failed_save_rolls_back_preferences_and_does_not_wake_delivery(self):
        import contextlib
        self.enable();previous=notifications.settings(self.store);notifications.enqueue(self.store,'login','Fixture')
        self.store.notification_wakeup.clear();connect=self.store.connect
        @contextlib.contextmanager
        def fail_cancellation():
            with connect() as db:
                class Broken:
                    def execute(self,query,args=()):
                        if query.startswith('UPDATE notifications'):raise OSError('Fixture failure')
                        return db.execute(query,args)
                yield Broken()
        with mock.patch.object(self.store,'connect',fail_cancellation),self.assertRaises(OSError):
            notifications.save_settings(self.store,{**previous,'events':[]},previous)
        self.assertEqual(notifications.settings(self.store),previous)
        self.assertEqual(self.rows()[0][2],'queued');self.assertFalse(self.store.notification_wakeup.is_set())

    def test_failed_inflight_delivery_cannot_resurrect_a_cancelled_message(self):
        self.enable(['login']);previous=notifications.settings(self.store);notifications.enqueue(self.store,'login','Fixture')
        def fail_after_clear(*args):
            notifications.save_settings(self.store,{**previous,'events':[]},previous)
            raise notifications.DeliveryError('Fixture delivery failed')
        with mock.patch('nara.notifications.send',side_effect=fail_after_clear):self.worker.deliver()
        self.assertEqual(self.rows()[0][2],'cancelled')

    def test_no_events_skip_health_and_client_scans_but_still_allow_an_explicit_test(self):
        self.enable();previous=notifications.settings(self.store);notifications.save_settings(self.store,{**previous,'events':[]},previous)
        with mock.patch.object(self.store,'totals',side_effect=AssertionError('Do not scan usage')):self.worker.poll()
        self.assertTrue(notifications.enqueue(self.store,'test','Fixture'))
        with mock.patch('nara.notifications.send') as send:self.worker.deliver();send.assert_called_once()
