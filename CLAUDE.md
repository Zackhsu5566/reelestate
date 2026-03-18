# ReelEstate 專案指令

## 專案概述
全自動化 AI 短影音生成服務，專為台灣房仲設計。詳見 `concept.md`。

## Remotion 範本（`remotion/` 目錄）

寫任何 Remotion 程式碼前，**必須先讀取** `remotion-video-toolkit` 相關規則（路徑：`C:\Users\being\skills\remotion-video-toolkit\rules\`）。

### 影片規格
- 尺寸：1080 × 1920（9:16）
- FPS：30
- 格式：MP4

### 時間配置（常數）
```
OPENING_FRAMES  = 10s = 300 frames（含 POI 生活機能）
CLIP_FRAMES     =  5s = 150 frames（每個房間）
STATS_FRAMES    = ~4.7s = 140 frames
CTA_FRAMES      =  3s = 90 frames
TRANSITION_FRAMES = 15 frames（0.5s fade）
```

### 場景結構
```
OpeningScene (含 POI) → [fade] → ClipScene × N → [fade] → StatsScene → [fade] → CTAScene
```

### 視覺風格
- 字型：Noto Sans TC（`@remotion/google-fonts/NotoSansTC`）
- 背景：深色漸層（`#0a0a0a` → `#1a1a2e`）
- 文字：白色，動畫由下滑入（interpolate Y + opacity）
- 字幕：TikTok 風格，底部顯示，當前詞高亮 `#FFD700`
- 轉場：`fade` from `@remotion/transitions`

### 素材放置位置
```
remotion/public/
├── clips/      ← Kling V2.5 輸出的 .mp4
├── images/     ← nano-banana-2 虛擬裝潢靜態圖（.jpg）
└── audio/      ← narration.mp3, bgm.mp3
```

> 完整設計文件與 input.json 格式見 `concept.md`

## Skills（`.claude/skills/`）

| Skill | 觸發條件 |
|-------|---------|
| `pr` | 建立 commit / PR |
| `render-report` | 影片 render 失敗、要偵錯 render 問題 |
| `add-composition` | 新增 Remotion scene |
| `add-worker` | 新增 AI worker 服務 |
| `pipeline-test` | E2E pipeline 測試 |
| `add-wavespeed-model` | 新增 WaveSpeed model |
| `add-api-field` | 新增 orchestrator API 欄位 |
| `deploy-update` | 部署更新到 VPS |
| `debug-job` | 偵錯失敗的 pipeline job |

使用前讀取對應 skill 檔案：`.claude/skills/<name>/SKILL.md`
