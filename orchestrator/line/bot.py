from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

PUSH_URL = "https://api.line.me/v2/bot/message/push"

# Quick Reply 空間標籤選項
SPACE_LABELS = ["客廳", "臥室", "廚房", "浴室", "陽台", "外觀", "其他"]


def _quick_reply_items(labels: list[str]) -> dict:
    """Build a quickReply object from a list of text labels."""
    return {
        "items": [
            {
                "type": "action",
                "action": {"type": "message", "label": lbl, "text": lbl},
            }
            for lbl in labels
        ]
    }


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
        resp = await self.client.post(
            PUSH_URL,
            json={"to": to, "messages": messages},
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

    # ── Basic messages ──

    async def send_message(self, chat_id: str, text: str) -> None:
        await self._push(chat_id, [{"type": "text", "text": text}])

    async def send_video(
        self, chat_id: str, video_url: str, thumbnail_url: str
    ) -> None:
        await self._push(chat_id, [self._video_message(video_url, thumbnail_url)])

    # ── Conversation flow messages ──

    async def send_welcome(self, chat_id: str) -> None:
        """Flex bubble: 歡迎訊息 + 使用說明."""
        bubble = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "text",
                        "text": "ReelEstate",
                        "weight": "bold",
                        "size": "xl",
                        "color": "#1a1a2e",
                    },
                    {
                        "type": "text",
                        "text": "傳送房屋照片，自動生成專業短影音",
                        "size": "sm",
                        "color": "#888888",
                        "wrap": True,
                    },
                    {"type": "separator"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "spacing": "sm",
                                "contents": [
                                    {"type": "text", "text": "1.", "size": "sm", "color": "#1a1a2e", "flex": 0},
                                    {"type": "text", "text": "傳送同一空間的照片", "size": "sm", "wrap": True},
                                ],
                            },
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "spacing": "sm",
                                "contents": [
                                    {"type": "text", "text": "2.", "size": "sm", "color": "#1a1a2e", "flex": 0},
                                    {"type": "text", "text": "輸入「完成」標記空間名稱", "size": "sm", "wrap": True},
                                ],
                            },
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "spacing": "sm",
                                "contents": [
                                    {"type": "text", "text": "3.", "size": "sm", "color": "#1a1a2e", "flex": 0},
                                    {"type": "text", "text": "重複步驟 1-2 上傳其他空間", "size": "sm", "wrap": True},
                                ],
                            },
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "spacing": "sm",
                                "contents": [
                                    {"type": "text", "text": "4.", "size": "sm", "color": "#1a1a2e", "flex": 0},
                                    {"type": "text", "text": "輸入「全部完成」後填寫物件資訊", "size": "sm", "wrap": True},
                                ],
                            },
                        ],
                    },
                    {"type": "separator"},
                    {
                        "type": "text",
                        "text": "📷 開始傳照片吧！",
                        "size": "sm",
                        "color": "#1a1a2e",
                        "weight": "bold",
                        "align": "center",
                    },
                ],
            },
        }
        await self._push(
            chat_id,
            [{"type": "flex", "altText": "歡迎使用 ReelEstate — 傳送照片開始", "contents": bubble}],
        )

    async def send_photo_started(self, chat_id: str) -> None:
        """收到第一張照片時的引導訊息."""
        await self._push(
            chat_id,
            [
                {
                    "type": "text",
                    "text": (
                        "📷 開始接收照片！\n"
                        "同一空間的照片請一起傳，\n"
                        "傳完後輸入「完成」標記空間名稱。"
                    ),
                }
            ],
        )

    async def send_label_prompt(self, chat_id: str, count: int) -> None:
        """照片批次完成，詢問空間名稱（Quick Reply 按鈕）."""
        await self._push(
            chat_id,
            [
                {
                    "type": "text",
                    "text": f"收到 {count} 張照片 ✓\n請選擇這是什麼空間：",
                    "quickReply": _quick_reply_items(SPACE_LABELS),
                }
            ],
        )

    async def send_space_summary(
        self, chat_id: str, spaces: list[dict], has_exterior: bool
    ) -> None:
        """Flex bubble: 已收集空間摘要 + 行動按鈕."""
        rows: list[dict] = []
        for s in spaces:
            rows.append(
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": f"✓ {s['label']}", "size": "sm", "flex": 2},
                        {
                            "type": "text",
                            "text": f"{len(s['photos'])} 張",
                            "size": "sm",
                            "color": "#888888",
                            "align": "end",
                            "flex": 1,
                        },
                    ],
                }
            )
        if has_exterior:
            rows.append(
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "✓ 外觀", "size": "sm", "flex": 2},
                        {
                            "type": "text",
                            "text": "1 張",
                            "size": "sm",
                            "color": "#888888",
                            "align": "end",
                            "flex": 1,
                        },
                    ],
                }
            )

        bubble = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": "已收集空間", "weight": "bold", "size": "md"},
                    {"type": "separator"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "sm",
                        "contents": rows,
                    },
                ],
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "spacing": "md",
                "contents": [
                    {
                        "type": "button",
                        "action": {"type": "message", "label": "繼續傳照片", "text": "繼續傳照片"},
                        "style": "secondary",
                        "height": "sm",
                    },
                    {
                        "type": "button",
                        "action": {"type": "message", "label": "全部完成", "text": "全部完成"},
                        "style": "primary",
                        "color": "#1a1a2e",
                        "height": "sm",
                    },
                ],
            },
        }
        await self._push(
            chat_id,
            [{"type": "flex", "altText": "已收集空間摘要", "contents": bubble}],
        )

    async def send_info_prompt(self, chat_id: str) -> None:
        """Flex bubble: 請輸入物件資訊 + 欄位提示."""
        fields = ["地址 / 位置", "坪數", "格局（幾房幾廳）", "樓層", "價格", "聯絡電話"]
        field_rows = [
            {"type": "text", "text": f"• {f}", "size": "sm", "color": "#555555"}
            for f in fields
        ]
        bubble = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": "📝 請輸入物件資訊", "weight": "bold", "size": "lg"},
                    {"type": "separator"},
                    {
                        "type": "text",
                        "text": "請包含以下資訊（直接打字即可）：",
                        "size": "sm",
                        "color": "#888888",
                        "wrap": True,
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "xs",
                        "contents": field_rows,
                    },
                ],
            },
        }
        await self._push(
            chat_id,
            [{"type": "flex", "altText": "請輸入物件資訊", "contents": bubble}],
        )

    async def send_progress(self, chat_id: str, stage: str) -> None:
        """Pipeline 進度通知."""
        await self._push(chat_id, [{"type": "text", "text": stage}])

    # ── Gate & delivery ──

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

    # ── Registration & job options ──

    async def send_registration_name_prompt(self, chat_id: str) -> None:
        await self.send_message(
            chat_id,
            "歡迎使用 ReelEstate！🏠\n請先輸入您的姓名：",
        )

    async def send_registration_company_prompt(self, chat_id: str) -> None:
        await self.send_message(chat_id, "請輸入您的公司名稱：")

    async def send_registration_phone_prompt(self, chat_id: str) -> None:
        await self.send_message(chat_id, "請輸入您的聯絡電話：")

    async def send_registration_line_id_prompt(self, chat_id: str) -> None:
        """Send LINE ID prompt with Quick Reply skip button."""
        await self._push(chat_id, [{
            "type": "text",
            "text": "請輸入您的 LINE ID（選填，將顯示於影片中供客戶聯繫）",
            "quickReply": {
                "items": [{
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": "跳過",
                        "data": "skip_line_id",
                        "displayText": "跳過",
                    },
                }],
            },
        }])

    async def send_registration_complete(self, chat_id: str) -> None:
        await self.send_message(
            chat_id,
            "註冊完成！您可以開始傳照片生成影片了 🎬\n\n"
            "直接傳送房屋照片即可開始。",
        )

    async def send_style_choice(self, chat_id: str) -> None:
        """Send style Quick Reply buttons."""
        styles = [
            ("日式無印", "style:japanese_muji"),
            ("北歐", "style:scandinavian"),
            ("現代極簡", "style:modern_minimalist"),
            ("現代奢華", "style:modern_luxury"),
            ("溫暖自然", "style:warm_natural"),
        ]
        items = [
            {
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": label,
                    "data": data,
                    "displayText": label,
                },
            }
            for label, data in styles
        ]
        await self._push(chat_id, [{
            "type": "text",
            "text": "請選擇虛擬裝潢風格：",
            "quickReply": {"items": items},
        }])

    async def send_narration_choice(self, chat_id: str) -> None:
        """Send narration opt-in Quick Reply."""
        items = [
            {
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": "是",
                    "data": "narration:yes",
                    "displayText": "是",
                },
            },
            {
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": "否",
                    "data": "narration:no",
                    "displayText": "否",
                },
            },
        ]
        await self._push(chat_id, [{
            "type": "text",
            "text": "要加入 AI 旁白嗎？",
            "quickReply": {"items": items},
        }])

    async def send_quota_exceeded(self, chat_id: str, usage: int, quota: int) -> None:
        await self.send_message(
            chat_id,
            f"您已使用 {usage}/{quota} 支影片額度，目前無法再生成。",
        )

    async def send_validation_error(self, chat_id: str, message: str) -> None:
        """Show a field-specific validation failure message during registration."""
        await self.send_message(chat_id, message)

    async def send_text_only_reminder(self, chat_id: str, reprompt: str) -> None:
        """Remind user that only text is accepted in the current state, then re-prompt."""
        await self.send_message(chat_id, f"請輸入文字訊息喔！\n{reprompt}")


# Module-level singleton (initialized with empty token; config applied at startup)
line_bot = LineBot()
