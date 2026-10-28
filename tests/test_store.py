from pathlib import Path
import tempfile
import unittest

from teamworker.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "group.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def add(self, mid, text="hello", requested=False):
        return self.store.add({"message_id": mid, "text": text}, requested)

    def test_duplicate_update_does_not_repeat_request(self):
        seq = self.add(1, requested=True)
        self.assertIsNone(self.add(1, requested=True))
        self.assertEqual(self.store.queued(), [seq])

    def test_recent_context_and_persistent_full_history(self):
        first = self.add(1, "x" * 1000)
        second = self.add(2, "small")
        request = self.add(3, requested=True)
        context, omitted = self.store.context(request, 200)
        self.assertTrue(omitted)
        self.assertEqual([x["message_id"] for x in context], [2])
        self.assertEqual(self.store.get(first)["text"], "x" * 1000)
        self.store.set("cursor", second)
        self.assertEqual(self.store.context(request, 200), ([], False))

    def test_restart_restores_queue_not_inflight_actions(self):
        first = self.add(1, requested=True)
        second = self.add(2, requested=True)
        self.store.status(first, "running")
        self.store.set("session", "/persistent/session.jsonl")
        self.store.db.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.interrupt_running(), 1)
        self.assertEqual(self.store.queued(), [second])
        self.assertEqual(self.store.state("session"), "/persistent/session.jsonl")

    def test_stop_keeps_journal(self):
        self.add(1, requested=True)
        self.store.clear_queue()
        self.assertEqual(self.store.queued(), [])
        self.assertEqual(self.store.latest(), 1)
