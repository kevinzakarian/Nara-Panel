import tempfile
import json
import unittest
from unittest import mock
from nara import __version__
from nara.store import Store
from nara.updates import UpdateChecker, version, panel_version, fetch, CORE_URL, PANEL_URL, MAX_RESPONSE


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.checker = UpdateChecker(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_each_entry_checks_again_and_last_result_survives_restart(self):
        with mock.patch('nara.updates.fetch', side_effect=[{'tag_name':'v9.0.0'}, {'tag_name':'v9.0.1'}]*2) as fetch:
            self.checker.check(100000)
            UpdateChecker(self.store).check(100001)
            self.assertEqual(fetch.call_count, 4)
            self.assertEqual(fetch.call_args_list[0].args, (PANEL_URL,))
            self.assertTrue(PANEL_URL.endswith("/releases/latest"))
            result = self.checker.status('sing-box version 1.14.3')
            self.assertTrue(result['panel']['available'])
            self.assertTrue(result['core']['available'])
            self.assertEqual(result['panel']['installed'], __version__)
        with mock.patch('nara.updates.fetch', side_effect=[{'tag_name':'v'+__version__}, {'tag_name':'v1.14.3'}]) as fetch:
            self.checker.check(186401)
            self.assertEqual(fetch.call_count, 2)
            self.assertFalse(self.checker.status('sing-box version 1.14.3')['core']['available'])

    def test_failure_keeps_last_success_and_does_not_claim_up_to_date(self):
        with mock.patch('nara.updates.fetch', side_effect=[{'tag_name':'v9.0.0'}, {'tag_name':'v9.0.0'}]):
            self.checker.check(100000)
        with mock.patch('nara.updates.fetch', side_effect=OSError('offline')):
            self.checker.check(186401)
        result = self.checker.status('sing-box version 1.14.3')
        self.assertTrue(result['core']['available'])
        self.assertTrue(result['core']['error'])
        self.assertEqual(result['core']['checked_at'], 100000)
        self.assertEqual(result['core']['latest'], '9.0.0')

    def test_components_fail_independently_and_prereleases_are_not_advertised(self):
        with mock.patch('nara.updates.fetch', side_effect=[OSError(), {'tag_name':'v1.15.0-alpha.1', 'prerelease':True}]):
            self.checker.check(100000)
        result = self.checker.status('sing-box version 1.14.3')
        self.assertFalse(result['core']['known'])
        self.assertFalse(result['panel']['available'])
        self.assertTrue(result['core']['error'])

    def test_stable_semantic_version_parsing(self):
        self.assertEqual(version('sing-box version 1.14.3'), (1,14,3))
        self.assertEqual(version('v1.20.0'), (1,20,0))
        self.assertIsNone(version('1.15.0-rc.1'))
        self.assertIsNone(version('unknown'))
        self.assertIsNone(version('1.14.4.1'))

    def test_panel_revisions_compare_numerically_and_core_updates_stay_separate(self):
        self.assertEqual(panel_version('1.14.4'), panel_version('1.14.4.0'))
        self.assertGreater(panel_version('1.14.4.10'), panel_version('1.14.4.9'))
        self.assertGreater(panel_version('1.14.5'), panel_version('1.14.4.99'))
        for invalid in ('1.14.4.2-rc.1', '1.14.4.2.1', '1.14.4.2\n', '1.14.4.1234567'):
            self.assertIsNone(panel_version(invalid))
        with mock.patch('nara.updates.fetch', side_effect=[{'tag_name':'v1.14.4.2'}, {'tag_name':'v1.14.4'}]):
            self.checker.check()
        with mock.patch('nara.updates.__version__', '1.14.4.1'):
            status = self.checker.status('sing-box version 1.14.4')
        self.assertTrue(status['panel']['available'])
        self.assertEqual(status['panel']['latest'], '1.14.4.2')
        self.assertFalse(status['core']['available'])

    def test_release_payload_with_many_assets_is_accepted_but_response_is_bounded(self):
        response=mock.MagicMock()
        response.__enter__.return_value=response
        response.url=CORE_URL
        response.read.return_value=json.dumps({'tag_name':'v1.14.3','padding':'x'*300000}).encode()
        with mock.patch('nara.updates.open_https',return_value=response):
            self.assertEqual(fetch(CORE_URL)['tag_name'],'v1.14.3')
        response.read.return_value=b'x'*(MAX_RESPONSE+1)
        with mock.patch('nara.updates.open_https',return_value=response),self.assertRaisesRegex(ValueError,'too large'):
            fetch(CORE_URL)
