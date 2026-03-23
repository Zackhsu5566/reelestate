"""Pipeline step logic: analyze → generate → render → deliver."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
import time
import os
import uuid as _uuid

import httpx

from orchestrator.config import settings
from orchestrator.models import AssetTask, JobState, JobStatus, SpaceInfo, SpaceInput
from orchestrator.staging_prompts import get_staging_prompt
from orchestrator.pipeline.state import store
from orchestrator.stores.user import UserStore
from orchestrator.services.agent import agent_service
from orchestrator.services.minimax import MiniMaxService
from orchestrator.services.r2 import r2_service
from orchestrator.services.render import render_service
from orchestrator.services.wavespeed import wavespeed, PROMPT_DRONE_UP, PROMPT_PUSH_IN, PROMPT_PAN
from orchestrator.line.bot import line_bot

logger = logging.getLogger(__name__)


# ── Helpers ──


def _build_task_key_prefix(space_index: int) -> str:
    """Unique prefix for asset_task keys based on space position."""
    return str(space_index)


def _get_space_photos(state: JobState, space: SpaceInfo, space_index: int) -> list[str]:
    """Get photos for a space — use agent's assignment directly.
    Fallback uses positional index to avoid duplicate-name bugs.
    """
    if space.photos:
        return space.photos
    # Fallback: positional match (safe for duplicate labels)
    if space_index < len(state.spaces_input):
        return state.spaces_input[space_index].photos
    return []


def _find_input_space(state: JobState, space_index: int) -> SpaceInput | None:
    """Get input space by index for metadata (is_small_space)."""
    if space_index < len(state.spaces_input):
        return state.spaces_input[space_index]
    return None


async def _narration_gate_poll(job_id: str, redis) -> tuple[str, str | None]:
    """Poll narration gate Redis key. Returns (action, edited_text).
    action: 'approved' | 'rejected' | 'edit'
    """
    key = f"narration_gate:{job_id}"
    deadline = time.monotonic() + 600  # 10 min
    while time.monotonic() < deadline:
        val = await redis.get(key)
        if val is None or val in ("pending", "edit_pending"):
            await asyncio.sleep(3)
            continue
        if val == "approved":
            return "approved", None
        if val == "rejected":
            return "rejected", None
        if val.startswith("edit:"):
            return "edit", val[5:]
        await asyncio.sleep(3)
    # Timeout → auto-approve
    return "approved", None


async def _task_tts(
    state: JobState, redis, minimax: MiniMaxService, r2
) -> None:
    """Run narration gate + TTS. Uses atomic updates to avoid clobbering asset_tasks."""
    job_id = state.job_id
    if not state.narration_enabled or not state.narration_text:
        return

    # Set gate pending
    gate_key = f"narration_gate:{job_id}"
    await redis.set(gate_key, "pending", ex=3600)

    # Notify user — push narration preview
    if line_bot and state.line_user_id:
        await line_bot.send_gate_narration(
            state.line_user_id, job_id, state.narration_text,
        )

    await store.update_narration(job_id, narration_gate_status="pending")

    # Wait for gate
    action, edited_text = await _narration_gate_poll(job_id, redis)

    if action == "rejected":
        await store.update_narration(
            job_id, narration_gate_status="rejected", narration_enabled=False,
        )
        return

    # Use edited text if provided
    final_text = edited_text if action == "edit" else state.narration_text
    await store.update_narration(
        job_id, narration_text=final_text, narration_gate_status="approved",
    )

    # Run TTS
    audio_bytes = await minimax.synthesize(final_text)
    if not audio_bytes:
        logger.warning("TTS failed, degrading to no narration: job=%s", job_id)
        await store.update_narration(job_id, narration_url=None)
        return

    # Log duration (observability)
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", tmp_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            duration = float(result.stdout.strip())
            logger.info("TTS audio duration: %.1fs (job=%s)", duration, job_id)
    except Exception:
        pass  # observability only

    # Upload to R2
    r2_key = f"audio/{job_id}/narration.mp3"
    narration_url = await r2.upload_bytes(audio_bytes, r2_key, "audio/mpeg")
    await store.update_narration(job_id, narration_url=narration_url)


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
        if state.status == JobStatus.delivering:
            await step_deliver(state)
    except Exception as e:
        logger.exception(f"Pipeline failed for job {job_id}")
        await store.append_error(job_id, str(e))
        await store.set_status(job_id, JobStatus.failed)
        if state and state.line_user_id:
            try:
                await line_bot.send_message(
                    state.line_user_id,
                    "❌ 影片生成失敗，請輸入「重新開始」重試或聯繫客服。",
                )
            except Exception:
                pass


# ── Step 1: Agent Analysis ──


async def _notify_progress(state: JobState, message: str) -> None:
    """Send LINE progress update if job was initiated via LINE."""
    if not state.line_user_id:
        return
    try:
        await line_bot.send_progress(state.line_user_id, message)
    except Exception as e:
        logger.warning(f"[{state.job_id}] Progress notification failed: {e}")


async def step_analyze(state: JobState) -> None:
    logger.info(f"[{state.job_id}] step_analyze")
    await _notify_progress(state, "📊 分析物件資訊中…")
    result = await agent_service.analyze(
        raw_text=state.raw_text,
        spaces=state.spaces_input,
        premium=state.premium,
    )
    # 用 spaces_input 的原始照片覆蓋 agent 回傳的 photos（LLM 容易搞混 URL）
    for i, space in enumerate(result.spaces):
        if i < len(state.spaces_input):
            space.photos = state.spaces_input[i].photos
            space.photo_count = len(space.photos)

    state.agent_result = result
    state.status = JobStatus.generating
    await store.save(state)
    if result.meta:
        if result.meta.warnings:
            logger.warning(f"[{state.job_id}] Agent warnings: {result.meta.warnings}")
        if result.meta.missing_fields:
            logger.warning(f"[{state.job_id}] Agent missing fields: {result.meta.missing_fields}")

    # Profile injection — fallback to user profile for contact fields
    if state.line_user_id:
        user_store = UserStore(store.r)
        profile = await user_store.get(state.line_user_id)
        if profile and state.agent_result:
            prop = state.agent_result.property
            if prop:
                prop.agent_name = prop.agent_name or profile.name
                prop.company = prop.company or profile.company
                prop.phone = prop.phone or profile.phone
                prop.line = prop.line or profile.line_id
                await store.save(state)

    # Copy narration text for TTS
    if state.narration_enabled and state.agent_result and state.agent_result.narration:
        state.narration_text = state.agent_result.narration
        await store.save(state)


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
    state: JobState, key_prefix: str, photo_index: int, photo_url: str, prompt: str,
    needs_reverse: bool = False,
) -> None:
    """Single photo → Kling v2.5 video. Optionally reverse for staging."""
    key = f"clip:{key_prefix}:{photo_index}"
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
    """Exterior photo → Kling v2.5 Drone Up video (non-critical)."""
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
    state: JobState, key_prefix: str, photo_url: str, prompt: str
) -> None:
    """Virtual staging via nano-banana-2."""
    key = f"staging:{key_prefix}"
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
        logger.warning(f"Staging failed for {key_prefix}: {e}")


async def step_generate(state: JobState) -> None:
    logger.info(f"[{state.job_id}] step_generate")
    await _notify_progress(state, "🎨 生成影片素材中（約 3-5 分鐘）…")
    state.status = JobStatus.generating
    await store.save(state)

    agent = state.agent_result
    tasks = []

    has_staging_template = state.premium and state.staging_template is not None

    if state.exterior_photo:
        tasks.append(_task_exterior_video(state))

    for si, space in enumerate(agent.spaces):
        photos = _get_space_photos(state, space, si)
        if not photos:
            continue

        prefix = _build_task_key_prefix(si)

        # Resolve room-specific staging prompt per space
        staging_prompt = (
            get_staging_prompt(state.staging_template, space.name)
            if has_staging_template else None
        )
        has_staging = staging_prompt is not None

        # 客廳/廚房用 Push In，其餘用 Rotate
        camera_prompt = (
            PROMPT_PUSH_IN if space.name in ("客廳", "廚房") else PROMPT_PAN
        )
        for idx, photo_url in enumerate(photos):
            is_last = (idx == len(photos) - 1)
            needs_reverse = has_staging and is_last
            tasks.append(_task_kling_video(
                state, prefix, idx, photo_url, camera_prompt,
                needs_reverse=needs_reverse,
            ))

        if has_staging:
            logger.info(f"[{state.job_id}] Staging {space.name} (si={si}) with room-specific prompt")
            tasks.append(_task_staging(state, prefix, photos[-1], staging_prompt))

    # TTS task runs in parallel with asset generation
    tts_task = None
    minimax = None
    if state.narration_enabled and state.narration_text:
        minimax = MiniMaxService(
            api_key=settings.minimax_api_key,
            group_id=settings.minimax_group_id,
            poll_interval=settings.minimax_poll_interval,
            poll_timeout=settings.minimax_poll_timeout,
        )
        tts_task = asyncio.create_task(
            _task_tts(state, store.r, minimax, r2_service)
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)
    state = await store.get(state.job_id)

    # Wait for TTS if running, then cleanup
    if tts_task:
        await tts_task
        await minimax.close()

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
    await _notify_progress(state, "🎬 合成影片中（約 10-20 分鐘）…")
    render_input = await _build_render_input(state)
    opening = next((s for s in render_input["scenes"] if s["type"] == "opening"), None)
    logger.info(f"[{state.job_id}] opening scene: {opening}")

    if state.preview_render_job_id:
        # Crash recovery
        result = await render_service.poll(state.preview_render_job_id)
    else:
        rid = await render_service.submit(state.job_id, render_input)
        state.preview_render_job_id = rid
        await store.save(state)
        result = await render_service.poll(rid)

    state.preview_url = result["outputUrl"]
    state.thumbnail_url = result.get("thumbnailUrl") or state.exterior_photo or next(
        (p for si in state.spaces_input for p in si.photos), None
    )
    state.status = JobStatus.delivering
    await store.save(state)


# ── Step 4: Deliver ──


async def step_deliver(state: JobState) -> None:
    logger.info(f"[{state.job_id}] step_deliver")
    # For now, final = preview (no upscale step in simplified pipeline)
    state.final_url = state.preview_url
    state.status = JobStatus.done
    await store.save(state)

    if state.line_user_id and state.final_url:
        try:
            await line_bot.send_final(
                state.line_user_id,
                state.final_url,
                state.thumbnail_url,
            )
        except Exception as e:
            logger.warning(f"[{state.job_id}] LINE send_final failed: {e}")


# ── Build RenderInput ──

OPENING_FRAMES = 450  # 15s
CLIP_FRAMES = 120  # 4s (video 1.25x speed)
CLIP_SMALL_FRAMES = 84  # 2.8s (video 1.25x speed)
STATS_FRAMES = 210  # 7s — enough for 5 items stagger animation + hold
CTA_FRAMES = 150  # 5s


async def _geocode(address: str) -> tuple[float, float] | None:
    """Geocode address via Mapbox, with Redis cache."""
    if not settings.mapbox_token or not address:
        return None

    cache_key = address.strip()
    cached = await store.get_geo_cache(cache_key)
    if cached and "lat" in cached and "lng" in cached:
        return cached["lat"], cached["lng"]

    url = "https://api.mapbox.com/search/geocode/v6/forward"
    params = {
        "q": address,
        "country": "TW",
        "limit": 1,
        "access_token": settings.mapbox_token,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        features = data.get("features", [])
        if not features:
            return None
        coords = features[0]["geometry"]["coordinates"]  # [lng, lat]
        result = {"lat": coords[1], "lng": coords[0]}
        await store.set_geo_cache(cache_key, result)
        return result["lat"], result["lng"]
    except Exception as e:
        logger.warning(f"Geocoding failed for '{address}': {e}")
        return None


async def _geocode_poi(
    poi_name: str,
    prop_lat: float,
    prop_lng: float,
) -> tuple[float, float] | None:
    """Geocode a POI via Google Places Text Search with location bias."""
    if not settings.google_places_api_key:
        return None

    cache_key = f"poi:{poi_name}:{prop_lat:.4f},{prop_lng:.4f}"
    cached = await store.get_geo_cache(cache_key)
    if cached and "lat" in cached and "lng" in cached:
        return cached["lat"], cached["lng"]

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": "places.location",
    }
    body = {
        "textQuery": poi_name,
        "locationBias": {
            "circle": {
                "center": {"latitude": prop_lat, "longitude": prop_lng},
                "radius": 2000.0,
            }
        },
        "maxResultCount": 1,
        "languageCode": "zh-TW",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        places = data.get("places", [])
        if not places:
            return None
        loc = places[0]["location"]
        result = {"lat": loc["latitude"], "lng": loc["longitude"]}
        await store.set_geo_cache(cache_key, result)
        return result["lat"], result["lng"]
    except Exception as e:
        logger.warning(f"POI geocoding failed for '{poi_name}': {e}")
        return None


async def _build_render_input(state: JobState) -> dict:
    agent = state.agent_result
    prop = agent.property
    scenes: list[dict] = []

    # Geocode address for Mapbox map
    geo = await _geocode(prop.address or prop.location or "")

    # Geocode POIs via Google Places
    if prop.pois and geo:
        prop_lat, prop_lng = geo
        for poi in prop.pois:
            if poi.lat is not None and poi.lng is not None:
                continue
            coords = await _geocode_poi(poi.name, prop_lat, prop_lng)
            if coords:
                poi.lat, poi.lng = coords

    # Opening scene
    opening_scene: dict = {"type": "opening", "durationInFrames": OPENING_FRAMES}
    if prop.pois:
        opening_scene["pois"] = [p.model_dump() for p in prop.pois]
    scenes.append(opening_scene)

    # Exterior video (separate clip after opening)
    exterior_task = state.asset_tasks.get("clip:exterior")
    if exterior_task and exterior_task.status == "completed":
        scenes.append({
            "type": "clip",
            "src": exterior_task.output_url,
            "label": "外觀",
            "durationInFrames": CLIP_FRAMES,
        })

    has_staging_template = state.premium and state.staging_template is not None

    # Clip scenes (per photo)
    for si, space in enumerate(agent.spaces):
        photos = _get_space_photos(state, space, si)
        if not photos:
            continue

        input_space = _find_input_space(state, si)
        is_small = input_space.is_small_space if input_space else False
        duration = CLIP_SMALL_FRAMES if is_small else CLIP_FRAMES
        prefix = _build_task_key_prefix(si)
        has_staging = has_staging_template and get_staging_prompt(state.staging_template, space.name) is not None

        for idx in range(len(photos)):
            clip_key = f"clip:{prefix}:{idx}"
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

            if has_staging and is_last:
                staging_task = state.asset_tasks.get(f"staging:{prefix}")
                if staging_task and staging_task.status == "completed":
                    scene["stagingImage"] = staging_task.output_url

            scenes.append(scene)

    # Background image
    bg_src = state.exterior_photo
    if not bg_src:
        for ri, space in reversed(list(enumerate(agent.spaces))):
            photos = _get_space_photos(state, space, ri)
            if photos:
                bg_src = photos[0]
                break

    scenes.append({"type": "stats", "durationInFrames": STATS_FRAMES, **({"backgroundSrc": bg_src} if bg_src else {})})
    scenes.append({"type": "cta", "durationInFrames": CTA_FRAMES, **({"backgroundSrc": bg_src} if bg_src else {})})

    render_input = {
        "title": agent.title or "",
        "location": prop.location or "",
        "address": prop.address or prop.location or "",
        "size": prop.size or "",
        "layout": prop.layout or "",
        "floor": prop.floor or "",
        "price": prop.price or "",
        "contact": prop.phone or "",
        "agentName": f"{prop.agent_name} | {prop.company}" if prop.agent_name and prop.company else prop.agent_name or "",
        "scenes": scenes,
    }

    if settings.mapbox_token:
        render_input["mapboxToken"] = settings.mapbox_token
    if geo:
        render_input["lat"] = geo[0]
        render_input["lng"] = geo[1]
    if prop.community:
        render_input["community"] = prop.community
    if prop.property_type:
        render_input["propertyType"] = prop.property_type
    if prop.building_age:
        render_input["buildingAge"] = prop.building_age
    if prop.line:
        render_input["line"] = prop.line

    # Audio
    if settings.bgm_url:
        render_input["bgm"] = settings.bgm_url
    if state.narration_url:
        render_input["narration"] = state.narration_url

    return render_input
