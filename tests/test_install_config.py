import re
import tempfile
import unittest
from pathlib import Path
from nara.install_config import ask_configuration, normalize_web_path, random_web_path, read_env


class InstallConfigTests(unittest.TestCase):
    def test_enter_defaults_to_eight_mixed_case_letters_and_port_10000(self):
        answers = iter(["", "", "SubPath", "10001"])
        result = ask_configuration(lambda _: next(answers), available=lambda p: True)
        self.assertEqual(result["NARA_PORT"], "10000")
        self.assertRegex(result["NARA_WEB_PATH"], r"^/[A-Za-z]{8}$")
        self.assertRegex(result["NARA_WEB_PATH"], r"[a-z]")
        self.assertRegex(result["NARA_WEB_PATH"], r"[A-Z]")

    def test_custom_path_and_port(self):
        answers = iter(["MyPanel", "12345", "MySubscriptions", "12346"])
        self.assertEqual(ask_configuration(lambda _: next(answers), available=lambda p: True),
                         {"NARA_WEB_PATH": "/MyPanel", "NARA_PORT": "12345", "NARA_SUB_PATH": "/MySubscriptions", "NARA_SUB_PORT": "12346"})

    def test_invalid_and_occupied_values_are_reprompted(self):
        answers = iter(["bad/path", "SafePath", "abc", "0", "65536", "10085", "12000", "13000", "SubPath", "13001"])
        errors = []
        result = ask_configuration(lambda _: next(answers), errors.append, available=lambda p: p != 12000)
        self.assertEqual(result, {"NARA_WEB_PATH": "/SafePath", "NARA_PORT": "13000", "NARA_SUB_PATH": "/SubPath", "NARA_SUB_PORT": "13001"})
        self.assertEqual(len(errors), 6)

    def test_existing_entry_defaults_are_retained(self):
        answers = iter(["", "", "SubPath", "10001"])
        result = ask_configuration(lambda _: next(answers), available=lambda p: True,
                                   defaults={"NARA_WEB_PATH": "/Existing", "NARA_PORT": "12300"})
        self.assertEqual(result, {"NARA_WEB_PATH": "/Existing", "NARA_PORT": "12300", "NARA_SUB_PATH": "/SubPath", "NARA_SUB_PORT": "10001"})

    def test_path_rejects_injection_traversal_and_unicode(self):
        for path in ("../admin", "abc/def", "ab?c", "a b", "a;id", "a\nPORT=1", "پنل", "a" * 65):
            with self.subTest(path=path), self.assertRaises(ValueError):
                normalize_web_path(path)
        self.assertEqual(normalize_web_path("/MyPanel/"), "/MyPanel")

    def test_generated_paths_have_both_cases(self):
        for _ in range(100):
            path = random_web_path()
            self.assertTrue(re.fullmatch(r"/[A-Za-z]{8}", path))
            self.assertTrue(any(c.isupper() for c in path) and any(c.islower() for c in path))

    def test_env_reader_does_not_execute_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "panel.env"
            path.write_text("# comment\nNARA_PORT=10000\nNARA_WEB_PATH=/SomePath\n")
            self.assertEqual(read_env(path), {"NARA_PORT": "10000", "NARA_WEB_PATH": "/SomePath"})

    def test_both_paths_random_and_subscription_default_port_distinct(self):
        answers = iter(['', '', '', ''])
        result = ask_configuration(lambda _: next(answers), available=lambda p: True)
        self.assertEqual(result['NARA_SUB_PORT'], '10001')
        self.assertNotEqual(result['NARA_WEB_PATH'], result['NARA_SUB_PATH'])
        self.assertRegex(result['NARA_SUB_PATH'], r'^/[A-Za-z]{8}$')

    def test_sub_path_and_port_conflicts_are_reprompted(self):
        answers = iter(['Panel', '10001', 'Panel', 'Subscriptions', '10001', '10085', '10002'])
        errors = []
        result = ask_configuration(lambda _: next(answers), errors.append, available=lambda p: True)
        self.assertEqual(result['NARA_SUB_PORT'], '10002')
        self.assertEqual(len(errors), 3)

    def test_upgrade_prompts_only_for_missing_subscription(self):
        questions = []
        answers = iter(['Download', '10001'])
        result = ask_configuration(lambda q: (questions.append(q), next(answers))[1], available=lambda p: True,
            defaults={'NARA_WEB_PATH':'/KeepPanel', 'NARA_PORT':'10000'}, keep_panel=True)
        self.assertEqual(len(questions), 2)
        self.assertTrue(all('Subscription' in q for q in questions))
        self.assertEqual(result['NARA_WEB_PATH'], '/KeepPanel')
