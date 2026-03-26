# ~~TTS Scene Alignment Design~~ (SUPERSEDED)

> **已淘汰**：此設計（char offset 拆分）已被 `2026-03-26-per-scene-tts-alignment-design.md` 取代。
> 新方案採用 per-scene TTS（每段 section 獨立呼叫 MiniMax），消除繁簡轉換導致的對齊問題。

## 背景

目前 TTS 產出一段連續的 narration.mp3，從 frame 0 開始播放，與場景時長無同步關係。旁白內容可能跟畫面不對齊（例如講「客廳」時畫面已經切到「主臥」）。

## 目標

讓每段旁白的播放時間對齊對應場景的起始時間，場景時長維持固定常數不變。

## 設計

### 核心概念

1. TTS 維持**單次呼叫**，產出完整音訊 + 字幕
2. 在 orchestrator 端用**字幕時間戳 + section marker** 拆分音訊段落
3. 計算每個場景的起始毫秒，在音訊段落之間**插入靜音 padding** 讓段落對齊場景
4. 同步調整字幕時間戳
5. Remotion 端**零改動**

### Section Marker 對應

講稿帶有 `[OPENING]`、`[空間名]`、`[MAP]`、`[STATS]`、`[CTA]` 等 marker。

對應策略：
1. 送 TTS 前，按 marker 拆分講稿，記錄每段的原始文字及其在完整文本中的**字元位移**（start_char, end_char）
2. Strip markers 和 `<#秒數#>` pause markers 後得到純文字，送 MiniMax
3. 拿到字幕後，用**累計字元位移**分配：每句字幕的文字在純文本中有對應位置，根據位置落在哪個 section 的 char range 來歸類
4. 每個 section 的音訊範圍 = 第一句 `time_begin` ~ 最後一句 `time_end`

> 為什麼用字元位移而非逐句比對：MiniMax 的斷句方式可能與原始段落不同（合句、拆句），繁簡轉換也會影響文字。字元位移更穩健。

Scene mapping：

| Section Marker | 對應場景 | 起始時間 |
|---|---|---|
| `[OPENING]` | HookScene 開頭（frame 0） | 0ms |
| `[空間名]` | 該空間**第一個** ClipScene 的起始 frame | 根據前面場景累計 |
| `[MAP]` | MapScene | 同上 |
| `[STATS]` | StatsScene | 同上 |
| `[CTA]` | CTAScene | 同上 |

**一個空間多個 clip 的處理**：`[客廳]` 的旁白從該空間第一個 clip 開始播放。若空間有多個 clip + staging，旁白的可用時長 = 所有 clip 的 durationInFrames + HOLD_FRAMES + STAGING_FRAMES - 各轉場 overlap。

### 場景起始時間計算

需精確 mirror Remotion 端 `calcTotalFrames()` 的邏輯。常數來源為 `remotion/src/ReelEstateVideo.tsx`：

```python
# Source of truth: remotion/src/ReelEstateVideo.tsx lines 15-20
FADE_FRAMES = 10            # ~0.33s fade between scenes
WIPE_FRAMES = 28            # ~0.93s wipe to staging
STAGING_FRAMES = 90         # 3s staging display
HOLD_FRAMES = 35            # ~1.17s freeze before staging wipe
HOOK_FRAMES_PER_IMAGE = 30  # 1s per hook image
MAX_HOOK_IMAGES = 3
FPS = 30
```

**虛擬碼**（mirror `calcTotalFrames` + 記錄每場景起始 frame）：

```python
def calc_scene_start_times(scenes, hook_image_count):
    """回傳 dict: scene_index → start_ms"""
    starts = {}
    cursor = hook_image_count * HOOK_FRAMES_PER_IMAGE  # Hook 佔的 frames

    for i, scene in enumerate(scenes):
        starts[i] = cursor / FPS * 1000  # frame → ms

        cursor += scene["durationInFrames"]

        # Staging 邏輯：clip → hold → wipe(overlap) → staging → fade(overlap) → next
        if scene["type"] == "clip" and scene.get("stagingImage"):
            cursor += HOLD_FRAMES
            cursor += STAGING_FRAMES
            cursor -= WIPE_FRAMES  # wipe overlap
            next_scene = scenes[i + 1] if i + 1 < len(scenes) else None
            if next_scene:
                cursor -= FADE_FRAMES  # fade overlap after staging

        # 一般轉場（非 staging）
        elif i + 1 < len(scenes):
            next_scene = scenes[i + 1]
            if _needs_fade_between(scene, next_scene):
                cursor -= FADE_FRAMES

    return starts

def _needs_fade_between(curr, next_scene):
    """同空間 clip → clip 無轉場，其餘 fade"""
    if curr["type"] == "clip" and next_scene["type"] == "clip":
        if curr.get("label") == next_scene.get("label"):
            return False
    return True
```

**常數同步注意**：這些常數在 Remotion（TypeScript）和 orchestrator（Python）兩端各有一份。Python 端加註解標明 source of truth 為 Remotion 端。若 Remotion 常數修改，需同步更新 Python 端。

轉換公式：`start_ms = start_frame / 30 * 1000`

### 音訊重組流程

```
原始音訊: [OPENING 0-2.1s][客廳 2.1-5.3s][主臥 5.3-8.0s][MAP ...][STATS ...][CTA ...]

場景時間軸: Hook 0-3s | 外觀 3-6.5s | 客廳 6.5-10s | 主臥 10-13.5s | ...

重組後:
[OPENING] + [silence] + [客廳] + [silence] + [主臥] + [silence] + ...
↑ 0s                   ↑ 6.5s              ↑ 10s
```

使用 `pydub`（Python library，底層呼叫 ffmpeg）：
1. 載入原始 mp3
2. 按每段的 `start_ms` / `end_ms` 切出 segments
3. 在 segments 之間插入 `AudioSegment.silent(duration=gap_ms)`
4. 匯出為 mp3
5. 同步調整字幕 `time_begin` / `time_end`（加上累積 offset）

### 字數控制（防超時）

Agent 端限制每段旁白字數，確保不超過場景時長：
- 1.2x 語速，約 4.8 字/秒
- Clip scene 3.5s → **最多 16 字**
- Map scene 10s → **最多 48 字**
- Stats scene 7s → **最多 33 字**
- CTA scene 5s → **最多 24 字**
- Opening（Hook 3s + 外觀 3.5s = 6.5s）→ **最多 31 字**

若某段音訊仍超過場景時長，log warning 但不截斷（容許少量溢出到轉場期間）。

## 改動範圍

### 新增

- **`orchestrator/services/audio_align.py`** — 音訊對齊核心邏輯
  - `split_subtitles_by_sections(narration_text, subtitles)` — 按 section marker 將字幕分組
  - `calc_scene_start_times(scenes, hook_image_count)` — 計算每個場景起始 ms
  - `align_narration(audio_bytes, subtitles, sections, scene_starts)` — 重組音訊 + 調整字幕

### 修改

- **`orchestrator/pipeline/jobs.py`**
  - 在 `_build_render_input()` 中，scenes 組裝完成後呼叫 `align_narration()`
  - 需從 state 中取得原始 `narration_text`（帶 markers）和 `narration_subtitles`
  - 需下載已上傳的 narration.mp3（從 `state.narration_url`）取得 audio bytes
  - 上傳重組後的音訊替換原本的 `narration_url`
  - 用調整後的字幕替換 `narration_subtitles`

- **`orchestrator/requirements.txt`** — 加入 `pydub`

- **`agent/SKILL.md`** — 更新每個 section 的字數上限

### 不改

- Remotion 端所有檔案
- MiniMax 呼叫方式（維持單次呼叫）
- input.json schema
- 場景時長常數

## 邊界情況

1. **無 narration** — 跳過對齊，行為不變
2. **Section marker 缺失** — 字幕無法分組，log warning，使用原始音訊
3. **某段音訊超過場景時長** — log warning，不截斷（允許少量溢出）
4. **某段無字幕**（例如 section 文字為空）— 該段插入完整靜音
5. **字幕文字比對失敗** — fallback 到原始音訊，不對齊
6. **OPENING 旁白超過 HookScene 時長** — 允許延續到外觀 clip scene（預期行為，hook + 外觀共享 OPENING 旁白時段）

## 測試策略

- Unit test: `split_subtitles_by_sections()` — 各種 marker 組合、缺失 marker、空 section
- Unit test: `calc_scene_start_times()` — 與 Remotion 端 `calcTotalFrames()` 交叉驗證
- Unit test: `align_narration()` — 用假音訊驗證靜音 padding 長度和字幕偏移
- 效能備註：pydub 在記憶體中操作整段音訊，目前旁白約 30-60 秒，無效能疑慮

## 前置條件

- Docker image 已包含 ffmpeg（`orchestrator/Dockerfile` 第 6 行），pydub 可直接使用

## 資料流

```
narration_text (帶 section markers)
  ↓ split by markers
sections: {"opening": "...", "客廳": "...", "map": "...", ...}
  ↓
MiniMax TTS (markers stripped)
  ↓ audio_bytes + subtitles[]
split_subtitles_by_sections(narration_text, subtitles)
  ↓ per-section subtitle groups
calc_scene_start_times(scenes, hook_image_count)
  ↓ per-scene start_ms
align_narration(audio_bytes, subtitles, sections, scene_starts)
  ↓ aligned_audio_bytes + aligned_subtitles
upload R2 → narration_url (replaced)
  ↓
Remotion renders with aligned audio + subtitles
```
