from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from orchestrator.line.bot import line_bot
from orchestrator.line.conversation import ConversationState
from orchestrator.models import UserProfile
from orchestrator.stores.user import UserStore
from orchestrator.line.validators import (
    validate_name, validate_company, validate_phone, validate_line_id,
)

if TYPE_CHECKING:
    from orchestrator.line.conversation import ConversationManager

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialized in main.py lifespan
conv_manager: ConversationManager | None = None
user_store: UserStore | None = None

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

    # 不接受照片的狀態 — text-only states
    text_only_reprompts = {
        ConversationState.registering_name: "請輸入您的姓名：",
        ConversationState.registering_company: "請輸入您的公司名稱：",
        ConversationState.registering_phone: "請輸入您的聯絡電話：",
        ConversationState.registering_line_id: "請輸入您的 LINE ID 或點選跳過：",
        ConversationState.editing_narration: "請輸入修改後的講稿：",
    }
    reprompt = text_only_reprompts.get(current)
    if reprompt:
        await line_bot.send_text_only_reminder(user_id, reprompt)
        return

    # 提前攔截配額：idle 狀態才阻擋（collecting_photos 已在途中不中斷）
    if current == ConversationState.idle:
        profile_check = await user_store.get(user_id)
        if profile_check and profile_check.usage >= profile_check.quota:
            await line_bot.send_quota_exceeded(user_id, profile_check.usage, profile_check.quota)
            return

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
    count = await conv_manager.add_photo(user_id, photo_url)
    await line_bot.send_photo_received(user_id, count)


# ── Text handler ──

# 全域指令（任何狀態都能觸發）
_RESET_COMMANDS = {"重新開始", "取消"}

# Registration step config
_REG_STEPS = {
    ConversationState.registering_name: {
        "field": "reg_name",
        "validate": validate_name,
        "next": ConversationState.registering_company,
        "error": "請輸入 1-20 字的姓名",
        "prompt": "send_registration_company_prompt",
    },
    ConversationState.registering_company: {
        "field": "reg_company",
        "validate": validate_company,
        "next": ConversationState.registering_phone,
        "error": "請輸入 1-30 字的公司名稱",
        "prompt": "send_registration_phone_prompt",
    },
    ConversationState.registering_phone: {
        "field": "reg_phone",
        "validate": validate_phone,
        "next": ConversationState.registering_line_id,
        "error": "請輸入正確的手機號碼（例如 0912345678）",
        "prompt": "send_registration_line_id_prompt",
    },
}


async def _handle_registration(
    user_id: str,
    text: str,
    state: ConversationState,
    bot_inst,
    conv,
) -> None:
    """Handle registering_name / registering_company / registering_phone steps."""
    step = _REG_STEPS[state]
    validated = step["validate"](text)
    if validated is None:
        await bot_inst.send_validation_error(user_id, step["error"])
        return
    await conv.set_reg_field(user_id, step["field"], validated, step["next"])
    await getattr(bot_inst, step["prompt"])(user_id)


async def _handle_registration_line_id(
    user_id: str,
    text: str,
    bot_inst,
    conv,
    user_store_inst,
) -> None:
    """Handle registering_line_id step (optional, can skip).

    Handles both new registration and 修改資料 flow:
    - New user: create full profile
    - Existing user (修改資料): update only personal info, preserve usage/quota
    """
    validated = validate_line_id(text)
    if validated is None:
        await bot_inst.send_validation_error(
            user_id, "LINE ID 格式不正確，請重新輸入或點選跳過",
        )
        return
    line_id = None if validated == "SKIP" else validated
    conv_state = await conv.get(user_id)

    existing = await user_store_inst.get(user_id)
    if existing:
        # 修改資料 — only update personal info, preserve usage/quota
        await user_store_inst.update(
            user_id,
            name=conv_state["reg_name"],
            company=conv_state["reg_company"],
            phone=conv_state["reg_phone"],
            line_id=line_id,
        )
    else:
        # New user — create full profile
        profile = UserProfile(
            line_user_id=user_id,
            name=conv_state["reg_name"],
            company=conv_state["reg_company"],
            phone=conv_state["reg_phone"],
            line_id=line_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        await user_store_inst.create(profile)

    await conv.complete_registration(user_id)
    await bot_inst.send_registration_complete(user_id)


async def _handle_text(user_id: str, text: str) -> None:
    # 全域指令 — 在任何狀態都有效
    if text in _RESET_COMMANDS:
        # editing_narration 特殊處理：寫 rejected，不取消 job
        state = await conv_manager.get(user_id)
        if state["state"] == ConversationState.editing_narration:
            job_id = state.get("job_id")
            if job_id:
                await conv_manager._r.set(
                    f"narration_gate:{job_id}", "rejected", ex=3600,
                )
            await conv_manager.set_processing(user_id, job_id)
            await line_bot.send_message(user_id, "已取消旁白。")
            return
        await conv_manager.reset(user_id)
        await line_bot.send_welcome(user_id)
        return

    if text == "使用說明":
        await line_bot.send_welcome(user_id)
        return

    if text == "修改資料":
        profile = await user_store.get(user_id)
        if profile:
            await conv_manager.start_registration(user_id)
            await line_bot.send_registration_name_prompt(user_id)
        else:
            await line_bot.send_message(user_id, "您尚未完成註冊，請先完成註冊後再修改資料。")
        return

    # Profile 檢查
    profile = await user_store.get(user_id)
    state = await conv_manager.get(user_id)
    current = state["state"]

    # 註冊流程
    if current in _REG_STEPS:
        await _handle_registration(user_id, text, current, line_bot, conv_manager)
        return
    if current == ConversationState.registering_line_id:
        await _handle_registration_line_id(user_id, text, line_bot, conv_manager, user_store)
        return

    # ── editing_narration ──
    if current == ConversationState.editing_narration:
        job_id = state.get("job_id")
        # 字數限制檢查
        from orchestrator.pipeline.state import store
        job_state = await store.get(job_id)
        if job_state and job_state.narration_text:
            max_len = int(len(job_state.narration_text) * 1.5)
            if len(text) > max_len:
                await line_bot.send_message(
                    user_id,
                    f"講稿過長（{len(text)} 字），請縮短至 {max_len} 字以內。",
                )
                return
        gate_key = f"narration_gate:{job_id}"
        await conv_manager._r.set(gate_key, f"edit:{text}", ex=3600)
        state["state"] = ConversationState.processing
        await conv_manager._save(user_id, state)
        await line_bot.send_message(user_id, "講稿已更新，正在生成旁白...")
        return

    # 新用戶 → 開始註冊
    if profile is None:
        await conv_manager.start_registration(user_id)
        await line_bot.send_registration_name_prompt(user_id)
        return

    # ── choosing_style ──
    if current == ConversationState.choosing_style:
        await line_bot.send_style_choice(user_id)
        return

    # ── awaiting_narration_choice ──
    if current == ConversationState.awaiting_narration_choice:
        await line_bot.send_narration_choice(user_id)
        return

    # ── collecting_photos ──
    if current == ConversationState.collecting_photos:
        if text in ("完成", "這批完成"):
            count = len(state["pending_photos"])
            await conv_manager.finalize_batch(user_id)
            await line_bot.send_label_prompt(user_id, count)
        else:
            await line_bot.send_message(
                user_id, "📷 照片接收中，傳完後請按「完成」標記空間。"
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
        await conv_manager.set_awaiting_style(user_id, text)
        await line_bot.send_style_choice(user_id)
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


async def _create_job(
    user_id: str, raw_text: str, state: dict, profile=None,
) -> None:
    """Create a pipeline job from conversation state."""
    from orchestrator.pipeline.state import store
    from orchestrator.models import JobState, JobStatus, SpaceInput
    from orchestrator.pipeline.jobs import pipeline_runner
    import uuid

    job_id = f"line-{uuid.uuid4().hex[:12]}"
    job_state = JobState(
        job_id=job_id,
        status=JobStatus.analyzing,
        raw_text=raw_text,
        spaces_input=[
            SpaceInput(
                label=s["label"],
                photos=s["photos"],
                is_small_space=s.get("is_small_space", False),
            )
            for s in state.get("spaces", [])
        ],
        exterior_photo=state.get("exterior_photo"),
        line_user_id=user_id,
        premium=profile.plan == "premium" if profile else True,
        staging_template=state.get("chosen_style") or "japanese_muji",
        narration_enabled=state.get("narration_enabled") or False,
    )
    await store.create(job_state)
    await conv_manager.set_processing(user_id, job_id)
    await line_bot.send_message(user_id, "✓ 收到！開始生成影片，約需 5-10 分鐘。")
    asyncio.create_task(pipeline_runner(job_id))


# ── Postback handler ──


async def _handle_postback(user_id: str, data: str) -> None:
    """Handle postback from Quick Reply and confirm template buttons."""
    # Skip LINE ID during registration
    if data == "skip_line_id":
        await _handle_registration_line_id(user_id, "跳過", line_bot, conv_manager, user_store)
        return

    # Style selection
    if data.startswith("style:"):
        style = data.split(":", 1)[1]
        await conv_manager.set_chosen_style(user_id, style)
        await line_bot.send_narration_choice(user_id)
        return

    # Narration choice
    if data.startswith("narration:"):
        enabled = data == "narration:yes"
        await conv_manager.set_narration_choice(user_id, enabled)
        # 配額檢查 + 建立 job
        state = await conv_manager.get(user_id)

        if not await user_store.try_consume_quota(user_id):
            quota_profile = await user_store.get(user_id)
            await line_bot.send_quota_exceeded(
                user_id, quota_profile.usage, quota_profile.quota,
            )
            await conv_manager.reset(user_id)
            return

        # fetch fresh profile after successful quota consumption
        profile = await user_store.get(user_id)
        await _create_job(user_id, state.get("raw_text", ""), state, profile)
        return

    # Narration gate
    if data.startswith("narration_gate:"):
        parts = data.split(":")
        if len(parts) == 3:
            job_id, action = parts[1], parts[2]
            gate_key = f"narration_gate:{job_id}"
            if action == "approved":
                await conv_manager._r.set(gate_key, "approved", ex=3600)
                await line_bot.send_message(user_id, "✅ 旁白已確認，繼續生成影片...")
            elif action == "rejected":
                await conv_manager._r.set(gate_key, "rejected", ex=3600)
                await line_bot.send_message(user_id, "已取消旁白，繼續生成影片...")
            elif action == "edit":
                await conv_manager._r.set(gate_key, "edit_pending", ex=3600)
                state = await conv_manager.get(user_id)
                state["state"] = ConversationState.editing_narration
                await conv_manager._save(user_id, state)
                await line_bot.send_message(user_id, "請輸入修改後的講稿：")
        return

    # Existing approve/reject handling
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


# ── Follow handler ──


async def _handle_follow(user_id: str) -> None:
    """Handle follow event — auto-start registration or welcome back."""
    profile = await user_store.get(user_id)
    if profile:
        # 已註冊用戶（封鎖後重新加好友）
        await conv_manager.reset(user_id)
        await line_bot.send_welcome(user_id)
    else:
        # 新用戶 → 啟動註冊
        await conv_manager.start_registration(user_id)
        await line_bot.send_registration_name_prompt(user_id)


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

        elif event_type == "follow":
            await _handle_follow(user_id)

    return {"ok": True}
