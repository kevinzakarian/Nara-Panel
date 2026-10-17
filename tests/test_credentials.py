import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from nara.__main__ import main
from nara.install_summary import administrator, entry_urls, main as summary_main, show_summary
from nara.store import Store, password_hash, password_matches


class CredentialsTests(unittest.TestCase):
    def setUp(self):
        self.previous_umask = os.umask(0o077)

    def tearDown(self):
        os.umask(self.previous_umask)

    def invoke(self, directory, command="init", username=None, output=None, answers=None):
        arguments = ["nara", command, "--data", str(directory)]
        if username is not None:
            arguments += ["--username", username]
        if output:
            arguments += ["--credentials-file", str(output)]
        capture = io.StringIO()
        with mock.patch("sys.argv", arguments), mock.patch("builtins.input", return_value="PanelOwner") as prompt, \
                mock.patch("getpass.getpass", side_effect=answers or ["fixture-password-123"] * 2), \
                contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
            main()
        return capture.getvalue(), prompt

    def test_init_prompts_custom_username_hashes_password_and_hands_off_privately(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "credentials.json"
            text, prompt = self.invoke(directory, output=output)
            prompt.assert_called_once()
            admin = Store(directory).get("admin")
            self.assertEqual(admin["username"], "PanelOwner")
            self.assertTrue(password_matches("fixture-password-123", admin["password"]))
            self.assertNotIn("fixture-password-123", text)
            self.assertEqual(json.loads(output.read_text()), {"username": "PanelOwner", "password": "fixture-password-123"})
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_explicit_username_and_password_reset_preserve_existing_custom_name(self):
        with tempfile.TemporaryDirectory() as directory:
            _, prompt = self.invoke(directory, username="Owner_42")
            prompt.assert_not_called()
            _, prompt = self.invoke(directory, "reset-password", answers=["changed-password-123"] * 2)
            prompt.assert_not_called()
            admin = Store(directory).get("admin")
            self.assertEqual(admin["username"], "Owner_42")
            self.assertTrue(password_matches("changed-password-123", admin["password"]))

    def test_interactive_invalid_username_is_reprompted_and_enter_keeps_admin_default(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch("sys.argv", ["nara", "init", "--data", directory]), \
                mock.patch("builtins.input", side_effect=["bad name", ""]) as prompt, \
                mock.patch("getpass.getpass", return_value="fixture-password-123"), contextlib.redirect_stdout(io.StringIO()):
            main()
            self.assertEqual(prompt.call_count, 2)
            self.assertEqual(Store(directory).get("admin")["username"], "admin")

    def test_bad_usernames_and_password_confirmation_never_initialize_admin(self):
        for username, answers in [("bad\nname", None), ("", None), ("x" * 65, None), ("Owner", ["fixture-password-123", "different-password"] )]:
            with self.subTest(username=username), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(SystemExit):
                    self.invoke(directory, username=username, answers=answers)
                self.assertIsNone(Store(directory).get("admin"))

    def test_credentials_handoff_does_not_overwrite_an_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "credentials.json"; output.write_text("keep")
            with self.assertRaises(FileExistsError):
                self.invoke(directory, output=output)
            self.assertEqual(output.read_text(), "keep")
            self.assertIsNone(Store(directory).get("admin"))


class SummaryTests(unittest.TestCase):
    settings = {"NARA_PORT":"10000", "NARA_WEB_PATH":"/Panel", "NARA_SUB_PORT":"10001", "NARA_SUB_PATH":"/Sub"}

    def test_summary_reads_database_as_its_owner_and_parent_does_not_open_store(self):
        paths = mock.Mock()
        with mock.patch('nara.install_summary.needs_database_owner', return_value=True), \
                mock.patch('nara.install_summary.database_as_owner', return_value={'username':'Owner'}) as owner_read, \
                mock.patch('nara.install_summary.Store') as store:
            self.assertEqual(administrator(paths), {'username':'Owner'})
            store.assert_not_called()
            owner_read.assert_called_once()

    def test_terminal_summary_colors_actual_url_username_and_password(self):
        output = io.StringIO(); output.isatty = lambda: True
        with mock.patch.dict(os.environ, {"TERM":"xterm"}), mock.patch.dict(os.environ) as environment:
            environment.pop("NO_COLOR", None)
            show_summary(self.settings, {"username":"Owner"}, {"username":"Owner", "password":"fixture-password-123"},
                         stream=output, addresses=["10.0.0.1", "94.159.98.242"])
        text = output.getvalue()
        self.assertIn("\x1b[1;36m  Panel URL: http://94.159.98.242:10000/Panel/", text)
        self.assertIn("\x1b[1;32m  Username: Owner", text)
        self.assertIn("\x1b[1;33m  Password: fixture-password-123", text)

    def test_upgrade_summary_never_treats_hash_as_password_and_plain_output_is_readable(self):
        output = io.StringIO()
        show_summary(self.settings, {"username":"Owner", "password":"private-hash"}, stream=output, addresses=[])
        text = output.getvalue()
        self.assertIn("Unchanged", text)
        self.assertNotIn("private-hash", text)
        self.assertNotIn("\x1b", text)
        self.assertIn("YOUR_SERVER_IP", text)

    def test_password_cannot_inject_terminal_escape_sequences_and_no_color_is_respected(self):
        output = io.StringIO(); output.isatty = lambda: True
        with mock.patch.dict(os.environ, {"TERM":"xterm", "NO_COLOR":""}):
            show_summary(self.settings, {"username":"Owner"}, {"username":"Owner", "password":"fixture\x1b[31m-value"},
                         stream=output, addresses=[])
        self.assertNotIn("\x1b", output.getvalue())
        self.assertIn("\\x1b[31m", output.getvalue())

    def test_summary_uses_saved_https_ports_and_ipv6_brackets(self):
        self.assertEqual(entry_urls(self.settings, addresses=["2001:db8::1"])[0], "http://[2001:db8::1]:10000/Panel/")
        self.assertEqual(entry_urls(self.settings, {"url":"https://panel.example:8443/Panel/", "subscription_url":"https://sub.example:9443/Sub/"}),
                         ("https://panel.example:8443/Panel/", "https://sub.example:9443/Sub/"))

    def test_summary_deletes_handoff_and_never_leaks_password_to_redirected_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root / "panel.env"; env.write_text("\n".join(k+"="+v for k,v in self.settings.items()))
            secret = root / "login.json"; secret.write_text(json.dumps({"username":"Owner", "password":"fixture-private-password"}))
            capture = io.StringIO()
            with mock.patch.dict(os.environ, {"NARA_SETUP_ENV":str(env), "NARA_SETUP_CREDENTIALS":str(secret)}), \
                    mock.patch("nara.install_summary.administrator", return_value={"username":"Owner"}), \
                    mock.patch("nara.install_summary.open", side_effect=OSError("no tty")), \
                    contextlib.redirect_stdout(capture):
                summary_main()
            self.assertFalse(secret.exists())
            self.assertNotIn("fixture-private-password", capture.getvalue())
            self.assertNotIn("private-hash", capture.getvalue())
            self.assertIn("Owner", capture.getvalue())
