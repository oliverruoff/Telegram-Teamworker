"""One group, one pi process, one ordered worker. No autonomous chat turns."""

import asyncio
from contextlib import suppress
import json
import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from .config import Config
from .messages import mention_spans, prompt, public_answer, record, text_of, without_mention
from .pi_rpc import PiRPC
from .store import Store
from .telegram_format import format_for_telegram

log = logging.getLogger(__name__)
ADMIN_COMMANDS = {"/connect", "/model", "/thinking", "/reload"}
HELP = ("Administration: /connect [openrouter|openai-codex], /model, /thinking, "
        "/reload, /status, /new, /stop, /cancel.\n"
        "Normal tasks belong in the configured group and require @mention. "
        "Install skills in /workspace/skills; then /reload.")


class Teamworker:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.data.mkdir(parents=True, exist_ok=True)
        (cfg.workspace / "skills").mkdir(exist_ok=True)
        self.store = Store(cfg.data / "group.sqlite3")
        if self.store.state("group_id", cfg.group_id) != cfg.group_id:
            self.store.db.close()
            raise ValueError("Workspace belongs to another group; use a separate workspace")
        self.store.set("group_id", cfg.group_id)
        self.pi = PiRPC("pi", cfg.pi_args(), str(cfg.workspace), self.on_pi_event)
        self.app = Application.builder().token(cfg.token).build()
        self.app.add_handler(MessageHandler(filters.ALL, self.on_update))
        self.app.add_handler(CallbackQueryHandler(self.on_callback))
        self.queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
        self.username = ""
        self.active = ""
        self.request: dict | None = None
        self.pending_ui: dict | None = None
        self.pending_timeout: asyncio.Task | None = None
        self.usage: dict = {}
        self.answer = ""
        self.provider_error = False
        self.context_failed = False
        self.stopped = False
        self.worker_task: asyncio.Task | None = None

    async def start(self, _app: Application) -> None:
        self.username = (await self.app.bot.get_me()).username
        interrupted = self.store.interrupt_running()
        await self.pi.start()
        await self.verify_commands()
        await self.restore_session()
        await self.remember_session()
        for seq in self.store.queued():
            self.queue.put_nowait(("group", seq))
        self.worker_task = asyncio.create_task(self.worker())
        if interrupted:
            await self.send(self.cfg.owner_id,
                            f"{interrupted} request(s) interrupted by restart; not repeated automatically. "
                            "Check external actions before asking again.")
        log.info("Teamworker ready for configured group")

    async def shutdown(self, _app: Application) -> None:
        if self.worker_task:
            self.worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker_task
        await self.cancel_ui()
        await self.pi.stop()
        self.store.db.close()

    async def remember_session(self) -> None:
        state = await self.pi.get_state()
        if state.get("sessionFile") and Path(state["sessionFile"]).is_file():
            self.store.set("session", state["sessionFile"])

    async def restore_session(self) -> None:
        saved = self.store.state("session")
        if saved:
            # Pi treats nonexistent/empty files as fresh sessions; don't silently
            # lose team context when a persisted checkpoint should exist.
            path = Path(saved)
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError("Saved group session is missing or empty")
            await self.pi.switch_session(saved)
        else:
            await self.pi.new_session()

    async def verify_commands(self) -> None:
        response = await self.pi.send({"type": "get_commands"})
        names = {c["name"] for c in (response or {}).get("data", {}).get("commands", [])}
        required = {c.removeprefix("/") for c in ADMIN_COMMANDS} | {"teamworker-context"}
        if not required <= names:
            raise RuntimeError("Required pi extensions are not loaded; refusing to forward commands")

    async def on_update(self, update: Update, _context) -> None:
        # Edited messages never execute a task again; channels/bot messages cannot
        # impersonate a human requester. Other groups and private chats are ignored.
        msg = update.message
        if not msg:
            return
        private_owner = (msg.chat.type == "private" and msg.from_user and
                         msg.from_user.id == self.cfg.owner_id)
        if private_owner:
            await self.admin(text_of(msg))
            return
        if msg.chat_id != self.cfg.group_id or msg.chat.type not in {"group", "supergroup"}:
            return
        if msg.from_user and msg.from_user.is_bot and not msg.sender_chat:
            return
        requested = bool(mention_spans(msg, self.username)) and not msg.sender_chat
        data = record(msg)
        if requested:
            data["request_text"] = without_mention(msg, self.username)
        seq = self.store.add(data, requested)
        if not seq or not requested:
            return
        # In an interactive group dialog only the original requester may answer,
        # and only with a fresh @mention. No group callback buttons bypass this.
        if (self.pending_ui and self.active == "group" and self.request and
                data["sender"]["user_id"] == self.request["sender"]["user_id"]):
            await self.answer_ui(data["request_text"])
            self.store.status(seq, "done")
            return
        self.queue.put_nowait(("group", seq))

    async def admin(self, text: str) -> None:
        command = text.split(maxsplit=1)[0].split("@")[0].lower() if text.strip() else ""
        if command == "/cancel":
            await self.cancel_ui()
            await self.send(self.cfg.owner_id, "Cancelled.")
        elif command == "/stop":
            self.stopped = True
            self.store.clear_queue()
            while not self.queue.empty():
                self.queue.get_nowait()
                self.queue.task_done()
            await self.cancel_ui()
            if self.active:
                await self.pi.abort()
            await self.send(self.cfg.owner_id, "Stop requested; pending queue cleared.")
        elif self.pending_ui and self.active == "admin":
            await self.answer_ui(text)
        elif command in {"/start", "/help"}:
            await self.send(self.cfg.owner_id, HELP)
        elif command == "/status":
            await self.send(self.cfg.owner_id,
                            f"Active: {self.active or 'idle'}; queued: {self.queue.qsize()}; "
                            f"compaction target: {self.cfg.compact_tokens} tokens.")
        elif command == "/new":
            self.queue.put_nowait(("reset", self.store.latest()))
            await self.send(self.cfg.owner_id, "Session reset queued.")
        elif command in ADMIN_COMMANDS:
            # Normalize command suffix/case so it always resolves to a registered
            # command, never accidentally falls through to a model prompt.
            argument = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
            self.queue.put_nowait(("admin", command + (" " + argument if argument else "")))
        else:
            await self.send(self.cfg.owner_id, HELP)

    async def worker(self) -> None:
        while True:
            kind, value = await self.queue.get()
            self.active = kind
            self.stopped = False
            try:
                if not self.pi.running:
                    await self.pi.restart()
                    await self.verify_commands()
                    await self.restore_session()
                if kind == "reset":
                    await self.pi.new_session()
                    # A new pi session is lazy and may not have a file yet.
                    # Clear the old checkpoint so a restart cannot resurrect it.
                    self.store.set("session", None)
                    self.store.set("cursor", value)
                    await self.remember_session()
                    await self.send(self.cfg.owner_id, "New group session started.")
                elif kind == "admin":
                    # Whitelisted extension commands only, never free-form prompts.
                    await self.verify_commands()
                    await self.pi.prompt_and_wait(str(value), timeout=None)
                    await self.remember_session()
                else:
                    await self.process_request(int(value))
            except Exception:
                # Provider/transport errors may contain secrets: don't echo them.
                log.error("%s work failed; inspect provider configuration and connection", kind)
                with suppress(Exception):
                    if kind == "group":
                        self.store.status(int(value), "failed")
                        await self.send(self.cfg.group_id,
                                        "Request failed. Please try again or ask the operator to check setup.",
                                        reply_to=self.request.get("message_id") if self.request else None)
                    else:
                        await self.send(self.cfg.owner_id, "Operation failed. Check setup and try again.")
            finally:
                with suppress(Exception):
                    await self.cancel_ui()
                with suppress(Exception):
                    await self.remember_session()
                self.active = ""
                self.request = None
                self.queue.task_done()

    async def context_usage(self) -> None:
        self.usage = {}
        self.context_failed = False
        await self.verify_commands()
        await self.pi.prompt_and_wait("/teamworker-context")
        if self.context_failed or not self.usage:
            raise RuntimeError("Context configuration unavailable")

    async def maintain_context(self, extra_bytes: int = 0) -> None:
        await self.context_usage()
        window = self.usage.get("contextWindow", 0)
        tokens = self.usage.get("tokens")
        if not window:
            return
        threshold = min(self.cfg.compact_tokens, max(4096, window - self.cfg.reserve_tokens))
        if tokens is not None and tokens > 0 and tokens + extra_bytes >= threshold:
            result = await self.pi.send({"type": "compact"}, timeout=None)
            if not result or not result.get("success"):
                raise RuntimeError("Compaction failed")
            await self.context_usage()

    async def process_request(self, seq: int) -> None:
        self.store.status(seq, "running")
        self.request = self.store.get(seq)
        await self.context_usage()
        await self.download_attachment(self.request)
        if self.request.get("reply_to"):
            await self.download_attachment(self.request["reply_to"])
        self.store.update(seq, self.request)
        if self.stopped:
            self.store.status(seq, "stopped")
            return
        # UTF-8 bytes are a deliberately conservative proxy for text tokens.
        # Limit newly injected background separately from the existing pi context.
        window = self.usage.get("contextWindow") or 32_768
        budget = min(self.cfg.context_bytes, max(1024, window // 8))
        background, omitted = self.store.context(seq, budget)
        content = prompt(self.request, background, omitted, str(self.cfg.data / "group.sqlite3"))
        # pi checks existing history before adding a new user prompt. Make room
        # for the newly injected text too, using bytes as a conservative bound.
        await self.maintain_context(extra_bytes=len(content.encode("utf-8")))
        if self.stopped:
            self.store.status(seq, "stopped")
            return
        self.answer = ""
        self.provider_error = False
        typing = asyncio.create_task(self.typing())
        try:
            await self.pi.prompt_and_wait(content, timeout=None)
        finally:
            typing.cancel()
            with suppress(asyncio.CancelledError):
                await typing
        if self.stopped:
            self.store.status(seq, "stopped")
            return
        if self.provider_error:
            raise RuntimeError("Provider failed")
        if self.answer.strip():
            answer = public_answer(self.answer)
            if answer:
                await self.send(self.cfg.group_id, answer, reply_to=self.request["message_id"])
        self.store.set("cursor", max(seq, self.store.state("cursor", 0)))
        self.store.status(seq, "done")
        await self.remember_session()
        await self.maintain_context()

    async def download_attachment(self, data: dict) -> None:
        attachment = data.get("attachment")
        if not attachment or attachment.get("local_path"):
            return
        size = attachment.get("size")
        if size is None or size > self.cfg.max_file_bytes:
            attachment["error"] = "File too large or unknown size; not downloaded (20 MB limit)."
            return
        # Never trust a remote filename as a local path.
        name = Path(attachment["name"]).name
        folder = self.cfg.data / "files" / str(data["message_id"])
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / (name if name not in {"", ".", ".."} else "attachment")
        tg_file = await self.app.bot.get_file(attachment["file_id"])
        await tg_file.download_to_drive(destination)
        attachment["local_path"] = str(destination)

    async def typing(self) -> None:
        while True:
            with suppress(Exception):
                await self.app.bot.send_chat_action(self.cfg.group_id, "typing")
            await asyncio.sleep(4)

    async def on_pi_event(self, event: dict) -> None:
        typ = event.get("type")
        if typ == "agent_start" and self.active == "group":
            self.answer = ""
            self.provider_error = False
        elif typ == "extension_ui_request":
            await self.ui_request(event)
        elif typ == "message_end" and self.active == "group":
            message = event.get("message", {})
            if message.get("role") == "assistant":
                self.provider_error = message.get("stopReason") in {"error", "aborted"}
                text = "".join(block.get("text", "") for block in message.get("content", [])
                               if block.get("type") == "text")
                if text and not self.provider_error:
                    self.answer = text
                await self.remember_session()
        elif typ == "compaction_end" and event.get("result") and not event.get("aborted") and not event.get("errorMessage"):
            await self.send(self.cfg.group_id, "compacted.")
        elif typ == "extension_error":
            self.context_failed = True
            await self.send(self.cfg.owner_id, "A pi extension failed. Check the installation.")

    async def ui_request(self, event: dict) -> None:
        method = event.get("method")
        message = str(event.get("message", ""))
        if method == "notify" and message.startswith("TW_CONTEXT:"):
            self.usage = json.loads(message.removeprefix("TW_CONTEXT:"))
            return
        target = self.cfg.owner_id if self.active != "group" else self.cfg.group_id
        if method == "notify":
            # Configuration notifications (including OAuth codes) stay private.
            if self.active == "admin":
                await self.send(target, message)
            return
        if method not in {"select", "confirm", "input", "editor"}:
            return
        await self.cancel_ui()
        event = dict(event)
        event["target"] = target
        self.pending_ui = event
        title = str(event.get("title", "Input required"))
        options = event.get("options", [])
        markup = None
        if method == "select":
            if target == self.cfg.owner_id:
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton(str(option)[:64], callback_data=f"ui:{event['id']}:{i}")]
                    for i, option in enumerate(options)])
            else:
                title += "\n" + "\n".join(f"{i + 1}. {o}" for i, o in enumerate(options))
        if method == "confirm":
            title += "\n" + event.get("message", "") + "\nReply yes/no."
        if target == self.cfg.group_id:
            title += f"\nOriginal requester: reply with @{self.username} and your answer."
        await self.send(target, title, markup=markup)
        timeout = (event.get("timeout") or 300_000) / 1000
        self.pending_timeout = asyncio.create_task(self.expire_ui(event["id"], timeout))

    async def expire_ui(self, event_id: str, seconds: float) -> None:
        await asyncio.sleep(seconds)
        if self.pending_ui and self.pending_ui["id"] == event_id:
            await self.cancel_ui()

    async def cancel_ui(self) -> None:
        event, self.pending_ui = self.pending_ui, None
        if self.pending_timeout and self.pending_timeout is not asyncio.current_task():
            self.pending_timeout.cancel()
        self.pending_timeout = None
        if event:
            await self.pi.extension_ui_response({"id": event["id"], "cancelled": True})

    async def answer_ui(self, text: str) -> None:
        event, self.pending_ui = self.pending_ui, None
        if not event:
            return
        if self.pending_timeout:
            self.pending_timeout.cancel()
            self.pending_timeout = None
        data = {"id": event["id"]}
        if text.strip().lower() == "/cancel":
            data["cancelled"] = True
        elif event["method"] == "confirm":
            data["confirmed"] = text.strip().lower() in {"ja", "yes", "y", "ok", "true", "1"}
        elif event["method"] == "select":
            options = event.get("options", [])
            data["value"] = options[int(text) - 1] if text.isdigit() and 1 <= int(text) <= len(options) else text
        else:
            data["value"] = text
        await self.pi.extension_ui_response(data)

    async def on_callback(self, update: Update, _context) -> None:
        query = update.callback_query
        if (not query or query.from_user.id != self.cfg.owner_id or not query.message or
                query.message.chat.id != self.cfg.owner_id):
            return
        await query.answer()
        event = self.pending_ui
        parts = (query.data or "").split(":")
        if (self.active != "admin" or not event or len(parts) != 3 or
                parts[0] != "ui" or parts[1] != event["id"]):
            return
        options = event.get("options", [])
        if parts[2].isdigit() and 0 <= int(parts[2]) < len(options):
            await self.answer_ui(options[int(parts[2])])
            await query.edit_message_reply_markup(reply_markup=None)

    async def send(self, chat_id: int, text: str, *, reply_to: int | None = None, markup=None) -> None:
        for chunk in format_for_telegram(text):
            kwargs = dict(chat_id=chat_id, text=chunk, parse_mode="MarkdownV2",
                          reply_to_message_id=reply_to, allow_sending_without_reply=True,
                          reply_markup=markup)
            try:
                message = await self.app.bot.send_message(**kwargs)
            except BadRequest:
                # Formatting should never prevent delivery. Escaped Markdown is
                # still readable as a fallback; don't echo provider exceptions.
                kwargs["parse_mode"] = None
                message = await self.app.bot.send_message(**kwargs)
            if chat_id == self.cfg.group_id:
                self.store.add(record(message))
