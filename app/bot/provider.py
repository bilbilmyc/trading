"""Bot Provider 抽象 — 平台无关的消息收发接口。

目前只有 Telegram 实现；未来加飞书 / Discord 只需实现这个 Protocol。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class IncomingMessage:
    """一条来自聊天平台的消息。"""

    chat_id: int
    text: str
    message_id: int = 0
    user_id: int = 0
    username: str = ""
    raw: Any = None


@dataclass
class OutgoingMessage:
    """要发送到聊天平台的消息。"""

    chat_id: int
    text: str
    parse_mode: str = "HTML"
    reply_to_message_id: int | None = None
    disable_notification: bool = False


class BotProvider(Protocol):
    """消息平台适配器接口。"""

    name: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, message: OutgoingMessage) -> None: ...
    async def poll(self) -> list[IncomingMessage]: ...
