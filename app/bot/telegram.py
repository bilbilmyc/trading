"""Telegram Bot 适配器 — 长轮询 + 发送消息。

只用 httpx，不依赖 python-telegram-bot 或 aiogram，保持依赖最小。
"""

from __future__ import annotations

import asyncio
import time

import httpx

from app.bot.config import BotConfig
from app.bot.provider import IncomingMessage, OutgoingMessage


class TelegramProvider:
    """Telegram Bot API 长轮询实现。"""

    name = "telegram"

    def __init__(self, config: BotConfig) -> None:
        self._config = config
        self._token = config.telegram_token
        self._base = f"https://api.telegram.org/bot{self._token}"
        self._client: httpx.AsyncClient | None = None
        self._offset: int = 0
        self._last_send: float = 0.0
        self._min_interval: float = 1.0 / max(config.send_rate_per_second, 0.1)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base,
                timeout=self._config.request_timeout_seconds,
            )
        return self._client

    async def start(self) -> None:
        # 验证 token 有效性
        client = await self._get_client()
        resp = await client.get("/getMe")
        if resp.status_code != 200:
            raise RuntimeError(f"Telegram getMe failed: {resp.status_code} {resp.text[:200]}")
        info = resp.json()
        if not info.get("ok"):
            raise RuntimeError(f"Telegram getMe not ok: {info}")
        bot_name = info["result"].get("username", "?")
        from loguru import logger
        logger.info(f"Telegram bot connected: @{bot_name}")

    async def stop(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def send(self, message: OutgoingMessage) -> None:
        # 简单限速：两条消息间隔不小于 min_interval
        now = time.monotonic()
        wait = self._min_interval - (now - self._last_send)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_send = time.monotonic()

        client = await self._get_client()
        payload: dict = {
            "chat_id": message.chat_id,
            "text": message.text,
            "parse_mode": message.parse_mode,
            "disable_notification": message.disable_notification,
        }
        if message.reply_to_message_id:
            payload["reply_to_message_id"] = message.reply_to_message_id
        resp = await client.post("/sendMessage", json=payload)
        if resp.status_code != 200:
            from loguru import logger
            logger.warning(f"Telegram send {resp.status_code}: {resp.text[:300]}")

    async def poll(self) -> list[IncomingMessage]:
        client = await self._get_client()
        resp = await client.get(
            "/getUpdates",
            params={"offset": self._offset, "timeout": 30},
            timeout=35.0,  # long polling
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not data.get("ok"):
            return []
        messages: list[IncomingMessage] = []
        for update in data.get("result", []):
            self._offset = update.get("update_id", self._offset) + 1
            msg = update.get("message") or update.get("edited_message")
            if not msg:
                continue
            text = msg.get("text", "").strip()
            if not text:
                continue
            chat = msg.get("chat", {})
            user = msg.get("from", {})
            messages.append(
                IncomingMessage(
                    chat_id=chat.get("id", 0),
                    text=text,
                    message_id=msg.get("message_id", 0),
                    user_id=user.get("id", 0),
                    username=user.get("username", ""),
                    raw=update,
                )
            )
        return messages
