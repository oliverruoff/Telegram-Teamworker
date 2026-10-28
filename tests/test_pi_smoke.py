"""Optional real pi test, no provider credentials or model requests required."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from teamworker.pi_rpc import PiRPC


@unittest.skipUnless(os.getenv("PI_TEST_COMMAND"), "set PI_TEST_COMMAND to run real pi RPC smoke test")
class PiSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_extensions_context_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = root / "agent"
            agent.mkdir()
            (agent / "extensions").symlink_to(Path(__file__).resolve().parents[1] / "teamworker/extensions")
            (agent / "settings.json").write_text(json.dumps({"defaultProjectTrust": "never"}))
            events = []

            async def event(record):
                events.append(record)
                if record.get("type") == "extension_ui_request" and record.get("method") in {"select", "confirm", "input"}:
                    await rpc.extension_ui_response({"id": record["id"], "cancelled": True})

            with patch.dict(os.environ, {"PI_CODING_AGENT_DIR": str(agent),
                                         "OPENROUTER_API_KEY": "",
                                         "OPENAI_API_KEY": "test-key-never-used-for-a-request"}):
                rpc = PiRPC(os.environ["PI_TEST_COMMAND"], ["--mode", "rpc", "--session-dir", str(root / "sessions"),
                                                         "--provider", "openai", "--model", "gpt-4.1"], str(root), event)
                await rpc.start()
                try:
                    state = await rpc.get_state()
                    self.assertIn("sessionId", state)
                    commands = await rpc.send({"type": "get_commands"})
                    names = {c["name"] for c in commands["data"]["commands"]}
                    self.assertTrue({"connect", "model", "thinking", "reload", "teamworker-context"} <= names)
                    await asyncio.wait_for(rpc.prompt_and_wait("/teamworker-context"), 30)
                    self.assertTrue(any(e.get("message", "").startswith("TW_CONTEXT:") for e in events))
                    settings = json.loads((agent / "settings.json").read_text())
                    budget = settings["compaction"]["modelOverrides"]["openai/gpt-4.1"]
                    window = state["model"]["contextWindow"]
                    threshold = min(200000, max(4096, window - 16384))
                    self.assertEqual(budget["reserveTokens"], window - threshold)
                    self.assertEqual(budget["keepRecentTokens"], min(20000, threshold // 4))
                    await asyncio.wait_for(rpc.prompt_and_wait("/model openai/gpt-4.1"), 30)
                    await asyncio.wait_for(rpc.prompt_and_wait("/thinking off"), 30)
                    await asyncio.wait_for(rpc.prompt_and_wait("/connect openrouter", timeout=None), 30)
                    self.assertTrue(any(e.get("method") == "input" for e in events))
                    await asyncio.wait_for(rpc.prompt_and_wait("/reload"), 30)
                    await rpc.new_session()
                    self.assertFalse(any(e.get("type") == "extension_error" for e in events), events)
                    self.assertFalse(any(e.get("type") == "agent_start" for e in events), "admin command triggered a model run")
                finally:
                    await rpc.stop()
