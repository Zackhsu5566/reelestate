# Per-Scene TTS Alignment Design

## 背景

原始設計（`2026-03-25-tts-scene-alignment-design.md`）使用單次 TTS 呼叫 + 字元位移拆分字幕。字元位移對 MiniMax 繁簡轉換、斷句差異過於脆弱，錯位風險高。

本設計改為 **per-scene TTS**：每個 section 獨立呼叫 MiniMax，字幕天然歸屬正確，零錯位風險。

## 設計決策

| 決策 | 結論 |
|------|------|
| 優先級 | 可靠性（不錯位） |
| TTS 策略 | Per-scene，每個 section 各自呼叫 |
| 場景時長 | 固定常數不變 |
| 防溢出 | Agent 端嚴格字數控制 |
| API 呼叫次數 | 5-8 次/job，可並行（既有 Semaphore(5)） |
| OPENING 範圍 | HookScene + 外觀 clip 共享一段旁白 |
| Remotion 改動 | 零 |

## 資料流

```
Agent 產出 narration_text（帶 section markers）
  ↓ split_by_markers()
sections: [
  {marker: "OPENING", text: "今天帶你來看..."},
  {marker: "客廳",    text: "一進門就是超大面..."},
  {marker: "主臥",    text: "主臥相當寬敞..."},
  {marker: "MAP",     text: "位置就在信義安和站..."},
  {marker: "STATS",   text: "整屋三十五坪..."},
  {marker: "CTA",     text: "售價兩千九百八十萬..."},
]
  ↓ 並行 TTS（asyncio.gather，每個 section 各一次）
per_section_results: [
  {marker, audio_bytes, subtitles, audio_duration_ms}
]
  ↓ calc_scene_start_times() — mirror Remotion 常數
scene_starts: {OPENING: 0ms, 客廳: 6500ms, 主臥: 10000ms, ...}
  ↓ assemble_audio() — 每段 pad 靜音 + 拼接
final_audio: 一條完整 narration.mp3
final_subtitles: [{text, time_begin, time_end}, ...]
  ↓ 上傳 R2，傳給 Remotion（現有流程不變）
```

## Section 拆分與 TTS 呼叫

```python
# 1. 拆分 narration_text
sections = split_by_markers(narration_text)
# → [{marker: "OPENING", text: "..."}, {marker: "客廳", text: "..."}, ...]

# 2. 並行呼叫 TTS（每個 section 各一次）
results = await asyncio.gather(*[
    minimax.synthesize(section["text"])
    for section in sections
])
# → [(audio_bytes, subtitles), ...]
```

**重點**：
- `minimax.synthesize()` 現有的繁簡轉換邏輯不需修改 — 傳入的已經是單段純文字
- 並行受既有 `Semaphore(5)` 控制
- 每段的 subtitles 時間戳從 0 開始，天然屬於該 section

## 場景起始時間計算

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

虛擬碼（mirror `calcTotalFrames` + 記錄每場景起始 frame）：

```python
def calc_scene_start_times(scenes, hook_image_count):
    """回傳 dict: scene_index → start_ms"""
    starts = {}
    cursor = hook_image_count * HOOK_FRAMES_PER_IMAGE

    for i, scene in enumerate(scenes):
        starts[i] = cursor / FPS * 1000

        cursor += scene["durationInFrames"]

        if scene["type"] == "clip" and scene.get("stagingImage"):
            cursor += HOLD_FRAMES
            cursor += STAGING_FRAMES
            cursor -= WIPE_FRAMES
            next_scene = scenes[i + 1] if i + 1 < len(scenes) else None
            if next_scene:
                cursor -= FADE_FRAMES

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

**常數同步注意**：Python 端加註解標明 source of truth 為 Remotion 端。若 Remotion 常數修改，需同步更新 Python 端。

## 音訊拼接邏輯

```python
def assemble_audio(section_results, scene_starts):
    """
    section_results: [{marker, audio_bytes, subtitles, audio_duration_ms}]
    scene_starts: {marker → start_ms}

    回傳: (final_audio_bytes, final_subtitles)
    """
    final_audio = AudioSegment.empty()
    final_subtitles = []

    for section in section_results:
        target_start_ms = scene_starts[section.marker]

        # 前面補靜音到 target 位置
        gap = target_start_ms - len(final_audio)
        if gap > 0:
            final_audio += AudioSegment.silent(duration=gap)

        # 加入 section audio
        final_audio += AudioSegment.from_mp3(section.audio_bytes)

        # 字幕加 offset
        for sub in section.subtitles:
            final_subtitles.append({
                "text": sub["text"],
                "time_begin": sub["time_begin"] + target_start_ms,
                "time_end": sub["time_end"] + target_start_ms,
            })

    return final_audio.export(format="mp3"), final_subtitles
```

**OPENING 特殊處理**：
- `target_start_ms = 0`
- 可用時長 = HookScene + 外觀 clip = `hook_image_count * HOOK_FRAMES_PER_IMAGE / FPS * 1000` + 第一個 clip 的 `durationInFrames / FPS * 1000`

**溢出處理**：
- 如果某段 audio > 場景可用時長 → log warning，不截斷（允許少量溢到轉場期間）
- 上游 Agent 靠字數限制確保 99% 不溢出

## Gate 預覽與編輯流程

### 預覽顯示

改 `send_gate_narration()` 為段落標題格式：

```
📝 AI 生成的旁白講稿

🎬 開場
今天帶你來看這間信義區的精裝兩房...

🏠 客廳
一進門就是超大面落地窗...

🛏️ 主臥
主臥相當寬敞...

🗺️ 周邊
位置就在信義安和站旁邊...

📊 規格
整屋三十五坪...

📞 聯繫
售價兩千九百八十萬...

[✅ 通過] [✏️ 修改講稿] [❌ 不要旁白]
```

Marker → Emoji 對照：

| Marker | 顯示 |
|--------|------|
| `[OPENING]` | 🎬 開場 |
| `[空間名]` | 🏠 空間名 |
| `[MAP]` | 🗺️ 周邊 |
| `[STATS]` | 📊 規格 |
| `[CTA]` | 📞 聯繫 |

### 編輯流程

1. 用戶按「✏️ 修改講稿」→ 進入 edit 模式
2. 用戶回傳整段文字（帶段落標題）
3. Pipeline parse 回 section markers，重新拆分
4. 全部 section 重跑 TTS（並行，幾秒完成）
5. 重新拼接 + 上傳

不做逐段重跑的智能 diff — 全部重跑也就多幾秒，複雜度不值得。

## 字數控制（防超時）

Agent 端限制每段旁白字數，確保不超過場景時長：
- 1.2x 語速，約 4.8 字/秒
- Clip scene 3.5s → **最多 16 字**
- Map scene 10s → **最多 48 字**
- Stats scene 7s → **最多 33 字**
- CTA scene 5s → **最多 24 字**
- Opening（Hook 3s + 外觀 3.5s = 6.5s）→ **最多 31 字**

## 改動範圍

### 新增

- **`orchestrator/services/audio_align.py`** — 核心對齊模組
  - `split_by_markers(narration_text)` — 按 section marker 拆分
  - `calc_scene_start_times(scenes, hook_image_count)` — mirror Remotion 常數
  - `assemble_audio(sections_results, scene_starts)` — pad + 拼接 audio + 調整字幕

### 修改

- **`orchestrator/pipeline/jobs.py`**
  - `_task_tts()` — 從單次 `minimax.synthesize()` 改成 per-section 並行呼叫 + `assemble_audio()`
- **`orchestrator/line/bot.py`**
  - `send_gate_narration()` — marker 轉 emoji 段落標題顯示
- **`orchestrator/requirements.txt`**
  - 加入 `pydub`
- **`agent/SKILL.md`**
  - 更新字數上限說明

### 不改

- Remotion 端所有檔案
- `orchestrator/services/minimax.py`（現有 synthesize 接收純文字，已夠用）
- input.json schema
- 場景時長常數

## 邊界情況

1. **無 narration** — 跳過，行為不變
2. **某段 TTS 失敗** — retry 一次，仍失敗則該段靜音，其餘正常
3. **某段 audio 超過場景時長** — log warning，不截斷（允許少量溢出到轉場期間）
4. **用戶編輯時缺少某段 marker** — 缺少的段落不產 TTS，該段靜音
5. **用戶編輯時新增未知 marker** — 忽略，log warning

## 測試策略

- Unit test: `split_by_markers()` — 各種 marker 組合、缺失 marker、空 section
- Unit test: `calc_scene_start_times()` — 與 Remotion 端 `calcTotalFrames()` 交叉驗證
- Unit test: `assemble_audio()` — 假 audio 驗證 padding 長度和字幕偏移
- Integration: 真實 MiniMax 跑一次完整流程驗證

## 前置條件

- Docker image 已包含 ffmpeg（`orchestrator/Dockerfile`），pydub 可直接使用
- MiniMax API 並發 semaphore 已設定（5）

## 與舊設計的差異

| | 舊設計（單次 TTS + char offset） | 本設計（per-scene TTS） |
|---|---|---|
| TTS 呼叫次數 | 1 次 | 5-8 次 |
| 字幕歸屬 | 字元位移，脆弱 | 天然正確 |
| 繁簡轉換影響 | 會破壞 char offset | 不影響 |
| 跨 section 斷句 | 需處理 | 不存在 |
| 語調連貫性 | 好 | 每段獨立，稍差 |
| Remotion 改動 | 零 | 零 |
| Gate 預覽 | 純文字 | 分段標題 |
