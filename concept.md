# ReelEstate - 技術概念整理

## 服務概述
全自動化 AI 短影音生成服務，專為台灣房仲設計。
輸入房屋資料+圖片，一鍵產出 TikTok/Reels/Shorts 短影音。

## 完整 Pipeline

```
房仲丟照片 + 空間標記 + 物件文字 + 建築外觀照（LINE）
       ↓
n8n：接收 LINE webhook → 驗證 signature → 照片下載/上傳 R2 → 轉發至 FastAPI
       ↓
┌─ FastAPI Orchestrator ─────────────────────────────┐
│                                                     │
│  ① 用戶管理                                         │
│     → 新用戶：觸發註冊流程（姓名/公司/電話/LINE ID） │
│     → 舊用戶：直接進入風格/旁白選擇                   │
│     → 配額檢查（Lua script 原子扣除）                 │
│                                                     │
│  ② 呼叫 Agent（sub-processor）                       │
│     → 傳入 raw_text + labeled photos + premium       │
│     → Agent 整理資訊、VLM 分析、寫講稿、規劃裝潢       │
│     → 回傳結構化 JSON                                 │
│                                                     │
│  📩 Gate 1：推講稿給房仲確認（LINE）                │
│     通過 → TTS 生成                                   │
│     修改 → 用戶輸入新講稿 → TTS 生成                  │
│     拒絕 → 跳過 TTS（純 BGM）                         │
│     Timeout 10 分鐘 → 自動通過                        │
│                                                     │
│  ③ Per-scene TTS：每段講稿各自呼叫 MiniMax             │
│     → silence padding 對齊 → 合併 narration.mp3       │
│     （失敗降級：TTS 失敗不中斷 pipeline）             │
│                                                     │
│  ④ 平行呼叫 WaveSpeed API：                           │
│     ├─ Kling V2.5 Turbo Pro（各空間）→ 影片片段        │
│     └─ nano-banana-2 → 虛擬裝潢圖（若 premium）        │
│                                                     │
│  ⑤ 素材到齊後：                                       │
│     → 組 input.json（固定 durationInFrames 常數）      │
│     → VPS Remotion render → 預覽影片                   │
│                                                     │
│  📩 Gate 2：推預覽影片給房仲確認（LINE）              │
│                                                     │
│  ⑥ 確認 OK → 送出最終 MP4                             │
│                                                     │
└─────────────────────────────────────────────────────┘
```

## 用戶管理（2026-03-21 上線）

### UserProfile（Redis Hash）
```
user:{line_user_id} → {
  name, company, phone, line_id,
  quota (int), usage (int), created_at
}
```

### 註冊流程
- 新用戶首次傳照片 → 觸發完整註冊（姓名→公司→電話→LINE ID）
- LINE ID 可跳過（Quick Reply 跳過按鈕）
- 「修改資料」指令可重新填寫

### 配額
- `try_consume_quota`：Lua script 原子扣除
- usage >= quota 時回傳 False（顯示額度不足訊息）

## 運鏡策略

### Kling 影片生成
- Model: `kwaivgi/kling-v2.5-turbo-pro/image-to-video`（$0.35/5s）
- 6 種 camera movement：Push In / Rotate / Truck Left / Truck Right / Pedestal Up / Drone Up
- 客廳/廚房：Pull Out；其餘室內：Pan；外觀：Drone Up
- guidance_scale: 0.8
- 播放速率：1.25x（5s 影片在 4s 內播完）

## 語音策略

### 講稿格式（Agent 輸出，帶 section marker + 停頓標記）
```
[OPENING]
信義區精裝兩房，<#0.5#>首次公開！

[客廳]
寬敞客廳採光充足，落地窗迎入自然光。

[主臥]
主臥獨立安靜，<#0.3#>空間大到可以放 king-size 床。

[STATS]
整屋35坪，兩房兩廳一衛，座落12樓，台北市信義區永吉路。

[CTA]
售價2,980萬，<#0.5#>歡迎來電洽詢王小明。
```

**停頓標記 `<#秒數#>`**：MiniMax 支援，短停頓 0.3-0.5s，長停頓 0.8-1.0s。

**字數公式**：`(空間數 × 16) + 134` 字（1.2x 語速 ≈ 4.8 字/秒）

### TTS 流程（Per-scene TTS）
```
Gate 1：房仲確認/修改/拒絕講稿（emoji 分段預覽）
     ↓ 通過 or 修改後
Split by [MARKER] → 每段 section 各自呼叫 MiniMax T2A (sync t2a_v2)
     → 計算各場景起始時間（mirror Remotion calcTotalFrames）
     → silence padding 對齊 + concat → narration.mp3 + aligned subtitles
     → 上傳 R2
     ↓ 失敗 → 降級（無旁白繼續）
Remotion render（BGM 有旁白時降音至 0.05 + SubtitleOverlay 字幕）
```

### 字幕
每段 section 的 MiniMax TTS 回傳 sentence-level 字幕（`time_begin` / `time_end` 毫秒），
`assemble_audio` 依場景起始時間 offset 後合併為完整字幕陣列。
Remotion `SubtitleOverlay` 根據時間戳顯示字幕，底部居中半透明黑底白字。

### 音訊設定
| 項目 | 值 |
|------|----|
| BGM 音量（無旁白） | 0.15 |
| BGM 音量（有旁白） | 0.05 |
| 旁白音量 | 1.0 |
| BGM URL | 環境變數 `BGM_URL` |

### 時長決定方式
各 scene 時長使用**固定常數**：

| 常數 | 值 | 時長 |
|------|---|------|
| OPENING_FRAMES | 450 | 15s |
| CLIP_FRAMES | 150 | 5s（實際播放 4s，1.25x 速率） |
| STATS_FRAMES | 210 | 7s |
| CTA_FRAMES | 150 | 5s |
| TRANSITION_FRAMES | 10 | 0.33s（fade） |

TTS 音訊獨立播放，不影響場景時長。

## 虛擬裝潢（WaveSpeed nano-banana-2/edit）

### 觸發條件
Premium 方案才有（`premium: True`，目前所有 job 預設開啟）。

### 裝潢 Reveal 規則
- 每個空間**只有最後一個 clip** 接裝潢圖
- 裝潢圖以 wipe 轉場顯示（WIPE_FRAMES = 28）
- 預設風格：`japanese_muji`（日式無印）

## 模型 / API 清單
| 模型 / API | 功能 | 狀態 |
|------------|------|------|
| `kwaivgi/kling-v2.5-turbo-pro/image-to-video` | 首尾幀 → 影片片段 | ✅ |
| `google/nano-banana-2/edit` | 虛擬裝潢 | ✅ |
| `wavespeed-ai/qwen-image/edit-multiple-angles` | 第二角度生成 | ✅ |
| MiniMax `speech-2.8-hd` | TTS（Chinese_casual_guide_vv2） | ✅ |
| Remotion | 剪輯 + 音訊 + 動畫 | ✅ |

### 已淘汰
| 模型 | 淘汰原因 |
|------|---------|
| Z-Image + Fun Control Net | 改用 nano-banana-2 |
| Wan 2.2 | 改用 Kling V2.5 Turbo Pro |
| Upscale (4x_NMKD-Siax) | Kling 品質已足夠 |
| RunPod qwen-image-edit-2511 | 改用 WaveSpeed |
| Kling V2.5 Turbo Std | 升級為 Turbo Pro |
| Qwen TTS (Worker C) | 改用 MiniMax T2A |
| Qwen3-ForcedAligner | 改用固定時長常數 |

## Opening 外觀展示（Premium only）

```
OpeningScene（Mapbox 地圖動畫 → crossfade → 外觀影片）
    → ClipScene × N（室內各空間影片）
```

- 外觀影片（`exteriorVideo`）由房仲上傳時標記 `exterior_photo`
- 缺失時跳過，Opening 直接接第一個室內空間

## Remotion 剪輯規劃

### 影片結構
```
HookScene（前 3 張 staging 快速硬切，各 1s）→ OpeningScene（Mapbox + exteriorVideo） → [fade] → ClipScene × N（含 Staging reveal）→ [fade] → StatsScene → [fade] → CTAScene
```

### 轉場邏輯
| 切換情境 | 效果 |
|----------|------|
| Hook 各圖之間 | 硬切（無轉場） |
| Hook → Opening | 硬切 |
| 同空間 clip → clip | 無轉場 |
| 不同空間之間 | fade |
| 最後一個 clip → Staging | wipe from-left |
| 其他 scene 切換 | fade |

### Remotion 架構
```
remotion/
├── src/
│   ├── Root.tsx
│   ├── ReelEstateVideo.tsx     ← 主 composition + 轉場 + 音訊（BGM + narration）+ 字幕
│   ├── types.ts               ← VideoInput（含 narrationSubtitles）
│   ├── components/
│   │   └── SubtitleOverlay.tsx ← 字幕 overlay
│   └── compositions/
│       ├── HookScene.tsx      ← 開場 hook（staging 快閃）
│       ├── OpeningScene.tsx
│       ├── ClipScene.tsx
│       ├── StagingScene.tsx
│       ├── StatsScene.tsx
│       ├── CTAScene.tsx
│       └── MapboxFlyIn.tsx
└── server/
    ├── index.ts                ← Express API
    ├── render-handler.ts
    ├── renderer.ts
    ├── assets.ts               ← 下載素材（含 narration）
    ├── types.ts
    └── uploader.ts
```

### input.json 格式
```json
{
  "title": "信義區精裝兩房",
  "location": "台北市信義區",
  "address": "台北市信義區永吉路 XX 號",
  "size": "35坪",
  "layout": "2房2廳1衛",
  "floor": "12F / 15F",
  "price": "2,980萬",
  "contact": "0912-345-678",
  "agentName": "王小明 | 信義房屋",
  "line": "wang_realestate",
  "exteriorVideo": "https://assets.replowapp.com/jobs/xxx/exterior.mp4",
  "bgm": "https://assets.replowapp.com/bgm.mp3",
  "narration": "https://assets.replowapp.com/jobs/xxx/narration.mp3",
  "narrationSubtitles": [
    {"text": "...", "time_begin": 0, "time_end": 5612.1}
  ],
  "scenes": [
    { "type": "opening", "durationInFrames": 450 },
    { "type": "clip", "src": "jobs/xxx/clips/客廳1.mp4", "label": "客廳", "durationInFrames": 150 },
    { "type": "clip", "src": "jobs/xxx/clips/客廳2.mp4", "label": "客廳", "durationInFrames": 150, "stagingImage": "jobs/xxx/images/客廳.jpg" },
    { "type": "clip", "src": "jobs/xxx/clips/主臥.mp4", "label": "主臥", "durationInFrames": 150, "stagingImage": "jobs/xxx/images/主臥.jpg" },
    { "type": "stats", "durationInFrames": 210 },
    { "type": "cta", "durationInFrames": 150 }
  ],
  "mapboxToken": "pk.xxx",
  "community": "信義之星",
  "propertyType": "電梯大樓",
  "buildingAge": "5年"
}
```

### 視覺風格
| 元素 | 選擇 |
|------|------|
| 字型 | Noto Sans TC |
| 色調 | 深色漸層，文字白色 |
| 動畫 | 文字由下滑入，淡出 |
| 轉場 | fade / wipe |
| 空間標籤 | 半透明毛玻璃，左下角 |
| 虛擬裝潢 badge | 金色（#FFD700），右上角 |
| 音訊 | TTS 旁白（1.0）+ BGM（0.05 有旁白 / 0.15 無旁白） |
| 字幕 | sentence-level，底部居中半透明黑底白字，fade in/out |

## 自動化架構

### 系統架構
```
LINE（房仲傳照片 + 空間標記 + 物件文字）
  ↓
n8n（接收 webhook，照片上傳 R2，路由到 FastAPI）
  ↓
FastAPI Orchestrator（主控，管理 job state + 呼叫所有服務）
  │
  ├─ 用戶管理（UserStore / Redis Hash）
  │    → 新用戶註冊、配額扣除
  │
  ├─ OpenClaw Agent（sub-processor，只做「思考」任務）
  │    → VLM 分析照片、生成講稿、規劃裝潢
  │    → 回傳結構化 JSON
  │
  ├─ Gate 1：講稿審核（LINE postback）
  │
  ├─ MiniMax T2A（TTS）
  │
  ├─ WaveSpeed API（平行）
  │    ├─ Kling V2.5 Turbo Pro
  │    └─ nano-banana-2
  │
  ├─ R2（素材暫存）
  │
  └─ VPS Remotion Render（POST /render → MP4）
  ↓
Gate 2：預覽確認（LINE Push API + postback）→ 最終 MP4 → LINE
```

### 人工審查節點
| Gate | 時機 | 內容 | 不通過處理 |
|------|------|------|-----------|
| Gate 1 | TTS 前 | 講稿文字 | 修改講稿 / 跳過旁白 / Timeout 自動通過 |
| Gate 2 | Render 後 | 預覽影片 | reject → 重新 render |

### 部署
- **FastAPI Orchestrator**：VPS `187.77.150.149`，`orchestrator-orchestrator-1`，port 8000
- **Remotion Render**：VPS `reelestate-remotion`，port 3100→3000
- **WaveSpeed / MiniMax / R2**：Orchestrator 直接呼叫

## 成本估算（每支影片）

| 項目 | 數量 | 單價 | 小計 |
|------|------|------|------|
| Kling V2.5 Turbo Pro 5s | 6 clips | $0.35 | **$2.10** |
| nano-banana-2 虛擬裝潢 | 4 張 | $0.07 | **$0.28** |
| qwen-image 多角度 | 2 張 | $0.025 | **$0.05** |
| MiniMax TTS（per-scene） | 5-8 次 | ~$0.01 | ~$0.05 |
| Remotion render（VPS） | 1 次 | ~$0 | ~$0 |
| **合計** | | | **~$2.48**（約 NT$77） |

## 商業規劃
| 項目 | 內容 |
|------|------|
| 每支成本 | ~$2.44（API 為主） |
| 商業模式 | 免費測試 → 月費（分方案）→ OEM (B2B) |
| 目標客戶 | 房仲加盟體系 |
| LINE 方案 | 目前 Free（200 則/月），需升輕用量（800元/月） |

## 已淘汰的 RunPod Workers
所有 AI 推論已遷移至 WaveSpeed API 和 MiniMax API：

- ~~Worker A（Qwen Edit）~~ → WaveSpeed `qwen-image/edit-multiple-angles`
- ~~Worker B（Wan 2.2）~~ → WaveSpeed Kling V2.5 Turbo Pro
- ~~Worker C（TTS + ForcedAligner）~~ → MiniMax T2A sync（含 subtitle），ForcedAligner 不再需要
- ~~Worker D（Z-Image + Upscale）~~ → WaveSpeed `nano-banana-2/edit`

## 目前進度
- ✅ FastAPI Orchestrator E2E 測試通過（2026-03-15）
- ✅ WaveSpeed Semaphore(3) 併發控制
- ✅ MiniMax T2A TTS（speech-2.8-hd）
- ✅ ClipScene 同空間標籤延續
- ✅ OpeningScene exteriorVideo crossfade（2026-03-19）
- ✅ Remotion 視覺微調（fade/wipe 時間分離、staging hold）（2026-03-19）
- ✅ 用戶管理（UserStore + 註冊流程 + 配額）（2026-03-21）
- ✅ 旁白審核門 Gate 1（講稿確認 postback）（2026-03-21）
- ✅ TTS 整合 + 失敗降級（2026-03-21）
- ✅ BGM + narration 注入 render input（2026-03-21）
- ✅ Remotion narration Audio track + BGM 動態音量（2026-03-21）
- ✅ agent/SKILL.md 更新停頓標記規則（2026-03-21）
- ✅ TTS 改用 sync endpoint + sentence-level 字幕（2026-03-25）
- ✅ SubtitleOverlay 繁體中文字幕顯示（2026-03-25）
- ✅ HookScene 開場 staging 快閃（前 3 張，各 1s 硬切）（2026-03-25）
- ✅ POI 間隔加長至 2 秒（2026-03-25）
- ✅ TTS retry 機制 + timeout 300s（2026-03-25）

## 待辦
- [ ] LINE 升輕用量方案（目前 Free 200 則/月易觸發 429）
- [ ] Agent POI inferred 模式不穩定（有時 pois: null）
- [ ] processing 狀態「重新開始」不取消背景 pipeline
- [ ] 真實資料 E2E 測試（含 TTS + BGM）
- [ ] 前端 UI（考慮中，可繞過 LINE push 限制）
