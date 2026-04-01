"""FastAPI Orchestrator for ReelEstate pipeline."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException

from orchestrator.models import (
    CreateJobRequest,
    DryRenderRequest,
    DryRenderResponse,
    GateCallbackRequest,
    JobResponse,
    JobState,
    JobStatus,
    SpaceInput,
)
from orchestrator.pipeline.gates import handle_gate_callback
from orchestrator.pipeline.jobs import pipeline_runner, _build_render_input
from orchestrator.pipeline.state import store
from orchestrator.services.r2 import r2_service
from orchestrator.services.render import render_service
from orchestrator.services.wavespeed import wavespeed
from orchestrator.config import settings
from orchestrator.line.bot import line_bot
from orchestrator.line.webhook import router as line_router
from orchestrator.line.conversation import ConversationManager
from orchestrator.stores.user import UserStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await store.connect()
    await r2_service.start()
    await wavespeed.start()
    await render_service.start()
    line_bot._token = settings.line_channel_access_token
    await line_bot.start()
    import orchestrator.line.webhook as line_wh
    line_wh.conv_manager = ConversationManager(store.r)
    line_wh.user_store = UserStore(store.r)

    # Resume interrupted jobs
    active_ids = await store.get_active_job_ids()
    for job_id in active_ids:
        state = await store.get(job_id)
        if state and state.status in (JobStatus.generating, JobStatus.rendering):
            logger.info(f"Resuming job {job_id} (status={state.status.value})")
            asyncio.create_task(pipeline_runner(job_id))

    yield

    # Shutdown
    await line_bot.close()
    await render_service.close()
    await wavespeed.close()
    await r2_service.close()
    await store.close()


app = FastAPI(title="ReelEstate Orchestrator", lifespan=lifespan)
app.include_router(line_router)


# ── Preprocessing ──


def _preprocess_spaces(spaces: list[SpaceInput]) -> list[SpaceInput]:
    """Preprocess space labels: strip 's' suffix (small space).
    Conventions:
    - Label ending with 's': small space (3.5s render duration), e.g. '陽台s' → '陽台'
    """
    processed: list[SpaceInput] = []
    for space in spaces:
        label = space.label
        is_small = False
        if label.endswith("s"):
            label = label[:-1]
            is_small = True
        processed.append(SpaceInput(label=label, photos=space.photos, is_small_space=is_small))
    return processed


# ── Helpers ──


def apply_overrides(render_input: dict, overrides: dict | None) -> dict:
    """Shallow-merge overrides into render_input. Scenes are patched by index."""
    if not overrides:
        return render_input
    for key, value in overrides.items():
        if key == "scenes" and isinstance(value, list):
            for patch in value:
                idx = patch["index"]
                if idx < 0 or idx >= len(render_input["scenes"]):
                    raise ValueError(f"Scene index {idx} out of range")
                fields = {k: v for k, v in patch.items() if k != "index"}
                render_input["scenes"][idx].update(fields)
        else:
            render_input[key] = value
    return render_input


# ── Routes ──


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/jobs", status_code=202)
async def create_job(req: CreateJobRequest):
    job_id = f"re_{uuid.uuid4().hex[:12]}"
    merged_spaces = _preprocess_spaces(req.spaces)
    state = JobState(
        job_id=job_id,
        raw_text=req.raw_text,
        spaces_input=merged_spaces,
        premium=req.premium,
        exterior_photo=req.exterior_photo,
        staging_template=req.staging_template,
        line_user_id=req.line_user_id,

    )
    await store.create(state)

    # Start pipeline in background
    asyncio.create_task(pipeline_runner(job_id))

    return {"job_id": job_id, "status": "analyzing"}


@app.get("/jobs")
async def list_jobs():
    active_ids = await store.get_active_job_ids()
    jobs = []
    for jid in active_ids:
        state = await store.get(jid)
        if state:
            jobs.append(
                JobResponse(
                    job_id=state.job_id,
                    status=state.status,
                    preview_url=state.preview_url,
                    final_url=state.final_url,
                    errors=state.errors,
                )
            )
    return jobs


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    state = await store.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(
        job_id=state.job_id,
        status=state.status,
        preview_url=state.preview_url,
        final_url=state.final_url,
        errors=state.errors,
    )


@app.post("/jobs/{job_id}/gate")
async def gate_callback(job_id: str, req: GateCallbackRequest):
    result = await handle_gate_callback(
        job_id=job_id,
        gate=req.gate,
        approved=req.approved,
        feedback=req.feedback,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


_READY_STATUSES = {JobStatus.rendering, JobStatus.gate_preview, JobStatus.delivering, JobStatus.done}


@app.post("/jobs/{job_id}/dry-render")
async def dry_render(job_id: str, req: DryRenderRequest = Body(default=None)):
    # 1. Load state
    state = await store.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # 2. Validate readiness
    if state.status not in _READY_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Job not ready (status={state.status.value}). Needs to be at least 'rendering'.",
        )

    # 3. Build render input from a deep copy (avoid side effects on original state)
    state_copy = JobState(**copy.deepcopy(state.model_dump()))
    render_input = await _build_render_input(state_copy)

    # 4. Apply overrides
    overrides = req.overrides.model_dump(exclude_none=True) if req and req.overrides else None
    try:
        render_input = apply_overrides(render_input, overrides)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 5. Submit with dry- prefix, use returned ID for polling
    dry_job_id = f"dry-{job_id}-{int(time.time())}"
    rid = await render_service.submit(dry_job_id, render_input)

    # 6. Poll with 20 min timeout (catch both TimeoutError and asyncio.TimeoutError)
    try:
        result = await asyncio.wait_for(
            render_service.poll(rid),
            timeout=1200,
        )
    except (TimeoutError, asyncio.TimeoutError):
        raise HTTPException(status_code=504, detail="Render timed out (20 min)")

    # 7. Return result
    return DryRenderResponse(
        render_job_id=rid,
        output_url=result["outputUrl"],
    )
