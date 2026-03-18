"""Telegram Bot: Gate notifications via inline keyboard."""

from __future__ import annotations

import httpx

from orchestrator.config import settings


class TelegramBot:
    BASE_URL = "https://api.telegram.org/bot"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=30)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        assert self._client is not None, "TelegramBot not started"
        return self._client

    @property
    def _url(self) -> str:
        return f"{self.BASE_URL}{settings.telegram_bot_token}"

    async def send_message(
        self, chat_id: str, text: str, reply_markup: dict | None = None
    ) -> dict:
        payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = await self.client.post(f"{self._url}/sendMessage", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def send_audio(
        self, chat_id: str, audio_url: str, caption: str, reply_markup: dict | None = None
    ) -> dict:
        payload: dict = {
            "chat_id": chat_id,
            "audio": audio_url,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = await self.client.post(f"{self._url}/sendAudio", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def send_video(
        self, chat_id: str, video_url: str, caption: str, reply_markup: dict | None = None
    ) -> dict:
        payload: dict = {
            "chat_id": chat_id,
            "video": video_url,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = await self.client.post(f"{self._url}/sendVideo", json=payload)
        resp.raise_for_status()
        return resp.json()

    def _gate_keyboard(self, job_id: str, gate: str, callback_url: str) -> dict:
        return {
            "inline_keyboard": [
                [
                    {"text": "✅ 通過", "callback_data": f"approve:{job_id}:{gate}"},
                    {"text": "❌ 不通過", "callback_data": f"reject:{job_id}:{gate}"},
                ]
            ]
        }

    # ── Gate notifications ──

    async def send_gate_preview(
        self, chat_id: str, job_id: str, video_url: str, callback_url: str
    ) -> None:
        kb = self._gate_keyboard(job_id, "preview", callback_url)
        await self.send_video(
            chat_id,
            video_url,
            "🎬 <b>預覽影片</b>\n\n請確認影片是否 OK：",
            reply_markup=kb,
        )

    async def send_final(self, chat_id: str, video_url: str) -> None:
        await self.send_video(
            chat_id,
            video_url,
            "🎉 <b>影片完成！</b>\n\n您的房產短影音已生成完畢，可直接下載使用。",
        )


telegram_bot = TelegramBot()
