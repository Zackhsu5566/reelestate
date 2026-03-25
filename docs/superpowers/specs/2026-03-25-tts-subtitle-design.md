# TTS Subtitle Design

## 背景

目前 TTS narration 只有音訊，沒有字幕。短影音平台上大部分用戶靜音觀看，字幕對觀看率影響大。

## 調查結果

- MiniMax **sync endpoint** (`t2a_v2`) 支援 `subtitle_enable: true`，回傳 sentence-level timestamps
- MiniMax **async endpoint** (`t2a_async_v2`) 不支援 subtitle
- Sync 限制 10,000 字，講稿約 150~300 字，完全夠用
- Subtitle 格式：JSON array，每句有 `text`、`time_begin`、`time_end`（毫秒）

```json
[
  {
    "text": "高雄市区精装套房，轻松置产首选！",
    "time_begin": 0,
    "time_end": 5612.1
  }
]
```

## 設計

### Backend（orchestrator）

1. **`minimax.py`** — `_synthesize_inner` 改用 sync `t2a_v2` endpoint
   - `synthesize()` 回傳 `tuple[bytes, list[dict]] | None`（audio + subtitles）
   - Sync endpoint 直接回傳 audio hex + subtitle URL，不需要 poll
   - 保留 retry 機制（1 retry）

2. **`jobs.py` / `state.py`** — 新增 subtitle 欄位
   - `JobState` 新增 `narration_subtitles: list[dict] | None`
   - `_task_tts` 拿到 subtitle 後存到 job state
   - Subtitle JSON 上傳 R2（`audio/{job_id}/subtitles.json`），URL 存到 `narration_subtitles_url`

3. **Render inputProps** — 傳 subtitle 給 Remotion
   - `narration_subtitles` 加入 render request

### Frontend（Remotion）

4. **`SubtitleOverlay` component**
   - 根據 subtitle timestamps 在對應時間顯示文字
   - 位置：底部居中
   - 樣式：半透明黑底 + 白字，Noto Sans TC
   - 淡入淡出動畫

5. **整合到影片**
   - 在 `ReelEstateVideo` 中，當有 `narration_subtitles` 時疊加 `SubtitleOverlay`
   - 字幕時間對齊 narration 音訊起始點

### 不做的事

- 不做 word-level 逐字動畫
- 不做字幕樣式客製化
- 不改 narration gate 流程（subtitle 在 TTS 生成時自動取得）

## 資料流

```
narration_text → MiniMax t2a_v2 (subtitle_enable=true)
  → audio hex → decode → upload R2 → narration_url
  → subtitle_file URL → fetch JSON → upload R2 → narration_subtitles_url
  → subtitle data → store in JobState → pass to Remotion inputProps
```
