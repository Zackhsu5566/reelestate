# TTS Subtitle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch MiniMax TTS from async to sync endpoint to get sentence-level subtitles, then display them in the Remotion video.

**Architecture:** MiniMax sync `t2a_v2` returns audio + subtitle in one call. Subtitles stored in JobState and passed to Remotion as `narrationSubtitles`. A new `SubtitleOverlay` component renders them time-synced over the video.

**Tech Stack:** Python (aiohttp, Pydantic), TypeScript (Remotion, React)

**Spec:** `docs/superpowers/specs/2026-03-25-tts-subtitle-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `orchestrator/services/minimax.py` | Switch to sync endpoint, return audio + subtitles |
| Modify | `orchestrator/models.py` | Add `narration_subtitles` + `narration_subtitles_url` fields |
| Modify | `orchestrator/pipeline/state.py` | Add subtitle fields to `_NARRATION_FIELDS` |
| Modify | `orchestrator/pipeline/jobs.py` | Handle subtitle in `_task_tts`, pass to render input |
| Modify | `orchestrator/tests/test_minimax.py` | Update tests for new return type |
| Modify | `remotion/src/types.ts` | Add `NarrationSubtitle` type and `narrationSubtitles` to `VideoInput` |
| Create | `remotion/src/components/SubtitleOverlay.tsx` | Subtitle display component |
| Modify | `remotion/src/ReelEstateVideo.tsx` | Integrate `SubtitleOverlay` |

---

### Task 1: MiniMax service — switch to sync endpoint

**Files:**
- Modify: `orchestrator/services/minimax.py`
- Test: `orchestrator/tests/test_minimax.py`

- [ ] **Step 1: Update test for new return type**

Update `orchestrator/tests/test_minimax.py` — `synthesize` now returns `tuple[bytes, list[dict]] | None`:

```python
async def test_synthesize_success(service):
    # ... existing mock setup ...
    result = await service.synthesize("測試講稿")
    assert result is not None
    audio, subtitles = result
    assert audio == b"fake-audio"
    assert isinstance(subtitles, list)
```

```python
async def test_synthesize_returns_none_on_failure(service):
    # ... existing mock for failure ...
    result = await service.synthesize("測試")
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && python -m pytest tests/test_minimax.py -v`
Expected: FAIL (return type changed)

- [ ] **Step 3: Rewrite `_synthesize_inner` to use sync endpoint**

In `orchestrator/services/minimax.py`, replace the async flow (`_create_task` → `_poll_task` → `_download_audio`) with a single sync call:

```python
async def synthesize(self, narration_text: str) -> tuple[bytes, list[dict]] | None:
    """Full TTS pipeline with 1 retry. Returns (audio_bytes, subtitles) or None."""
    async with _tts_semaphore:
        for attempt in range(2):
            try:
                result = await self._synthesize_inner(narration_text)
                if result is not None:
                    return result
                if attempt == 0:
                    logger.warning("TTS attempt 1 failed, retrying in 5s...")
                    await asyncio.sleep(5)
            except Exception:
                logger.exception("TTS synthesis failed (attempt %d)", attempt + 1)
                if attempt == 0:
                    await asyncio.sleep(5)
        return None

async def _synthesize_inner(self, narration_text: str) -> tuple[bytes, list[dict]] | None:
    text = self._strip_markers(narration_text)
    text = _t2s.convert(text)
    session = await self._get_session()

    url = f"{_BASE_URL}/t2a_v2?GroupId={self.group_id}"
    payload = {
        "model": "speech-2.8-hd",
        "text": text,
        "voice_setting": {
            "voice_id": "Chinese_casual_guide_vv2",
            "speed": 1.0,
            "language_boost": "Chinese",
        },
        "audio_setting": {
            "format": "mp3",
            "sample_rate": 32000,
        },
        "subtitle_enable": True,
    }

    try:
        resp = await session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=self.poll_timeout))
        if resp.status != 200:
            body = await resp.text()
            logger.warning("TTS sync failed: status=%d body=%s", resp.status, body[:200])
            return None

        data = await resp.json()
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code") != 0:
            logger.warning("TTS sync error: %s", base_resp)
            return None

        # Decode audio from hex
        audio_hex = data.get("data", {}).get("audio")
        if not audio_hex:
            logger.warning("TTS sync: no audio in response")
            return None
        audio_bytes = bytes.fromhex(audio_hex)

        # Fetch subtitles
        subtitles = []
        subtitle_url = data.get("data", {}).get("subtitle_file")
        if subtitle_url:
            try:
                sub_resp = await session.get(subtitle_url)
                if sub_resp.status == 200:
                    subtitles = await sub_resp.json()
            except Exception:
                logger.warning("Failed to fetch subtitle file, continuing without subtitles")

        return audio_bytes, subtitles

    except asyncio.TimeoutError:
        logger.warning("TTS sync timeout after %.0fs", self.poll_timeout)
        return None
    except Exception:
        logger.exception("TTS sync error")
        return None
```

Remove the old methods: `_create_task`, `_poll_task`, `_download_audio`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_minimax.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/services/minimax.py orchestrator/tests/test_minimax.py
git commit -m "refactor: switch MiniMax TTS to sync endpoint with subtitle support"
```

---

### Task 2: Add subtitle fields to JobState

**Files:**
- Modify: `orchestrator/models.py:122-127`
- Modify: `orchestrator/pipeline/state.py:77-80`

- [ ] **Step 1: Add fields to `JobState`**

In `orchestrator/models.py`, add after `narration_url`:

```python
    narration_subtitles: list[dict] | None = None
    narration_subtitles_url: str | None = None
```

- [ ] **Step 2: Add to `_NARRATION_FIELDS` in state.py**

In `orchestrator/pipeline/state.py`, update:

```python
_NARRATION_FIELDS = {
    "narration_enabled", "narration_gate_status",
    "narration_text", "narration_task_id", "narration_url",
    "narration_subtitles", "narration_subtitles_url",
}
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/models.py orchestrator/pipeline/state.py
git commit -m "feat: add narration_subtitles fields to JobState"
```

---

### Task 3: Update `_task_tts` to handle subtitles

**Files:**
- Modify: `orchestrator/pipeline/jobs.py:79-140`
- Modify: `orchestrator/pipeline/jobs.py:701-702`

- [ ] **Step 1: Update `_task_tts` to store subtitles**

In `orchestrator/pipeline/jobs.py`, update the TTS result handling (after line 114):

```python
    # Run TTS
    result = await minimax.synthesize(final_text)
    if not result:
        logger.warning("TTS failed, degrading to no narration: job=%s", job_id)
        await store.update_narration(job_id, narration_url=None)
        return

    audio_bytes, subtitles = result
```

Keep the ffprobe duration logging as-is. Then update the R2 upload section:

```python
    # Upload audio to R2
    r2_key = f"audio/{job_id}/narration.mp3"
    narration_url = await r2.upload_bytes(audio_bytes, r2_key, "audio/mpeg")

    # Upload subtitles to R2
    subtitles_url = None
    if subtitles:
        import json
        sub_key = f"audio/{job_id}/subtitles.json"
        subtitles_url = await r2.upload_bytes(
            json.dumps(subtitles).encode(), sub_key, "application/json"
        )

    await store.update_narration(
        job_id,
        narration_url=narration_url,
        narration_subtitles=subtitles,
        narration_subtitles_url=subtitles_url,
    )
```

- [ ] **Step 2: Pass subtitles to render input**

In `orchestrator/pipeline/jobs.py`, after line 702 (`render_input["narration"] = ...`), add:

```python
    if state.narration_subtitles:
        render_input["narrationSubtitles"] = state.narration_subtitles
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/pipeline/jobs.py
git commit -m "feat: store and pass narration subtitles through pipeline"
```

---

### Task 4: Remotion — add subtitle type and `SubtitleOverlay` component

**Files:**
- Modify: `remotion/src/types.ts`
- Create: `remotion/src/components/SubtitleOverlay.tsx`

- [ ] **Step 1: Add types**

In `remotion/src/types.ts`, add before `VideoInput`:

```typescript
export type NarrationSubtitle = {
  text: string;
  time_begin: number; // milliseconds
  time_end: number;   // milliseconds
};
```

Add to `VideoInput`:

```typescript
  narrationSubtitles?: NarrationSubtitle[];
```

- [ ] **Step 2: Create `SubtitleOverlay` component**

Create `remotion/src/components/SubtitleOverlay.tsx`:

```tsx
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansTC";
import type { NarrationSubtitle } from "../types";

const { fontFamily } = loadFont("normal", { weights: ["700"] });

const FADE_FRAMES = 5;

type Props = {
  subtitles: NarrationSubtitle[];
};

export const SubtitleOverlay: React.FC<Props> = ({ subtitles }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const timeMs = (frame / fps) * 1000;

  const active = subtitles.find(
    (s) => timeMs >= s.time_begin && timeMs <= s.time_end,
  );

  if (!active) return null;

  const startFrame = (active.time_begin / 1000) * fps;
  const endFrame = (active.time_end / 1000) * fps;

  const fadeIn = interpolate(frame, [startFrame, startFrame + FADE_FRAMES], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [endFrame - FADE_FRAMES, endFrame], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        bottom: 120,
        left: 40,
        right: 40,
        display: "flex",
        justifyContent: "center",
        opacity: Math.min(fadeIn, fadeOut),
      }}
    >
      <div
        style={{
          background: "rgba(0, 0, 0, 0.7)",
          backdropFilter: "blur(8px)",
          borderRadius: 12,
          padding: "16px 28px",
          maxWidth: 900,
        }}
      >
        <div
          style={{
            color: "#fff",
            fontSize: 36,
            fontWeight: 700,
            fontFamily,
            textAlign: "center",
            lineHeight: 1.4,
          }}
        >
          {active.text}
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 3: Commit**

```bash
git add remotion/src/types.ts remotion/src/components/SubtitleOverlay.tsx
git commit -m "feat: add SubtitleOverlay component for narration subtitles"
```

---

### Task 5: Integrate `SubtitleOverlay` into `ReelEstateVideo`

**Files:**
- Modify: `remotion/src/ReelEstateVideo.tsx:72-198`

- [ ] **Step 1: Add SubtitleOverlay to the video**

In `remotion/src/ReelEstateVideo.tsx`:

1. Import: `import { SubtitleOverlay } from "./components/SubtitleOverlay";`
2. Destructure: add `narrationSubtitles` to the destructured props (line 75)
3. Add overlay before `</AbsoluteFill>` (after the Audio elements):

```tsx
      {narrationSubtitles && narrationSubtitles.length > 0 && (
        <SubtitleOverlay subtitles={narrationSubtitles} />
      )}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd remotion && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add remotion/src/ReelEstateVideo.tsx
git commit -m "feat: integrate subtitle overlay into ReelEstateVideo"
```

---

### Task 6: Remove exploratory log + cleanup

**Files:**
- Modify: `orchestrator/services/minimax.py`

- [ ] **Step 1: Remove the test log line**

Remove the `logger.info("TTS poll success response: %s", data)` line added earlier for testing (no longer needed since we switched to sync endpoint — the old `_poll_task` method is removed).

- [ ] **Step 2: Commit**

```bash
git add orchestrator/services/minimax.py
git commit -m "chore: remove exploratory TTS log"
```

---

### Task 7: Deploy and verify

- [ ] **Step 1: Push to GitHub**

```bash
git push origin master
```

- [ ] **Step 2: Deploy orchestrator**

```bash
ssh root@187.77.150.149 "cd /opt/reelestate && git pull && cd orchestrator && docker compose up -d --build"
```

- [ ] **Step 3: Deploy Remotion render server**

```bash
ssh root@187.77.150.149 "cd /opt/reelestate && git pull && cd remotion && docker build -t reelestate-remotion . && docker stop reelestate-remotion && docker rm reelestate-remotion && docker run -d --name reelestate-remotion --restart unless-stopped -p 3100:3000 -e PORT=3000 -e RENDER_API_TOKEN=reelestate-render-token-2024 -e R2_PROXY_URL=\$R2_PROXY_URL -e R2_UPLOAD_TOKEN=\$R2_UPLOAD_TOKEN reelestate-remotion"
```

- [ ] **Step 4: Verify both services healthy**

```bash
ssh root@187.77.150.149 "docker logs orchestrator-orchestrator-1 --tail 5"
curl -sk https://187.77.150.149/health -H "Host: render.replowapp.com" -H "Authorization: Bearer reelestate-render-token-2024"
```

- [ ] **Step 5: Trigger a test job and verify subtitles appear in output video**
