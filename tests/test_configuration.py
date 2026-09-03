"""Validate configuration policies and reject typos before model calls."""

import tempfile
import unittest
from pathlib import Path

from configuration import load_config


class ConfigurationTests(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(text, encoding="utf-8")
            return load_config(path)

    def test_assume_requires_currency(self):
        with self.assertRaisesRegex(ValueError, "currency is required"):
            self.load('[currency.unqualified_dollar]\naction="assume"')

    def test_reject_does_not_require_currency(self):
        config = self.load('[currency.unqualified_dollar]\naction="reject"')
        self.assertEqual(config.currency.unqualified_dollar.action, "reject")

    def test_reject_can_leave_currency_setting_in_place(self):
        config = self.load('[currency.unqualified_dollar]\naction="reject"\ncurrency="USD"')
        self.assertEqual(config.currency.unqualified_dollar.action, "reject")

    def test_settings_are_loaded(self):
        config = self.load('[model]\nname="other-model"\nreasoning_effort="medium"\ntimeout_seconds=20\n'
                           '[batch]\nworkers=2\n[currency.unqualified_dollar]\naction="assume"\ncurrency="CAD"')
        self.assertEqual(config.model.name, "other-model")
        self.assertEqual(config.model.reasoning_effort, "medium")
        self.assertEqual(config.model.timeout_seconds, 20)
        self.assertEqual(config.batch.workers, 2)
        self.assertEqual(config.currency.unqualified_dollar.currency, "CAD")

    def test_invalid_settings_fail(self):
        for text in ('[currency.unqualified_dollar]\naction="guess"',
                     '[currency.unqualified_dollar]\naction="assume"\ncurrency="dollars"',
                     '[batch]\nworkers=0', '[batch]\nworkers=true', '[batch]\nworker=4',
                     '[model]\ntimeout_seconds=-1', '[model]\nreasoning_effort="none"',
                     '[model]\nname=" "', 'not valid TOML'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load(text)

    def test_missing_config_fails(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, "Cannot load"):
            load_config(Path(directory) / "missing.toml")
