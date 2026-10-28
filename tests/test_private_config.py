import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.scheduler.cli import provider_for
from src.scheduler.config import read_private_config


class PrivateConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / ".env"

    def test_file_config_is_explicit_and_does_not_mutate_process(self):
        self.path.write_text('# local\nLLM_API_KEY="test-placeholder"\nLLM_MODEL=chosen-model\nLLM_BASE_URL=https://example.invalid/v1\n', encoding="utf-8")
        with patch.dict(os.environ, {"LLM_MODEL": "environment-model"}, clear=True):
            provider = provider_for("live", self.path)
            self.assertEqual(provider.model, "chosen-model")
            self.assertEqual(provider.key, "test-placeholder")
            self.assertEqual(provider.url, "https://example.invalid/v1/chat/completions")
            self.assertEqual(os.environ["LLM_MODEL"], "environment-model")
            self.assertNotIn("LLM_API_KEY", os.environ)

    def test_invalid_private_config_errors_do_not_echo_values(self):
        for content in ("UNKNOWN=secret-fixture", "LLM_API_KEY=secret-fixture\nLLM_API_KEY=secret-fixture", 'LLM_API_KEY="secret-fixture'):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError) as raised:
                    read_private_config(self.path)
                self.assertNotIn("secret-fixture", str(raised.exception))

    def test_private_config_does_not_execute_shell_expressions(self):
        self.path.write_text("LLM_MODEL=$(expression-is-data)\nLLM_API_KEY='test=placeholder'\n", encoding="utf-8")
        settings = read_private_config(self.path)
        self.assertEqual(settings["LLM_MODEL"], "$(expression-is-data)")
        self.assertEqual(settings["LLM_API_KEY"], "test=placeholder")

    def test_mock_never_loads_private_config_or_silently_uses_it(self):
        with self.assertRaises(ValueError):
            provider_for("mock", self.path)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            provider_for("live")
