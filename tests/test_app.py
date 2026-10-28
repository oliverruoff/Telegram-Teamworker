import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from telegram import Chat, Message, Update, User

from teamworker.app import Teamworker
from teamworker.config import Config
from test_messages import message


class AppTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bot = Teamworker(Config("123:test", -100, 99, Path(self.temp.name)))
        self.bot.username = "teamworker"
        self.bot.send = AsyncMock()
        self.bot.pi = AsyncMock()
        self.bot.pi.get_state.return_value = {}

    async def asyncTearDown(self):
        await self.bot.cancel_ui()
        self.bot.store.db.close()
        self.temp.cleanup()

    async def update(self, msg):
        await self.bot.on_update(Update(1, message=msg), None)

    async def test_silent_group_history_no_model_call(self):
        await self.update(message("Team decision: use Python"))
        self.assertEqual(self.bot.store.latest(), 1)
        self.assertTrue(self.bot.queue.empty())
        self.bot.send.assert_not_called()
        self.bot.pi.prompt_and_wait.assert_not_called()

    async def test_only_mentions_enqueue_and_all_humans_allowed(self):
        await self.update(message("@teamworker help", mention=True, user_id=123))
        self.assertEqual(await self.bot.queue.get(), ("group", 1))
        self.bot.send.assert_not_called()

    async def test_foreign_group_and_private_nonowner_ignored(self):
        await self.update(message("@teamworker help", mention=True, chat_id=-200))
        msg = Message(2, datetime.now(timezone.utc), Chat(42, "private"),
                      from_user=User(42, "Someone", False), text="/connect")
        await self.update(msg)
        self.assertEqual(self.bot.store.latest(), 0)
        self.assertTrue(self.bot.queue.empty())
        self.bot.send.assert_not_called()

    async def test_private_owner_cannot_submit_freeform_agent_task(self):
        msg = Message(2, datetime.now(timezone.utc), Chat(99, "private"),
                      from_user=User(99, "Owner", False), text="Write code for me")
        await self.update(msg)
        self.assertTrue(self.bot.queue.empty())
        self.bot.send.assert_awaited_once()
        self.bot.pi.prompt_and_wait.assert_not_called()

    async def test_group_slash_command_not_forwarded_as_admin(self):
        await self.update(message("/connect"))
        self.assertTrue(self.bot.queue.empty())
        await self.update(message("@teamworker /connect", mention=True, mid=2))
        self.assertEqual(await self.bot.queue.get(), ("group", 2))

    async def test_admin_command_normalized_not_prompted(self):
        await self.bot.admin("/MODEL@teamworker")
        self.assertEqual(await self.bot.queue.get(), ("admin", "/model"))

    async def test_only_original_requester_can_answer_group_ui(self):
        self.bot.active = "group"
        self.bot.request = {"sender": {"user_id": 42}}
        self.bot.pending_ui = {"id": "one", "method": "confirm", "target": -100}
        await self.update(message("@teamworker yes", mention=True, user_id=7))
        self.assertIsNotNone(self.bot.pending_ui)
        self.bot.pi.extension_ui_response.assert_not_called()
        await self.update(message("@teamworker ja", mention=True, user_id=42, mid=2))
        self.bot.pi.extension_ui_response.assert_awaited_once_with({"id": "one", "confirmed": True})

    async def test_compaction_message_only_on_success(self):
        await self.bot.on_pi_event({"type": "compaction_end", "aborted": True})
        await self.bot.on_pi_event({"type": "compaction_end", "errorMessage": "secret error"})
        self.bot.send.assert_not_called()
        await self.bot.on_pi_event({"type": "compaction_end", "result": {"summary": "private"}})
        self.bot.send.assert_awaited_once_with(-100, "compacted.")

    async def test_configuration_notifications_never_reach_group(self):
        self.bot.active = "admin"
        await self.bot.on_pi_event({"type": "extension_ui_request", "method": "notify", "message": "OAuth code"})
        self.bot.send.assert_awaited_once_with(99, "OAuth code")

    async def test_small_model_compacts_before_200k(self):
        async def usage():
            self.bot.usage = {"tokens": 20_000, "contextWindow": 32_768}
        self.bot.context_usage = usage
        self.bot.pi.send.return_value = {"success": True}
        await self.bot.maintain_context()
        self.bot.pi.send.assert_awaited_once_with({"type": "compact"}, timeout=None)

    async def test_failed_provider_attempt_does_not_poison_successful_retry(self):
        self.bot.active = "group"
        await self.bot.on_pi_event({"type": "message_end", "message": {
            "role": "assistant", "stopReason": "error", "content": [{"type": "text", "text": "secret"}]}})
        self.assertTrue(self.bot.provider_error)
        self.assertEqual(self.bot.answer, "")
        await self.bot.on_pi_event({"type": "message_end", "message": {
            "role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "Done"}]}})
        self.assertFalse(self.bot.provider_error)
        self.assertEqual(self.bot.answer, "Done")

    async def test_missing_admin_extension_fails_closed(self):
        self.bot.pi.send.return_value = {"success": True, "data": {"commands": []}}
        with self.assertRaises(RuntimeError):
            await self.bot.verify_commands()
        self.bot.pi.prompt_and_wait.assert_not_called()

    async def test_cannot_reuse_team_workspace_for_other_group(self):
        with self.assertRaises(ValueError):
            Teamworker(Config("123:test", -200, 99, Path(self.temp.name)))

    async def test_missing_saved_session_does_not_silently_reset(self):
        self.bot.store.set("session", str(Path(self.temp.name) / "missing.jsonl"))
        with self.assertRaises(RuntimeError):
            await self.bot.restore_session()
        self.bot.pi.new_session.assert_not_called()

    async def test_new_background_is_budgeted_before_submission(self):
        async def usage():
            self.bot.usage = {"tokens": 190_000, "contextWindow": 1_000_000}
        self.bot.context_usage = usage
        self.bot.pi.send.return_value = {"success": True}
        await self.bot.maintain_context(extra_bytes=15_000)
        self.bot.pi.send.assert_awaited_once_with({"type": "compact"}, timeout=None)
