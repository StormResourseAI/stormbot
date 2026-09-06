"""The guard has to fail closed on anything it does not positively recognize."""

from __future__ import annotations

import unittest

from stormbot.governance import ProductionDatabaseError, assert_test_database
from stormbot.governance.db_guard import is_test_database

TEST_ENV = {"STORMBOT_TEST_MODE": "1"}
PRODUCTION_ENV: dict[str, str] = {}


class RecognitionTests(unittest.TestCase):
    def test_disposable_targets_are_recognized(self):
        for url in (
            "sqlite:///:memory:",
            "file::memory:?cache=shared",
            "sqlite:///./var/stormbot_test.db",
            "postgresql://localhost:5432/stormbot_test",
            "postgresql://127.0.0.1/test_stormbot",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_test_database(url))

    def test_production_shaped_targets_are_not_recognized(self):
        for url in (
            "sqlite:///./stormbot.db",
            "postgresql://db.internal.example.com:5432/stormbot_test",
            "postgresql://localhost:5432/stormbot",
            "mysql://localhost/production",
            "",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_test_database(url))

    def test_a_remote_host_is_never_test_state_even_when_named_test(self):
        """Naming a production host's database 'test' does not make it test state."""
        self.assertFalse(is_test_database("postgresql://prod-primary.example.com/stormbot_test"))


class GuardTests(unittest.TestCase):
    def test_a_test_process_cannot_bind_to_production_state(self):
        with self.assertRaises(ProductionDatabaseError):
            assert_test_database("sqlite:///./stormbot.db", env=TEST_ENV)

    def test_a_test_process_may_bind_to_disposable_state(self):
        url = "sqlite:///:memory:"

        self.assertEqual(assert_test_database(url, env=TEST_ENV), url)

    def test_the_error_message_never_echoes_the_connection_string(self):
        """Connection strings carry passwords; the error is read by everyone."""
        url = "postgresql://stormbot:hunter2@db.example.com:5432/stormbot"

        with self.assertRaises(ProductionDatabaseError) as raised:
            assert_test_database(url, env=TEST_ENV)

        self.assertNotIn("hunter2", str(raised.exception))
        self.assertNotIn("db.example.com", str(raised.exception))

    def test_outside_a_test_process_the_guard_is_a_passthrough(self):
        """Production code paths are unaffected, so nobody has a reason to route around it."""
        url = "postgresql://db.example.com:5432/stormbot"

        self.assertEqual(assert_test_database(url, env=PRODUCTION_ENV), url)

    def test_this_very_test_run_is_recognized_as_a_test_process(self):
        from stormbot.governance.db_guard import under_test

        self.assertTrue(under_test({"UNITTEST_RUNNING": "1"}))


if __name__ == "__main__":
    unittest.main()
