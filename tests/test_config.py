import os
from pathlib import Path
import unittest
from unittest.mock import patch

from teamworker.config import Config, load_config


class ConfigTest(unittest.TestCase):
    def test_only_explicit_required_ids(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_GROUP_ID": "-100",
                                     "TELEGRAM_OWNER_ID": "42"}, clear=True):
            cfg = load_config()
            self.assertEqual(cfg.group_id, -100)
            self.assertEqual(cfg.owner_id, 42)
            self.assertEqual(cfg.compact_tokens, 200_000)

    def test_cannot_override_session_routing_in_cli(self):
        cfg = Config("secret", -100, 42, Path("/workspace"))
        with patch.dict(os.environ, {"PI_ARGS": "--session /other/session"}):
            with self.assertRaises(ValueError):
                cfg.pi_args()

    def test_pi_args_quoted_values(self):
        cfg = Config("secret", -100, 42, Path("/workspace"))
        with patch.dict(os.environ, {"PI_ARGS": '--model "provider/model" --thinking low'}):
            self.assertEqual(cfg.pi_args()[-4:], ["--model", "provider/model", "--thinking", "low"])

    def test_flags_cannot_be_smuggled_in_as_values(self):
        cfg = Config("secret", -100, 42, Path("/workspace"))
        with patch.dict(os.environ, {"PI_ARGS": "--model --no-session"}):
            with self.assertRaises(ValueError):
                cfg.pi_args()
