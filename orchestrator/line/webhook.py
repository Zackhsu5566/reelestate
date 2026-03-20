from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from orchestrator.line.bot import line_bot
from orchestrator.line.conversation import ConversationState

if TYPE_CHECKING:
    from orchestrator.line.conversation import ConversationManager

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialized in main.py lifespan
conv_manager: ConversationManager | None = None

# Lazy import to avoid pulling in heavy pipeline deps at import time.
# Tests patch this name directly on the module.
handle_gate_callback = None


def _get_handle_gate_callback():
    global handle_gate_callback
    if handle_gate_callback is None:
        from orchestrator.pipeline.gates import handle_gate_callback as _hgc
        handle_gate_callback = _hgc
    return handle_gate_callback


# ── Image handler ──


async def _handle_image(user_id: str, event: dict) -> None:
    photo_url = event.get("photo_url")
    if not photo_url:
        logger.warning(f"Image event without photo_url for {user_id}")
        return

    state = await conv_manager.get(user_id)
    current = state["state"]

    # 不接受照片的狀態
    if current == ConversationState.processing:
        await line_bot.send_message(user_id, "⏳ 影片製作中，完成後會通知你！")
        return
    if current == ConversationState.awaiting_info:
        await line_bot.send_message(user_id, "📝 請先輸入物件資訊。")
        return
    if current == ConversationState.awaiting_feedback:
        await line_bot.send_message(user_id, "請先提供影片修改意見。")
        return

    # idle / collecting_photos / awaiting_label 都可以加照片
    was_idle = current == ConversationState.idle
    await conv_manager.add_photo(user_id, photo_url)

    if was_idle:
        await line_bot.send_photo_started(user_id)


# ── Text handler ──

# 全域指令（任何狀態都能觸發）
_RESET_COMMANDS = {"重新開始", "取消"}


async def _handle_text(user_id: str, text: str) -> None:
    # 全域重置
    if text in _RESET_COMMANDS:
        await conv_manager.reset(user_id)
        await line_bot.send_welcome(user_id)
        return

    state = await conv_manager.get(user_id)
    current = state["state"]

    # ── collecting_photos ──
    if current == ConversationState.collecting_photos:
        if text in ("完成", "這批完成"):
            count = len(state["pending_photos"])
            await conv_manager.finalize_batch(user_id)
            await line_bot.send_label_prompt(user_id, count)
        else:
            await line_bot.send_message(
                user_id, "📷 照片接收中，傳完後請輸入「完成」標記空間。"
            )
        return

    # ── awaiting_label ──
    if current == ConversationState.awaiting_label:
        label = text.strip()
        if not label:
            await line_bot.send_label_prompt(user_id, len(state["pending_photos"]))
            return
        await conv_manager.assign_label(user_id, label)
        updated = await conv_manager.get(user_id)
        if label == "外觀":
            count = len(state["pending_photos"])
            if count > 1:
                await line_bot.send_message(
                    user_id, f"✓ 外觀照片已收到（僅使用第 1 張，其餘 {count - 1} 張略過）"
                )
        await line_bot.send_space_summary(
            user_id,
            updated["spaces"],
            bool(updated["exterior_photo"]),
        )
        return

    # ── idle ──
    if current == ConversationState.idle:
        has_data = bool(state["spaces"]) or bool(state["exterior_photo"])

        if text in ("完成", "全部完成"):
            if not has_data:
                await line_bot.send_message(user_id, "還沒有傳任何照片喔，請先傳照片 📷")
                return
            await conv_manager.complete_photos(user_id)
            await line_bot.send_info_prompt(user_id)
            return

        if text == "繼續傳照片":
            await line_bot.send_message(user_id, "好的，請繼續傳照片 📷")
            return

        # 沒有上下文的文字 → 歡迎訊息
        await line_bot.send_welcome(user_id)
        return

    # ── awaiting_info ──
    if current == ConversationState.awaiting_info:
        await _create_job(user_id, text, state)
        return

    # ── processing ──
    if current == ConversationState.processing:
        await line_bot.send_message(
            user_id, "⏳ 影片製作中，完成後會通知你！"
        )
        return

    # ── awaiting_feedback ──
    if current == ConversationState.awaiting_feedback:
        if state.get("job_id"):
            await _get_handle_gate_callback()(
                job_id=state["job_id"],
                gate="preview",
                approved=False,
                feedback=text,
            )
        await line_bot.send_message(user_id, "✓ 已收到您的回饋，我們會盡快處理。")
        return

    # Fallback（理論上不會到這裡）
    await line_bot.send_welcome(user_id)


# ── Job creation ──


async def _create_job(user_id: str, raw_text: str, state: dict) -> None:
    """Create a pipeline job from conversation state."""
    from orchestrator.pipeline.state import store
    from orchestrator.models import JobState, JobStatus, SpaceInput
    from orchestrator.pipeline.jobs import pipeline_runner
    import uuid

    job_id = f"line-{uuid.uuid4().hex[:12]}"
    spaces_input = [
        SpaceInput(label=s["label"], photos=s["photos"]) for s in state["spaces"]
    ]
    job_state = JobState(
        job_id=job_id,
        status=JobStatus.analyzing,
        raw_text=raw_text,
        spaces_input=spaces_input,
        exterior_photo=state.get("exterior_photo"),
        line_user_id=user_id,
    )
    await store.create(job_state)
    await conv_manager.set_processing(user_id, job_id)
    await line_bot.send_message(user_id, "✓ 收到！開始生成影片，約需 5-10 分鐘。")
    asyncio.create_task(pipeline_runner(job_id))


# ── Postback handler ──


async def _handle_postback(user_id: str, data: str) -> None:
    """Handle postback from confirm template buttons."""
    parts = data.split(":")
    if len(parts) != 3:
        logger.warning(f"Invalid postback data: {data}")
        return

    action, job_id, gate = parts

    if action == "approve":
        await _get_handle_gate_callback()(
            job_id=job_id, gate=gate, approved=True, feedback=None
        )
    elif action == "reject":
        await conv_manager.set_awaiting_feedback(user_id)
        await line_bot.send_message(user_id, "請說明需要修改的地方：")


# ── Webhook endpoint ──


@router.post("/webhook/line")
async def line_webhook(body: dict) -> dict:
    """Handle forwarded LINE webhook events from n8n."""
    if conv_manager is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    events = body.get("events", [])
    for event in events:
        user_id = event.get("source", {}).get("userId")
        if not user_id:
            continue

        event_type = event.get("type")

        if event_type == "message":
            msg = event.get("message", {})
            msg_type = msg.get("type")

            if msg_type == "image":
                await _handle_image(user_id, event)
            elif msg_type == "text":
                await _handle_text(user_id, msg.get("text", "").strip())

        elif event_type == "postback":
            data = event.get("postback", {}).get("data", "")
            await _handle_postback(user_id, data)

    return {"ok": True}
