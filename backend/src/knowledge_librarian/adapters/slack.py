"""Optional Slack Socket Mode delivery adapter sharing the core application service."""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from knowledge_librarian.models import ChatMessage, ChatRequest
from knowledge_librarian.service import LibrarianService


class SlackConfigurationError(ValueError):
    pass


class SlackApplicationAdapter:
    def __init__(
        self,
        *,
        service: LibrarianService,
        bot_token: str,
        app_token: str,
        signing_secret: str,
        feedback_sink: Callable[[str, str, str], Awaitable[None]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not bot_token.startswith("xoxb-"):
            raise SlackConfigurationError("A Slack bot token is required")
        if not app_token.startswith("xapp-"):
            raise SlackConfigurationError("A Slack Socket Mode app token is required")
        if len(signing_secret) < 16:
            raise SlackConfigurationError("A Slack signing secret is required")
        self.service = service
        self.bot_token = bot_token
        self.app_token = app_token
        self.signing_secret = signing_secret
        self.feedback_sink = feedback_sink
        self.clock = clock
        self._history: dict[str, list[ChatMessage]] = {}

    def build(self) -> Any:
        try:
            from slack_bolt.async_app import AsyncApp
        except ImportError as exc:
            raise RuntimeError("Install the 'slack' project extra to enable Slack") from exc

        app = AsyncApp(token=self.bot_token, signing_secret=self.signing_secret)

        @app.event("app_mention")
        async def on_mention(event: dict[str, Any], client: Any) -> None:
            await self.handle_mention(event, client)

        @app.action(re.compile(r"^librarian_(helpful|needs_work)$"))
        async def on_feedback(ack: Any, body: dict[str, Any], client: Any) -> None:
            await ack()
            await self.handle_feedback(body, client)

        return app

    async def handle_mention(self, event: dict[str, Any], client: Any) -> None:
        question = re.sub(r"<@[A-Z0-9]+>", "", str(event.get("text", ""))).strip()
        channel = str(event["channel"])
        thread_ts = str(event.get("thread_ts") or event["ts"])
        if not question:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Ask me a question about the indexed knowledge base.",
            )
            return
        initial = await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Searching the knowledge base…",
        )
        response_ts = initial["ts"]
        text = ""
        citations: list[dict[str, Any]] = []
        conversation_id = f"{channel}:{thread_ts}"
        history = self._history.get(conversation_id, [])[-10:]
        last_update = self.clock()
        last_update_length = 0
        async for chat_event in self.service.events(
            ChatRequest(message=question, conversation_id=conversation_id, history=history)
        ):
            if chat_event.type == "delta":
                text += str(chat_event.data["text"])
                now = self.clock()
                if len(text) - last_update_length >= 240 and now - last_update >= 1.0:
                    await client.chat_update(channel=channel, ts=response_ts, text=text + " ▌")
                    last_update = now
                    last_update_length = len(text)
            elif chat_event.type == "citation":
                citations.append(chat_event.data)
        source_lines = "\n".join(f"[{item['id']}] {item['title']}" for item in citations)
        final_text = text + (f"\n\n*Sources*\n{source_lines}" if source_lines else "")
        await client.chat_update(
            channel=channel,
            ts=response_ts,
            text=final_text,
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": final_text}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Helpful"},
                            "action_id": "librarian_helpful",
                            "value": response_ts,
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Needs work"},
                            "action_id": "librarian_needs_work",
                            "value": response_ts,
                        },
                    ],
                },
            ],
        )
        self._history[conversation_id] = [
            *history,
            ChatMessage(role="user", content=question),
            ChatMessage(role="assistant", content=text),
        ][-10:]

    async def handle_feedback(self, body: dict[str, Any], client: Any) -> None:
        action = body["actions"][0]
        rating = str(action["action_id"]).removeprefix("librarian_")
        response_id = str(action["value"])
        actor_hash = hashlib.sha256(str(body["user"]["id"]).encode()).hexdigest()
        if self.feedback_sink is not None:
            await self.feedback_sink(response_id, rating, actor_hash)
        await client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=body["user"]["id"],
            text="Thanks — your feedback was recorded for this session.",
        )

    async def run(self) -> None:
        try:
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
        except ImportError as exc:
            raise RuntimeError("Install the 'slack' project extra to enable Slack") from exc
        await AsyncSocketModeHandler(self.build(), self.app_token).start_async()  # type: ignore[no-untyped-call]
