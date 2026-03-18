# Pipeline Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除 TTS/ForcedAligner/Qwen multi-angle，切換 Kling v1.6，固定 prompt，staging 改模板選擇 — 大幅簡化 pipeline。

**Architecture:** Orchestrator pipeline 從 5 步縮為 3 步（analyze → generate → render）。Kling 改為單圖 + prompt 模式，每張照片獨立生成影片。有 staging 的空間用 ffmpeg 反轉最後一個 clip。Remotion 移除 narration/captions/KenBurns。

**Tech Stack:** Python 3.12 (FastAPI + Pydantic), TypeScript (Remotion), ffmpeg, WaveSpeed API, Redis

**Spec:** `docs/superpowers/specs/2026-03-18-pipeline-simplification-design.md`

---

### Task 1: Orchestrator Models 更新

**Files:**
- Modify: `orchestrator/models.py`

- [ ] **Step 1: 更新 JobStatus enum**

移除 `gate_script`、`tts`、`gate_audio`：

```python
class JobStatus(str, Enum):
    analyzing = "analyzing"
    generating = "generating"
    rendering = "rendering"
    gate_preview = "gate_preview"
    delivering = "delivering"
    done = "done"
    failed = "failed"
```

- [ ] **Step 2: 更新 SpaceInput**

`force_ken_burns` → `is_small_space`：

```python
class SpaceInput(BaseModel):
    label: str
    photos: list[str]
    is_small_space: bool = False  # Set by _preprocess_spaces when label ends with 's'
```

- [ ] **Step 3: 簡化 SpaceInfo**

移除 VLM/角度/ken_burns 相關欄位：

```python
class SpaceInfo(BaseModel):
    name: str
    original_label: str | None = None
    photo_count: int
    photos: list[str] = []
    needs_staging: bool = False
    staging_prompt: str | None = None
```

- [ ] **Step 4: 移除 VisualObservation class**

刪除整個 `VisualObservation` class（不再需要 VLM 分析）。

- [ ] **Step 5: 簡化 AgentResult**

移除 `style_direction` 和 `estimated_video_duration_sec`：

```python
class AgentResult(BaseModel):
    property: PropertyInfo
    title: str
    narration: str
    spaces: list[SpaceInfo]
    meta: AgentMeta | None = None
```

- [ ] **Step 6: 移除 JobState 中 TTS/Alignment 欄位**

移除 `audio_url`、`sections`、`captions`、`total_duration_ms`、`total_duration_frames`。新增 `staging_template`：

```python
class JobState(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.analyzing
    raw_text: str = ""
    spaces_input: list[SpaceInput] = []
    premium: bool = False
    exterior_photo: str | None = None
    staging_template: str | None = None  # 新增
    line_user_id: str = ""
    callback_url: str = ""
    agent_result: AgentResult | None = None
    asset_tasks: dict[str, AssetTask] = {}
    preview_render_job_id: str | None = None
    preview_url: str | None = None
    final_url: str | None = None
    errors: list[str] = []
```

- [ ] **Step 7: 更新 CreateJobRequest**

新增 `staging_template`：

```python
class CreateJobRequest(BaseModel):
    raw_text: str
    spaces: list[SpaceInput]
    premium: bool = False
    exterior_photo: str | None = None
    staging_template: str | None = None  # 新增：客戶選的裝潢風格模板 key
    line_user_id: str = ""
    callback_url: str = ""
```

- [ ] **Step 8: 新增 STAGING_TEMPLATES 常數**

在 `models.py` 底部新增：

```python
STAGING_TEMPLATES: dict[str, str] = {
    "japanese_muji": (
        "Transform the interior into a Japanese Muji / Japandi style. "
        "Keep the original architecture unchanged, preserve all walls, windows, and layout. "
        "Use light wood materials, neutral color palette (beige, white, light brown), minimal furniture, clean lines. "
        "Add low-profile furniture, wooden textures, soft fabric, linen, and subtle decoration. "
        "Emphasize simplicity, calm atmosphere, and natural harmony. "
        "Soft natural lighting, airy space, uncluttered, zen feeling. "
        "Interior photography, highly realistic."
    ),
    "scandinavian": (
        "Transform the interior into a Scandinavian style. "
        "Keep the original structure unchanged. "
        "Use white and light gray base, light wood flooring, simple modern furniture. "
        "Add cozy elements like fabric sofa, soft rug, warm lighting, indoor plants. "
        "Clean, functional, and bright atmosphere. "
        "Balanced minimalism with warmth. "
        "Interior photography, natural daylight, realistic materials."
    ),
    "modern_minimalist": (
        "Transform the interior into a modern minimalist style. "
        "Preserve the original layout completely. "
        "Use monochrome palette (white, gray, black), sleek furniture, clean surfaces. "
        "Reduce decoration, emphasize open space and geometry. "
        "Add subtle lighting accents and modern materials like glass and metal. "
        "High-end, clean, elegant atmosphere. "
        "Interior photography, sharp lines, realistic rendering."
    ),
    "modern_luxury": (
        "Transform the interior into a modern luxury style. "
        "Keep original structure unchanged. "
        "Use marble textures, gold accents, dark wood, and premium materials. "
        "Add elegant furniture, layered lighting, and refined decorations. "
        "Create a sophisticated, upscale atmosphere without clutter. "
        "Interior photography, high-end real estate style, realistic lighting."
    ),
    "warm_natural": (
        "Transform the interior into a warm natural style. "
        "Preserve all architectural elements. "
        "Use warm wood tones, soft fabrics, earthy colors (beige, brown, olive). "
        "Add cozy furniture, plants, and soft lighting. "
        "Comfortable, inviting, homey atmosphere. "
        "Interior photography, natural light, realistic."
    ),
}
```

- [ ] **Step 9: 驗證 models.py 語法正確**

Run: `cd C:/Users/being/Projects/ReelEstate && python -c "from orchestrator.models import *; print('OK')"`
Expected: `OK`

---

### Task 2: WaveSpeed Service 改寫

**Files:**
- Modify: `orchestrator/services/wavespeed.py`

- [ ] **Step 1: 移除 Qwen Edit，切換 Kling model**

```python
# 移除
MODEL_QWEN_EDIT = "wavespeed-ai/qwen-image/edit-multiple-angles"

# 修改
MODEL_KLING = "kwaivgi/kling-v1.6-i2v-standard"  # was v2.5-turbo-pro
MODEL_STAGING = "google/nano-banana-2/edit"       # 不變
```

- [ ] **Step 2: 移除 qwen_edit 和 qwen_edit_submit 方法**

刪除 `qwen_edit()`（行 76-87）和 `qwen_edit_submit()`（行 89-103）。

- [ ] **Step 3: 改寫 kling_video 和 kling_submit**

從雙圖（first_frame + last_frame）改為單圖 + prompt：

```python
# Kling prompt constants
PROMPT_DRONE_UP = "Cinematic drone shot rising vertically high above the space, revealing more of the vast surroundings."
PROMPT_ROTATE = "Slow horizontal camera pan from left to right across the room"

async def kling_video(
    self,
    image_url: str,
    prompt: str,
    existing_id: str | None = None,
) -> str:
    """Generate video from single image via Kling v1.6. Returns output URL."""
    if existing_id:
        return await self.poll(existing_id)
    pid = await self.kling_submit(image_url, prompt)
    return await self.poll(pid)

async def kling_submit(self, image_url: str, prompt: str) -> str:
    """Submit Kling video, return prediction_id."""
    return await self.submit(
        MODEL_KLING,
        {
            "image": image_url,
            "duration": 5,
            "prompt": prompt,
            "guidance_scale": 0.3,
        },
    )
```

- [ ] **Step 4: 驗證 wavespeed.py 語法正確**

Run: `cd C:/Users/being/Projects/ReelEstate && python -c "from orchestrator.services.wavespeed import wavespeed; print('OK')"`
Expected: `OK`

---

### Task 3: Preprocess Spaces 改寫

**Files:**
- Modify: `orchestrator/main.py`

- [ ] **Step 1: 改寫 _preprocess_spaces()**

移除 `k` 後綴 / `.1` 配對邏輯，改為 `s` 後綴處理：

```python
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
```

- [ ] **Step 2: 更新 create_job route**

在 `create_job` 中把 `staging_template` 傳進 JobState：

```python
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
        staging_template=req.staging_template,  # 新增
        line_user_id=req.line_user_id,
        callback_url=req.callback_url,
    )
    await store.create(state)
    asyncio.create_task(pipeline_runner(job_id))
    return {"job_id": job_id, "status": "analyzing"}
```

- [ ] **Step 3: 移除 minimax_tts 和 worker_c 的 import 和 lifecycle**

從 `main.py` 移除：
- `from orchestrator.services.minimax_tts import minimax_tts`
- `from orchestrator.services.worker_c import worker_c`
- lifespan 中的 `await worker_c.start()` / `await worker_c.close()`
- lifespan 中的 `await minimax_tts.start()` / `await minimax_tts.close()`

- [ ] **Step 4: 更新 resume logic**

lifespan 中 `state.status in (...)` 也要更新（移除 `JobStatus.tts` 等已不存在的狀態）。目前只 resume `generating` 和 `rendering`，這兩個保留即可，不需改動。

- [ ] **Step 5: 驗證 main.py 語法正確**

Run: `cd C:/Users/being/Projects/ReelEstate && python -c "from orchestrator.main import app; print('OK')"`
Expected: `OK`

---

### Task 4: Gates 簡化

**Files:**
- Modify: `orchestrator/pipeline/gates.py`

- [ ] **Step 1: 只保留 preview gate**

```python
GATE_STATUS_MAP = {
    "preview": JobStatus.gate_preview,
}

GATE_NEXT_STATUS = {
    "preview": JobStatus.delivering,
}
```

- [ ] **Step 2: 驗證 gates.py 語法正確**

Run: `cd C:/Users/being/Projects/ReelEstate && python -c "from orchestrator.pipeline.gates import handle_gate_callback; print('OK')"`
Expected: `OK`

---

### Task 5: Telegram Bot 簡化

**Files:**
- Modify: `orchestrator/telegram/bot.py`

- [ ] **Step 1: 移除 send_gate_script 和 send_gate_audio 方法**

刪除 `send_gate_script()`（行 84-92）和 `send_gate_audio()`（行 94-103）。保留 `send_gate_preview`、`send_final`、基礎 `send_message`/`send_audio`/`send_video`。

- [ ] **Step 2: 驗證 bot.py 語法正確**

Run: `cd C:/Users/being/Projects/ReelEstate && python -c "from orchestrator.telegram.bot import telegram_bot; print('OK')"`
Expected: `OK`

---

### Task 6: Agent Service 簡化

**Files:**
- Modify: `orchestrator/services/agent.py`

- [ ] **Step 1: 移除照片 image blocks**

修改 `_build_user_content()`，不再附加照片 URL 作為 image content blocks：

```python
def _build_user_content(
    raw_text: str,
    spaces: list[SpaceInput],
    premium: bool,
) -> list[dict]:
    """Build user message content blocks: JSON text only (no images)."""
    input_json = {
        "raw_text": raw_text,
        "spaces": [{"label": s.label, "photos": s.photos} for s in spaces],
        "premium": premium,
    }
    return [{"type": "text", "text": json.dumps(input_json, ensure_ascii=False)}]
```

- [ ] **Step 2: 驗證 agent.py 語法正確**

Run: `cd C:/Users/being/Projects/ReelEstate && python -c "from orchestrator.services.agent import agent_service; print('OK')"`
Expected: `OK`

---

### Task 7: Pipeline Jobs 大改寫

**Files:**
- Modify: `orchestrator/pipeline/jobs.py`

這是改動量最大的檔案，分步驟處理。

- [ ] **Step 1: 清理 imports**

移除不再需要的 imports：

```python
# 移除
from orchestrator.services.minimax_tts import minimax_tts
from orchestrator.services.worker_c import worker_c

# 新增
import subprocess
import tempfile

import httpx
```

保留的 imports：
```python
from orchestrator.services.wavespeed import wavespeed, PROMPT_DRONE_UP, PROMPT_ROTATE
from orchestrator.models import AssetTask, JobState, JobStatus, SpaceInfo, SpaceInput, STAGING_TEMPLATES
```

- [ ] **Step 2: 改寫 pipeline_runner**

移除 TTS/gate_script/gate_audio 步驟：

```python
async def pipeline_runner(job_id: str) -> None:
    """Run the full pipeline, resuming from current status."""
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
            return  # Wait for gate callback
        if state.status == JobStatus.delivering:
            await step_deliver(state)
    except Exception as e:
        logger.exception(f"Pipeline failed for job {job_id}")
        await store.append_error(job_id, str(e))
        await store.set_status(job_id, JobStatus.failed)
```

- [ ] **Step 3: 改寫 step_analyze**

分析完直接進入 `generating`（跳過 gate_script）：

```python
async def step_analyze(state: JobState) -> None:
    logger.info(f"[{state.job_id}] step_analyze")
    result = await agent_service.analyze(
        raw_text=state.raw_text,
        spaces=state.spaces_input,
        premium=state.premium,
    )
    state.agent_result = result
    state.status = JobStatus.generating  # 直接進入 generating，不觸發 gate
    await store.save(state)

    if result.meta:
        if result.meta.warnings:
            logger.warning(f"[{state.job_id}] Agent warnings: {result.meta.warnings}")
        if result.meta.missing_fields:
            logger.warning(f"[{state.job_id}] Agent missing fields: {result.meta.missing_fields}")
```

- [ ] **Step 4: 刪除 step_tts**

刪除整個 `step_tts` function（行 107-137）。

- [ ] **Step 5: 新增 _reverse_video helper**

```python
async def _reverse_video(video_url: str) -> str:
    """Download video, reverse with ffmpeg, upload to R2. Returns new URL."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(video_url)
        resp.raise_for_status()
        video_bytes = resp.content

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f_in:
        f_in.write(video_bytes)
        in_path = f_in.name

    out_path = in_path.replace(".mp4", "_reversed.mp4")
    try:
        proc = await asyncio.get_event_loop().run_in_executor(
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

        import uuid as _uuid
        key = f"clips/reversed_{_uuid.uuid4().hex[:8]}.mp4"
        return await r2_service.upload_bytes(reversed_bytes, key, content_type="video/mp4")
    finally:
        import os
        os.unlink(in_path)
        if os.path.exists(out_path):
            os.unlink(out_path)
```

- [ ] **Step 6: 新增 _task_kling_video**

取代 `_task_clip_direct` 和 `_task_angle_then_clip`：

```python
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

        # Reverse if needed (last clip in space with staging)
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
```

- [ ] **Step 7: 新增 _task_exterior_video**

```python
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
        # Non-critical: don't raise
        logger.warning(f"Exterior video failed: {e}")
```

- [ ] **Step 8: 改寫 step_generate**

```python
async def step_generate(state: JobState) -> None:
    logger.info(f"[{state.job_id}] step_generate")
    state.status = JobStatus.generating
    await store.save(state)

    agent = state.agent_result
    tasks = []

    # Determine staging prompt from template
    staging_prompt = None
    if state.premium and state.staging_template:
        staging_prompt = STAGING_TEMPLATES.get(state.staging_template)

    # Exterior video (non-critical)
    if state.exterior_photo:
        tasks.append(_task_exterior_video(state))

    # Per-space, per-photo Kling tasks
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

        # Staging (premium only)
        if has_staging:
            # Use last photo for staging
            tasks.append(_task_staging(state, space.name, photos[-1], staging_prompt))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    state = await store.get(state.job_id)

    for r in results:
        if isinstance(r, Exception):
            await store.append_error(state.job_id, str(r))

    # Check for critical failures (clips only, not exterior or staging)
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
```

- [ ] **Step 9: 刪除舊 task functions**

刪除：
- `_task_align()`（行 218-253）
- `_task_clip_direct()`（行 256-284）
- `_task_angle_then_clip()`（行 287-343）

保留 `_task_staging()`（不變）和 `_find_input_space()`（不變）。

- [ ] **Step 10: 改寫 _build_render_input**

```python
# Fixed durations (frames at 30fps)
OPENING_FRAMES = 300       # 10s
CLIP_FRAMES = 150          # 5s
CLIP_SMALL_FRAMES = 105    # 3.5s
STATS_FRAMES = 140         # ~4.7s
CTA_FRAMES = 90            # 3s


def _build_render_input(state: JobState) -> dict:
    """Assemble RenderInput dict matching remotion/server/types.ts."""
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

    # Determine staging prompt
    staging_prompt = None
    if state.premium and state.staging_template:
        staging_prompt = STAGING_TEMPLATES.get(state.staging_template)

    # Clip scenes (per photo)
    for space in agent.spaces:
        input_space = _find_input_space(state, space)
        if input_space is None:
            continue

        is_small = input_space.is_small_space if input_space else False
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

            # Attach staging to last clip of space
            if staging_prompt and is_last:
                staging_task = state.asset_tasks.get(f"staging:{space.name}")
                if staging_task and staging_task.status == "completed":
                    scene["stagingImage"] = staging_task.output_url

            scenes.append(scene)

    # Background image for stats/cta
    bg_src = state.exterior_photo
    if not bg_src:
        for space in reversed(agent.spaces):
            input_space = _find_input_space(state, space)
            if input_space and input_space.photos:
                bg_src = input_space.photos[0]
                break

    # Stats scene
    scenes.append({"type": "stats", "durationInFrames": STATS_FRAMES, **({"backgroundSrc": bg_src} if bg_src else {})})

    # CTA scene
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
```

- [ ] **Step 11: 驗證 jobs.py 語法正確**

Run: `cd C:/Users/being/Projects/ReelEstate && python -c "from orchestrator.pipeline.jobs import pipeline_runner; print('OK')"`
Expected: `OK`

---

### Task 8: Config 清理

**Files:**
- Modify: `orchestrator/config.py`

- [ ] **Step 1: 移除 MiniMax TTS 和 RunPod Worker C 設定**

刪除以下欄位（保留檔案結構，只移除不用的設定）：

```python
# 移除這些
runpod_api_key: str = ""
runpod_endpoint_c: str = "391h73cn715crm"
runpod_poll_interval: float = 2.0
runpod_poll_timeout: float = 180.0

minimax_api_key: str = ""
minimax_group_id: str = ""
minimax_model: str = "speech-02-hd"
minimax_voice_id: str = "Chinese_casual_guide_vv2"
minimax_voice_speed: float = 1.0
minimax_voice_emotion: str = "neutral"
```

- [ ] **Step 2: 驗證 config.py**

Run: `cd C:/Users/being/Projects/ReelEstate && python -c "from orchestrator.config import settings; print('OK')"`
Expected: `OK`

---

### Task 9: Dockerfile 加裝 ffmpeg

**Files:**
- Modify: `orchestrator/Dockerfile`

- [ ] **Step 1: 安裝 ffmpeg**

在 `RUN pip install` 之前加入：

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install ffmpeg for video reversal
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

COPY orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY orchestrator/ /app/orchestrator/
COPY agent/SKILL.md /app/agent/SKILL.md

EXPOSE 8000

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### Task 10: Remotion Types 更新

**Files:**
- Modify: `remotion/src/types.ts`

- [ ] **Step 1: 移除不用的 types，更新 OpeningSceneInput**

```typescript
import type { Caption } from "@remotion/captions";  // 移除此 import

export type OpeningSceneInput = {
  type: "opening";
  durationInFrames: number;
  exteriorVideo?: string;   // 重命名：was exteriorPhoto
  pois?: POI[];
};

export type ClipSceneInput = {
  type: "clip";
  src: string;
  label: string;
  durationInFrames: number;
  stagingImage?: string;
};

export type StatsSceneInput = {
  type: "stats";
  durationInFrames: number;
  backgroundSrc?: string;
};

export type CTASceneInput = {
  type: "cta";
  durationInFrames: number;
  backgroundSrc?: string;
};

export type POI = {
  name: string;
  category: "mrt" | "supermarket" | "park" | "school" | "hospital" | "other";
  distance: string;
  lat?: number;
  lng?: number;
};

// 移除 KenBurnsSceneInput
// 移除 LocationSceneInput

export type SceneInput =
  | OpeningSceneInput
  | ClipSceneInput
  | StatsSceneInput
  | CTASceneInput;

export type VideoInput = {
  title: string;
  location: string;
  address: string;
  community?: string;
  propertyType?: string;
  buildingAge?: string;
  size: string;
  layout: string;
  floor: string;
  price: string;
  contact: string;
  line?: string;
  agentName: string;
  scenes: SceneInput[];
  bgm?: string;
  mapboxToken?: string;
  lat?: number;
  lng?: number;
  // 移除 narration, captions
};
```

---

### Task 11: ReelEstateVideo.tsx 簡化

**Files:**
- Modify: `remotion/src/ReelEstateVideo.tsx`

- [ ] **Step 1: 移除 imports**

```typescript
// 移除
import { Audio } from "@remotion/media";
import { KenBurnsScene } from "./compositions/KenBurnsScene";
import { LocationScene } from "./compositions/LocationScene";
import { CaptionsOverlay } from "./compositions/CaptionsOverlay";
```

- [ ] **Step 2: 從 props 解構中移除 narration/captions**

```typescript
const {
  title, location, address, size, layout, floor,
  price, contact, line, agentName, scenes, bgm,  // 移除 narration, captions
} = props;
```

- [ ] **Step 3: 移除 switch 中的 ken_burns 和 location case**

刪除 `case "ken_burns":` 和 `case "location":` 區塊（行 99-136）。

- [ ] **Step 4: 移除 calcTotalFrames 中的 ken_burns 處理**

在 `needsFadeBetween()` 中移除 `ken_burns` 判斷：

```typescript
function needsFadeBetween(curr: SceneInput, next: SceneInput): boolean {
  if (
    curr.type === "clip" && next.type === "clip" &&
    curr.label === next.label
  ) {
    return false;
  }
  return true;
}
```

`calcTotalFrames()` 中也移除 `scene.type === "ken_burns"` 的判斷。

- [ ] **Step 5: 移除 Audio (narration) 和 CaptionsOverlay**

在 return JSX 中：
- 移除 `<Audio src={staticFile(narration)} volume={1} />`
- 移除 CaptionsOverlay Sequence 區塊
- 保留 BGM Audio

```tsx
return (
  <AbsoluteFill style={{ background: "#000" }}>
    <TransitionSeries>{seriesItems}</TransitionSeries>
    {bgm && <Audio src={staticFile(bgm)} volume={0.15} loop />}
  </AbsoluteFill>
);
```

- [ ] **Step 6: 驗證 TypeScript 編譯**

Run: `cd C:/Users/being/Projects/ReelEstate/remotion && npx tsc --noEmit`
Expected: 無 error（可能有 warning，只要沒 error 就 OK）

---

### Task 12: OpeningScene 改用影片

**Files:**
- Modify: `remotion/src/compositions/OpeningScene.tsx`

- [ ] **Step 1: 加入 Video import**

```typescript
import { AbsoluteFill, Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { OffthreadVideo } from "remotion";  // 新增
```

- [ ] **Step 2: 更新 Props type**

```typescript
type Props = {
  title: string;
  location: string;
  address: string;
  community?: string;
  propertyType?: string;
  buildingAge?: string;
  floor?: string;
  mapboxToken?: string;
  lat?: number;
  lng?: number;
  exteriorVideo?: string;  // 重命名 exteriorPhoto → exteriorVideo
  pois?: POI[];
};
```

- [ ] **Step 3: 更新組件內的 exteriorPhoto → exteriorVideo**

在函數參數解構、`showExterior` 判斷中，全部改為 `exteriorVideo`。

- [ ] **Step 4: 把 `<Img>` 改為 `<OffthreadVideo>`**

將外觀部分的 `<Img>` 替換為影片播放，移除 Ken Burns scale 效果：

```tsx
{showExterior && (
  <AbsoluteFill style={{ opacity: exteriorOpacity, overflow: "hidden" }}>
    <OffthreadVideo
      src={exteriorVideo!}
      style={{
        width: "100%",
        height: "100%",
        objectFit: "cover",
      }}
    />
  </AbsoluteFill>
)}
```

移除 `exteriorScale` 相關的 interpolate（不再需要 Ken Burns zoom）。

- [ ] **Step 5: 驗證 TypeScript 編譯**

Run: `cd C:/Users/being/Projects/ReelEstate/remotion && npx tsc --noEmit`
Expected: 無 error

---

### Task 13: 清理不用的 Remotion 組件

**Files:**
- Delete or mark unused: `remotion/src/compositions/KenBurnsScene.tsx`
- Delete or mark unused: `remotion/src/compositions/CaptionsOverlay.tsx`
- Delete or mark unused: `remotion/src/compositions/LocationScene.tsx`

- [ ] **Step 1: 刪除三個不再使用的組件檔案**

```bash
cd C:/Users/being/Projects/ReelEstate/remotion
rm src/compositions/KenBurnsScene.tsx
rm src/compositions/CaptionsOverlay.tsx
rm src/compositions/LocationScene.tsx
```

- [ ] **Step 2: 確認沒有其他檔案 import 這些組件**

Run: `grep -r "KenBurnsScene\|CaptionsOverlay\|LocationScene" C:/Users/being/Projects/ReelEstate/remotion/src/ --include="*.tsx" --include="*.ts"`
Expected: 無結果（已在 Task 11 中從 ReelEstateVideo.tsx 移除 import）

- [ ] **Step 3: 驗證 TypeScript 編譯**

Run: `cd C:/Users/being/Projects/ReelEstate/remotion && npx tsc --noEmit`
Expected: 無 error

---

### Task 14: Agent SKILL.md 精簡

**Files:**
- Modify: `agent/SKILL.md`

- [ ] **Step 1: 讀取現有 SKILL.md**

先讀取 `C:\Users\being\Projects\ReelEstate\agent\SKILL.md` 了解結構。

- [ ] **Step 2: 精簡 SKILL.md**

保留：
- 物件資訊提取（PropertyInfo 所有欄位）
- 標題生成（5-8 字）
- 講稿生成（帶 section markers，僅參考用）
- 空間名稱整理

移除：
- VLM 照片分析指引
- `visual_observations` 輸出要求
- `horizontal_angle` / `angle_reasoning` 輸出要求
- `needs_second_angle` 輸出要求
- `use_ken_burns` 輸出要求
- `style_direction` 輸出要求
- `staging_prompt` 生成指引（Agent 不再決定裝潢風格）
- `estimated_video_duration_sec` 輸出要求

更新 JSON 輸出格式範例，使之與新的 `AgentResult` / `SpaceInfo` model 一致。

- [ ] **Step 3: 驗證 SKILL.md 中的 JSON 範例可被 AgentResult 解析**

寫一個簡單測試：拷貝 SKILL.md 中的 JSON 範例，確認 `AgentResult.model_validate_json()` 能解析。

---

### Task 15: 整合驗證

- [ ] **Step 1: Orchestrator 全模組 import 測試**

Run: `cd C:/Users/being/Projects/ReelEstate && python -c "from orchestrator.main import app; from orchestrator.pipeline.jobs import pipeline_runner; from orchestrator.pipeline.gates import handle_gate_callback; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 2: Remotion TypeScript 編譯**

Run: `cd C:/Users/being/Projects/ReelEstate/remotion && npx tsc --noEmit`
Expected: 無 error

- [ ] **Step 3: Docker build 測試**

Run: `cd C:/Users/being/Projects/ReelEstate && docker build -f orchestrator/Dockerfile -t reelestate-orchestrator-test .`
Expected: Build 成功

- [ ] **Step 4: 驗證 ffmpeg 在 Docker 中可用**

Run: `docker run --rm reelestate-orchestrator-test ffmpeg -version`
Expected: 顯示 ffmpeg 版本資訊

- [ ] **Step 5: 準備測試 input.json mock**

建立一個 mock input.json 用於本地 Remotion preview 測試，確認新的 scene 結構能正確 render。格式應遵循新的 types（無 narration/captions/ken_burns，有 exteriorVideo）。

---

### Task 16: 更新 Memory

- [ ] **Step 1: 更新 project memory**

更新 `C:\Users\being\.claude\projects\C--Users-being\memory\MEMORY.md` 和相關 memory 檔案，反映：
- Kling 版本變更
- Qwen multi-angle 移除
- TTS/ForcedAligner 移除
- 新的空間標記慣例
- Staging 模板機制
- 新的 pipeline 流程
