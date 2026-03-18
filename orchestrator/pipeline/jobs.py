"""Pipeline step logic: analyze → generate → render → deliver."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
import os
import uuid as _uuid

import httpx

from orchestrator.config import settings
from orchestrator.models import AssetTask, JobState, JobStatus, SpaceInfo, SpaceInput, STAGING_TEMPLATES
from orchestrator.pipeline.state import store
from orchestrator.services.agent import agent_service
from orchestrator.services.r2 import r2_service
from orchestrator.services.render import render_service
from orchestrator.services.wavespeed import wavespeed, PROMPT_DRONE_UP, PROMPT_ROTATE
from orchestrator.telegram.bot import telegram_bot

logger = logging.getLogger(__name__)


# ── Helpers ──


def _find_input_space(state: JobState, space: SpaceInfo) -> SpaceInput | None:
    """Match agent space to input space by original_label (fallback to name)."""
    match_label = space.original_label or space.name
    return next((s for s in state.spaces_input if s.label == match_label), None)


# ── Main pipeline runner ──


async def pipeline_runner(job_id: str) -> None:
    state = await store.get(job_id)
    if state is None:
        logger.error(f"Job {job_id} not found")
        return
    try:
        if state.status == JobStatus.analyzing:
            await step_analyze(state)
            state = await store.get(job_id)
        if state.status == JobStatus.generating:
            await step_generate(state)
            state = await store.get(job_id)
        if state.status == JobStatus.rendering:
            await step_render(state)
            state = await store.get(job_id)
        if state.status == JobStatus.gate_preview:
            return
        if state.status == JobStatus.delivering:
            await step_deliver(state)
    except Exception as e:
        logger.exception(f"Pipeline failed for job {job_id}")
        await store.append_error(job_id, str(e))
        await store.set_status(job_id, JobStatus.failed)


# ── Step 1: Agent Analysis ──


async def step_analyze(state: JobState) -> None:
    logger.info(f"[{state.job_id}] step_analyze")
    result = await agent_service.analyze(
        raw_text=state.raw_text,
        spaces=state.spaces_input,
        premium=state.premium,
    )
    state.agent_result = result
    state.status = JobStatus.generating
    await store.save(state)
    if result.meta:
        if result.meta.warnings:
            logger.warning(f"[{state.job_id}] Agent warnings: {result.meta.warnings}")
        if result.meta.missing_fields:
            logger.warning(f"[{state.job_id}] Agent missing fields: {result.meta.missing_fields}")


# ── Step 2: Parallel Asset Generation ──


async def _reverse_video(video_url: str) -> str:
    """Download video, reverse with ffmpeg, upload to R2. Returns new URL."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(video_url)
        resp.raise_for_status()
        video_bytes = resp.content

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f_in:
        f_in.write(video_bytes)
        in_path = f_in.name

    out_path = in_path + ".reversed.mp4"
    try:
        proc = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ["ffmpeg", "-y", "-i", in_path, "-vf", "reverse", "-an", out_path],
                capture_output=True, timeout=60,
            ),
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg reverse failed: {proc.stderr.decode()}")

        with open(out_path, "rb") as f:
            reversed_bytes = f.read()

        key = f"clips/reversed_{_uuid.uuid4().hex[:8]}.mp4"
        return await r2_service.upload_bytes(reversed_bytes, key, content_type="video/mp4")
    finally:
        os.unlink(in_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


async def _task_kling_video(
    state: JobState, space_name: str, photo_index: int, photo_url: str, prompt: str,
    needs_reverse: bool = False,
) -> None:
    """Single photo → Kling v1.6 video. Optionally reverse for staging."""
    key = f"clip:{space_name}:{photo_index}"
    existing = state.asset_tasks.get(key)
    if existing and existing.status == "completed":
        return

    try:
        existing_id = existing.remote_job_id if existing and existing.status == "submitted" else None

        if existing_id:
            url = await wavespeed.poll(existing_id)
        else:
            pid = await wavespeed.kling_submit(photo_url, prompt)
            await store.update_asset_task(
                state.job_id, key, AssetTask(status="submitted", remote_job_id=pid)
            )
            url = await wavespeed.poll(pid)

        if needs_reverse:
            logger.info(f"Reversing video for {key} (staging connection)")
            url = await _reverse_video(url)

        await store.update_asset_task(
            state.job_id, key, AssetTask(status="completed", output_url=url)
        )
    except Exception as e:
        await store.update_asset_task(
            state.job_id, key, AssetTask(status="failed", error=str(e))
        )
        raise


async def _task_exterior_video(state: JobState) -> None:
    """Exterior photo → Kling v1.6 Drone Up video (non-critical)."""
    key = "clip:exterior"
    existing = state.asset_tasks.get(key)
    if existing and existing.status == "completed":
        return

    try:
        existing_id = existing.remote_job_id if existing and existing.status == "submitted" else None

        if existing_id:
            url = await wavespeed.poll(existing_id)
        else:
            pid = await wavespeed.kling_submit(state.exterior_photo, PROMPT_DRONE_UP)
            await store.update_asset_task(
                state.job_id, key, AssetTask(status="submitted", remote_job_id=pid)
            )
            url = await wavespeed.poll(pid)

        await store.update_asset_task(
            state.job_id, key, AssetTask(status="completed", output_url=url)
        )
    except Exception as e:
        await store.update_asset_task(
            state.job_id, key, AssetTask(status="failed", error=str(e))
        )
        logger.warning(f"Exterior video failed: {e}")


async def _task_staging(
    state: JobState, space_name: str, photo_url: str, prompt: str
) -> None:
    """Virtual staging via nano-banana-2."""
    key = f"staging:{space_name}"
    existing = state.asset_tasks.get(key)
    if existing and existing.status == "completed":
        return

    try:
        existing_id = existing.remote_job_id if existing and existing.status == "submitted" else None

        if existing_id:
            url = await wavespeed.poll(existing_id)
        else:
            pid = await wavespeed.staging_submit(photo_url, prompt)
            await store.update_asset_task(
                state.job_id, key, AssetTask(status="submitted", remote_job_id=pid)
            )
            url = await wavespeed.poll(pid)

        await store.update_asset_task(
            state.job_id, key, AssetTask(status="completed", output_url=url)
        )
    except Exception as e:
        await store.update_asset_task(
            state.job_id, key, AssetTask(status="failed", error=str(e))
        )
        # Staging failure is non-critical, don't raise
        logger.warning(f"Staging failed for {space_name}: {e}")


async def step_generate(state: JobState) -> None:
    logger.info(f"[{state.job_id}] step_generate")
    state.status = JobStatus.generating
    await store.save(state)

    agent = state.agent_result
    tasks = []

    staging_prompt = None
    if state.premium and state.staging_template:
        staging_prompt = STAGING_TEMPLATES.get(state.staging_template)

    if state.exterior_photo:
        tasks.append(_task_exterior_video(state))

    for space in agent.spaces:
        input_space = _find_input_space(state, space)
        if input_space is None:
            continue

        photos = input_space.photos
        has_staging = staging_prompt is not None

        for idx, photo_url in enumerate(photos):
            is_last = (idx == len(photos) - 1)
            needs_reverse = has_staging and is_last
            tasks.append(_task_kling_video(
                state, space.name, idx, photo_url, PROMPT_ROTATE,
                needs_reverse=needs_reverse,
            ))

        if has_staging:
            tasks.append(_task_staging(state, space.name, photos[-1], staging_prompt))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    state = await store.get(state.job_id)

    for r in results:
        if isinstance(r, Exception):
            await store.append_error(state.job_id, str(r))

    clip_failed = False
    for key, task in state.asset_tasks.items():
        if task.status == "failed" and key.startswith("clip:") and key != "clip:exterior":
            clip_failed = True

    if clip_failed:
        await store.append_error(state.job_id, "Critical task failed: clip generation failed")
        await store.set_status(state.job_id, JobStatus.failed)
        return

    state.status = JobStatus.rendering
    await store.save(state)


# ── Step 3: Render ──


async def step_render(state: JobState) -> None:
    logger.info(f"[{state.job_id}] step_render")
    render_input = _build_render_input(state)

    if state.preview_render_job_id:
        # Crash recovery
        url = await render_service.poll(state.preview_render_job_id)
    else:
        rid = await render_service.submit(state.job_id, render_input)
        state.preview_render_job_id = rid
        await store.save(state)
        url = await render_service.poll(rid)

    state.preview_url = url
    state.status = JobStatus.gate_preview
    await store.save(state)

    # Send preview to Telegram for Gate 2
    if state.line_user_id:
        try:
            await telegram_bot.send_gate_preview(
                chat_id=state.line_user_id,
                job_id=state.job_id,
                video_url=url,
                callback_url=state.callback_url,
            )
        except Exception as e:
            logger.warning(f"[{state.job_id}] Telegram send_gate_preview failed: {e}")


# ── Step 4: Deliver ──


async def step_deliver(state: JobState) -> None:
    logger.info(f"[{state.job_id}] step_deliver")
    # For now, final = preview (no upscale step in simplified pipeline)
    state.final_url = state.preview_url
    state.status = JobStatus.done
    await store.save(state)

    # Notify via Telegram
    if state.line_user_id and state.final_url:
        try:
            await telegram_bot.send_final(state.line_user_id, state.final_url)
        except Exception as e:
            logger.warning(f"[{state.job_id}] Telegram send_final failed: {e}")


# ── Build RenderInput ──

OPENING_FRAMES = 300
CLIP_FRAMES = 150
CLIP_SMALL_FRAMES = 105
STATS_FRAMES = 140
CTA_FRAMES = 90


def _build_render_input(state: JobState) -> dict:
    agent = state.agent_result
    prop = agent.property
    scenes: list[dict] = []

    # Opening scene
    opening_scene: dict = {"type": "opening", "durationInFrames": OPENING_FRAMES}
    exterior_task = state.asset_tasks.get("clip:exterior")
    if exterior_task and exterior_task.status == "completed":
        opening_scene["exteriorVideo"] = exterior_task.output_url
    if prop.pois:
        opening_scene["pois"] = [p.model_dump() for p in prop.pois]
    scenes.append(opening_scene)

    staging_prompt = None
    if state.premium and state.staging_template:
        staging_prompt = STAGING_TEMPLATES.get(state.staging_template)

    # Clip scenes (per photo)
    for space in agent.spaces:
        input_space = _find_input_space(state, space)
        if input_space is None:
            continue

        is_small = input_space.is_small_space
        duration = CLIP_SMALL_FRAMES if is_small else CLIP_FRAMES
        photos = input_space.photos

        for idx in range(len(photos)):
            clip_key = f"clip:{space.name}:{idx}"
            clip_task = state.asset_tasks.get(clip_key)
            if not clip_task or clip_task.status != "completed":
                logger.warning(f"Clip {clip_key} not completed, skipping")
                continue

            is_last = (idx == len(photos) - 1)
            scene: dict = {
                "type": "clip",
                "src": clip_task.output_url,
                "label": space.name,
                "durationInFrames": duration,
            }

            if staging_prompt and is_last:
                staging_task = state.asset_tasks.get(f"staging:{space.name}")
                if staging_task and staging_task.status == "completed":
                    scene["stagingImage"] = staging_task.output_url

            scenes.append(scene)

    # Background image
    bg_src = state.exterior_photo
    if not bg_src:
        for space in reversed(agent.spaces):
            input_space = _find_input_space(state, space)
            if input_space and input_space.photos:
                bg_src = input_space.photos[0]
                break

    scenes.append({"type": "stats", "durationInFrames": STATS_FRAMES, **({"backgroundSrc": bg_src} if bg_src else {})})
    scenes.append({"type": "cta", "durationInFrames": CTA_FRAMES, **({"backgroundSrc": bg_src} if bg_src else {})})

    render_input = {
        "title": agent.title or "",
        "location": prop.location or "",
        "address": prop.address or "",
        "size": prop.size or "",
        "layout": prop.layout or "",
        "floor": prop.floor or "",
        "price": prop.price or "",
        "contact": prop.phone or "",
        "agentName": prop.agent_name or "",
        "scenes": scenes,
    }

    if settings.mapbox_token:
        render_input["mapboxToken"] = settings.mapbox_token
    if prop.community:
        render_input["community"] = prop.community
    if prop.property_type:
        render_input["propertyType"] = prop.property_type
    if prop.building_age:
        render_input["buildingAge"] = prop.building_age
    if prop.line:
        render_input["line"] = prop.line

    return render_input
