from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

PUSH_URL = "https://api.line.me/v2/bot/message/push"


class LineBot:
    """LINE Messaging API Push client."""

    def __init__(self, channel_access_token: str = "") -> None:
        self._token = channel_access_token
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=30)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("LineBot not started. Call start() first.")
        return self._client

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _push(self, to: str, messages: list[dict]) -> None:
        payload = {"to": to, "messages": messages}
        logger.info(f"LINE Push payload: {payload}")
        resp = await self.client.post(
            PUSH_URL,
            json=payload,
            headers=self._headers(),
        )
        if resp.status_code >= 400:
            logger.error(f"LINE Push API error {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    def _video_message(self, video_url: str, thumbnail_url: str) -> dict:
        return {
            "type": "video",
            "originalContentUrl": video_url,
            "previewImageUrl": thumbnail_url,
        }

    async def send_message(self, chat_id: str, text: str) -> None:
        await self._push(chat_id, [{"type": "text", "text": text}])

    async def send_video(
        self, chat_id: str, video_url: str, thumbnail_url: str
    ) -> None:
        await self._push(chat_id, [self._video_message(video_url, thumbnail_url)])

    async def send_gate_preview(
        self,
        chat_id: str,
        job_id: str,
        video_url: str,
        thumbnail_url: str | None = None,
    ) -> None:
        confirm = {
            "type": "template",
            "altText": "預覽影片確認",
            "template": {
                "type": "confirm",
                "text": "請確認預覽影片是否 OK",
                "actions": [
                    {
                        "type": "postback",
                        "label": "✅ 通過",
                        "data": f"approve:{job_id}:preview",
                    },
                    {
                        "type": "postback",
                        "label": "❌ 不通過",
                        "data": f"reject:{job_id}:preview",
                    },
                ],
            },
        }
        if thumbnail_url:
            messages = [self._video_message(video_url, thumbnail_url), confirm]
        else:
            messages = [
                {"type": "text", "text": f"🎬 預覽影片：\n{video_url}"},
                confirm,
            ]
        await self._push(chat_id, messages)

    async def send_final(
        self, chat_id: str, video_url: str, thumbnail_url: str | None = None
    ) -> None:
        if thumbnail_url:
            messages = [
                self._video_message(video_url, thumbnail_url),
                {"type": "text", "text": "🎉 影片完成！可直接下載使用。"},
            ]
        else:
            messages = [
                {"type": "text", "text": f"🎉 影片完成！可直接下載使用。\n{video_url}"},
            ]
        await self._push(chat_id, messages)


# Module-level singleton (initialized with empty token; config applied at startup)
line_bot = LineBot()
