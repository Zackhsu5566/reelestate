# TTS Scene Alignment Design

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
1. 送 TTS 前，按 marker 拆分講稿，記錄每段文字（marker 本身被 MiniMax 忽略）
2. 拿到字幕後，逐句文字比對，將字幕分配到對應 section
3. 每個 section 的音訊範圍 = 第一句 `time_begin` ~ 最後一句 `time_end`

Scene mapping：

| Section Marker | 對應場景 | 起始時間 |
|---|---|---|
| `[OPENING]` | HookScene 開頭（frame 0） | 0ms |
| `[空間名]` | 對應的 ClipScene | 根據前面場景累計 |
| `[MAP]` | MapScene | 同上 |
| `[STATS]` | StatsScene | 同上 |
| `[CTA]` | CTAScene | 同上 |

### 場景起始時間計算

遍歷 scenes 陣列，累計每個場景的起始 frame，需考慮：
- HookScene: `hookImages.length * HOOK_FRAMES_PER_IMAGE`（30 frames/image）
- 每個 scene 的 `durationInFrames`
- Staging: `HOLD_FRAMES`（35）+ `STAGING_FRAMES`（90）- `WIPE_FRAMES`（28）overlap
- 轉場: `-FADE_FRAMES`（10）overlap

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
  - `_build_render_input()` 中呼叫 `align_narration()`
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
