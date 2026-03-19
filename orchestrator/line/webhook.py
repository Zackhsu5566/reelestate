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

# Debounce timers: {user_id: asyncio.Task}
_debounce_tasks: dict[str, asyncio.Task] = {}

DEBOUNCE_SECONDS = 5.0


# Lazy import to avoid pulling in heavy pipeline deps at import time.
# Tests patch this name directly on the module.
handle_gate_callback = None


def _get_handle_gate_callback():
    global handle_gate_callback
    if handle_gate_callback is None:
        from orchestrator.pipeline.gates import handle_gate_callback as _hgc
        handle_gate_callback = _hgc
    return handle_gate_callback


async def _debounce_finalize(user_id: str) -> None:
    """Wait DEBOUNCE_SECONDS then finalize photo batch and ask for label."""
    await asyncio.sleep(DEBOUNCE_SECONDS)
    _debounce_tasks.pop(user_id, None)
    await conv_manager.finalize_batch(user_id)
    state = await conv_manager.get(user_id)
    n = len(state["pending_photos"])
    await line_bot.send_message(user_id, f"收到 {n} 張照片，這是什麼空間？")


def _reset_debounce(user_id: str) -> None:
    """Cancel existing debounce timer and start a new one."""
    existing = _debounce_tasks.get(user_id)
    if existing and not existing.done():
        existing.cancel()
    _debounce_tasks[user_id] = asyncio.create_task(_debounce_finalize(user_id))


async def _handle_image(user_id: str, event: dict) -> None:
    photo_url = event.get("photo_url")
    if not photo_url:
        logger.warning(f"Image event without photo_url for {user_id}")
        return
    await conv_manager.add_photo(user_id, photo_url)
    _reset_debounce(user_id)


async def _handle_text(user_id: str, text: str) -> None:
    state = await conv_manager.get(user_id)
    current = state["state"]

    if current == ConversationState.awaiting_label:
        await conv_manager.assign_label(user_id, text)
        updated = await conv_manager.get(user_id)
        if text == "外觀":
            await line_bot.send_message(
                user_id, "✓ 外觀照片，請繼續傳下一張或輸入『完成』"
            )
        else:
            last_space = updated["spaces"][-1] if updated["spaces"] else None
            count = len(last_space["photos"]) if last_space else 0
            await line_bot.send_message(
                user_id,
                f"✓ {text}（{count} 張），請繼續傳下一張或輸入『完成』",
            )
        return

    if text == "完成":
        if current == ConversationState.collecting_photos:
            # Cancel debounce, finalize immediately
            existing = _debounce_tasks.pop(user_id, None)
            if existing and not existing.done():
                existing.cancel()
            await conv_manager.finalize_batch(user_id)
            await line_bot.send_message(
                user_id,
                "收到，這批照片是什麼空間？先回覆空間名稱再輸入『完成』",
            )
            return

        if not state["spaces"] and not state["exterior_photo"]:
            await line_bot.send_message(user_id, "還沒有傳任何照片喔，請先傳照片。")
            return
        await conv_manager.complete_photos(user_id)
        await line_bot.send_message(user_id, "請輸入物件資訊：")
        return

    if current == ConversationState.awaiting_info:
        await _create_job(user_id, text, state)
        return

    if current == ConversationState.awaiting_feedback:
        if state.get("job_id"):
            await handle_gate_callback(
                job_id=state["job_id"],
                gate="preview",
                approved=False,
                feedback=text,
            )
        await line_bot.send_message(user_id, "✓ 已收到您的回饋，我們會盡快處理。")
        return

    # Default: idle state, unexpected text
    await line_bot.send_message(
        user_id, "請傳照片開始建立影片，或輸入『完成』結束上傳。"
    )


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


async def _handle_postback(user_id: str, data: str) -> None:
    """Handle postback from confirm template buttons."""
    parts = data.split(":")
    if len(parts) != 3:
        logger.warning(f"Invalid postback data: {data}")
        return

    action, job_id, gate = parts

    if action == "approve":
        await handle_gate_callback(
            job_id=job_id, gate=gate, approved=True, feedback=None
        )
    elif action == "reject":
        await conv_manager.set_awaiting_feedback(user_id)
        await line_bot.send_message(user_id, "請說明需要修改的地方：")


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
