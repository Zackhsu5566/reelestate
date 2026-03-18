# ReelEstate - 技術概念整理

## 服務概述
全自動化 AI 短影音生成服務，專為台灣房仲設計。
輸入房屋資料+圖片，一鍵產出 TikTok/Reels/Shorts 短影音。

## 完整 Pipeline

```
房仲丟照片 + 空間標記 + 物件文字 + 建築外觀照（Telegram）
       ↓
n8n：接收 webhook → 依標記分組照片 → 上傳 R2 → POST /jobs
       ↓
┌─ FastAPI Orchestrator ─────────────────────────────┐
│                                                     │
│  ① 呼叫 Agent（sub-processor）                       │
│     → 傳入 raw_text + labeled photos + premium       │
│     → Agent 整理資訊、VLM 分析、寫講稿、規劃裝潢       │
│     → 回傳結構化 JSON                                 │
│                                                     │
│  📩 Gate 1：推講稿給房仲確認（Telegram）                │
│                                                     │
│  ② MiniMax T2A：TTS（整段講稿）→ narration.mp3           │
│                                                     │
│  📩 Gate 1.5：推音訊試聽（Telegram）                    │
│     不通過 → 調整講稿或 TTS 參數 → 重跑 TTS            │
│                                                     │
│  ③ 平行呼叫 WaveSpeed API + Render Server：           │
│     ├─ Qwen Edit（需要的空間）→ 第二角度圖              │
│     │    └→ Kling（首尾幀）→ 影片片段                   │
│     ├─ Kling（原圖配對的空間）→ 影片片段                │
│     ├─ nano-banana-2 → 虛擬裝潢圖（若 premium）        │
│                                                     │
│  ④ ForcedAligner 結果 + 素材到齊後：                   │
│     → 組 input.json（含各 scene durationInFrames）     │
│     → VPS Remotion render → 預覽影片                   │
│                                                     │
│  📩 Gate 2：推預覽影片給房仲確認（Telegram）              │
│                                                     │
│  ⑤ 確認 OK → 送出最終 MP4                             │
│                                                     │
└─────────────────────────────────────────────────────┘
```

## 運鏡模組策略

### 兩種素材情境
| 情境 | 做法 | 品質 |
|------|------|------|
| 同空間兩張照片（客廳） | 直接丟 Kling API | 最穩，最自然 |
| 只有一張照片（其他房間） | Qwen Edit 生第二角度 → Kling API | 可用，家具可能小變形 |
| 小空間（陽台/廁所/浴室等） | Ken Burns 靜態圖動畫（zoom + pan） | 省成本，效果自然 |

### Kling 首尾幀順序
- **首幀**：Qwen Edit 生成的角度（或第二張原圖）
- **尾幀**：原始照片
- 原因：影片結尾停在原圖，接 wipe 轉場顯示虛擬裝潢版本（nano-banana-2），形成 before/after 對比
- **API**：WaveSpeed `kwaivgi/kling-v2.5-turbo-pro/image-to-video`，start+end frame 模式，5s

### Qwen Image Edit 使用角度
API 用數值角度（非文字 prompt），由 Agent 呼叫 VLM 分析照片後決定方向：

```json
{
  "images": ["<image_url>"],
  "horizontal_angle": 45,   // 正值=右旋，負值=左旋；常用 ±35 或 ±45
  "vertical_angle": 0,
  "distance": 1,
  "output_format": "jpeg",
  "seed": -1
}
```

**角度選擇邏輯**：
- 以「能看見最多空間」為主要原則
- 右側是牆/櫃子 → 用負值（左旋）；左側封閉 → 用正值（右旋）
- 分析維度：哪側有更多開放空間、走道、房間延伸

不使用俯視角度（vertical_angle 保持 0）。

## 語音 + 字幕策略

### 講稿格式（Agent 輸出，帶 section marker）
```
[OPENING]
信義區精裝兩房，首次公開！

[客廳]
寬敞客廳採光充足，落地窗迎入自然光，
是全家人最愛的聚集地。

[主臥]
主臥獨立安靜，空間大到可以放 king-size 床
還有專屬更衣區。

[STATS]
整屋35坪，兩房兩廳一衛，座落12樓，
視野無遮擋，位於台北市信義區永吉路。

[CTA]
售價2,980萬，歡迎來電洽詢。
```

### TTS + ForcedAligner 流程
```
整段講稿 → MiniMax T2A → narration.mp3
                           ↓
              📩 Gate 1.5：房仲試聽
                           ↓ OK
        Qwen3-ForcedAligner（mp3 + 講稿原文）
                           ↓
              字元級 timestamps（簡體）
                           ↓
                        後處理：
              1. 用 index 對應回原始繁體字
              2. 去重（處理重複段）
              3. 依 section marker 位置切出各 scene 起訖秒數
              4. 分詞（jieba）→ 合併成詞級 timestamps
                           ↓
        ├→ 各 scene durationInFrames
        └→ captions 陣列（詞級，繁體）→ CaptionsOverlay
```

### ForcedAligner 注意事項
- 輸出為**簡體字元級**，需用原始講稿 index 對應回繁體
- 可能出現重複段，需去重處理
- 字幕顯示用**原始繁體文字**，ForcedAligner 只取時間戳

### 時長決定方式
影片總長 = TTS 音訊長度。各 scene 時長由 Agent 講稿長度決定：

| Scene | 時長來源 | 旁白內容 |
|-------|---------|---------|
| OpeningScene | ForcedAligner `[OPENING]` 區間 | 標題 hook |
| ClipScene × N | ForcedAligner 各空間區間 | 空間介紹 |
| KenBurnsScene × N | ForcedAligner 各空間區間 | 空間介紹（小空間） |
| StatsScene | ForcedAligner `[STATS]` 區間 | 物件資訊（坪數、格局等） |
| CTAScene | ForcedAligner `[CTA]` 區間 | 價格 + 聯絡方式 |

Agent 透過控制各段講稿長度，間接決定每個鏡頭的秒數。

## 虛擬裝潢（WaveSpeed nano-banana-2/edit）

### 觸發條件
由客戶選擇的方案決定（高階方案才有），非 Agent 自動判斷。

### Agent 裝潢規劃職責
- **全案統一風格方向**：色調、材質、氛圍（例：現代簡約、淺色木質調）
- **各空間獨立 prompt**，依空間功能設計：
  - 客廳：沙發、茶几、電視櫃、地毯
  - 主臥：床組、床頭燈、衣櫃
  - 廚房：中島、吊燈、餐具擺設
  - 浴室：乾濕分離、鏡櫃、植物點綴
- Agent 需具備室內設計規劃能力，確保風格一致但內容因空間而異
- **使用 WaveSpeed `google/nano-banana-2/edit`**，傳入原始照片 + 裝潢 prompt

### 裝潢 Reveal 規則
- 每個空間**只有最後一個 clip** 接裝潢圖
- 裝潢圖顯示時間包含在該空間的 ForcedAligner 區間內
- 素材路徑：`public/images/<空間名稱>.jpg`

## 模型 / API 清單
| 模型 / API | 功能 | 部署方式 | 狀態 |
|------------|------|---------|------|
| `google/nano-banana-2/edit` | 虛擬裝潢 | **WaveSpeed API** | 已測試 ✅（品質極佳，~38s） |
| `wavespeed-ai/qwen-image/edit-multiple-angles` | 第二角度生成 | **WaveSpeed API** | 已測試 ✅（~9.4s） |
| `kwaivgi/kling-v2.5-turbo-pro/image-to-video` | 首尾幀 → 影片片段（無音訊） | **WaveSpeed API** | 已測試 ✅（品質佳，~95s） |
| MiniMax T2A (speech-02-hd) | 文字轉語音（Chinese_casual_guide_vv2） | **MiniMax API** | 已測試 ✅ |
| Qwen3-ForcedAligner | 語音文字對齊 → 字元級 timestamps | RunPod Worker C | 已跑通（需後處理） ✅ |
| Remotion | 剪輯 + 字幕 + 動畫 | VPS | v2 開發中 |

### 已淘汰
| 模型 | 原功能 | 淘汰原因 |
|------|--------|---------|
| Z-Image + Fun Control Net | 虛擬裝潢 | 改用 WaveSpeed `google/nano-banana-2/edit` |
| Wan 2.2 | 首尾幀影片生成 | 改用 WaveSpeed Kling V2.5 Turbo Pro |
| Upscale (4x_NMKD-Siax) | 提升影片畫質 | Kling 輸出品質已足夠，暫不需要 |
| Gemini 2.5 Flash Image | 虛擬裝潢 | 改用 WaveSpeed `google/nano-banana-2/edit` |
| RunPod qwen-image-edit-2511 | 第二角度生成 | 改用 WaveSpeed `wavespeed-ai/qwen-image/edit-multiple-angles`，Worker A 退休 |
| Kling V2.5 Turbo Std | 首尾幀影片 | 升級為 WaveSpeed Kling V2.5 Turbo Pro |
| Qwen TTS (Worker C) | 文字轉語音（voice clone） | 改用 MiniMax T2A，預建語音免 voice clone |

## Opening 外觀展示（Premium only）

### 概念
Premium 方案在 Opening 地圖動畫結束後，crossfade 進入建築外觀靜態照片（Ken Burns 微動效），讓觀眾在進入室內空間前先看到建築外觀：

```
OpeningScene（Mapbox 地圖動畫 → crossfade → 外觀照片 Ken Burns）
    → ClipScene × N（室內各空間影片）
```

- 外觀照片（`exteriorPhoto`）由房仲上傳時標記 `exterior_photo`，直接透過 input.json 傳入
- 地圖動畫與文字 overlay 在 crossfade 時淡出
- 無額外標籤顯示

### Standard vs Premium

| | Standard | Premium |
|---|---|---|
| **Opening 地圖** | Mapbox only | Mapbox（同） |
| **外觀展示** | 無 | Mapbox 動畫結束後 crossfade 外觀靜態照（Ken Burns 微動效） |
| **Render 時間影響** | 無差異 | 無差異 |
| **額外成本** | $0 | $0（外觀照片直接傳入，不需 AI 生成） |

### 技術實作
- **exteriorPhoto**：房仲上傳時標記 `exterior_photo`，R2 URL 直接填入 OpeningScene
- **Ken Burns 動畫**：與 KenBurnsScene 相同，zoom + pan 微動效
- **非關鍵任務**：`exteriorPhoto` 缺失時跳過，Opening 直接接第一個室內空間

### 時序
```
step_generate 平行執行：
├─ _task_align              (~10s)
├─ _task_clip_direct × N    (~95s each, semaphore 限 3 併發)
└─ _task_staging × N        (~38s each, non-critical)
（外觀照片已由 n8n 上傳至 R2，無需額外 AI 生成步驟）
```

## Remotion 剪輯規劃

### 影片結構
```
OpeningScene（Mapbox 地圖動畫 → crossfade 外觀照 Ken Burns, premium）→ [fade] → ClipScene/KenBurnsScene × N（含 Staging reveal）→ [fade] → StatsScene → [fade] → CTAScene
```

影片總長由 TTS 音訊長度決定，各 scene 由 ForcedAligner 時間戳切分。

### 轉場邏輯
| 切換情境 | 效果 |
|----------|------|
| 同空間 clip → clip | 無轉場（直接接，標籤延續不重新 fade in） |
| 同空間 ken_burns → clip（或反向） | 無轉場（直接接，標籤延續） |
| 不同空間之間 | fade (0.5s) |
| 最後一個 clip/ken_burns → Staging | wipe from-left (0.5s) |
| StagingScene → 下一個空間 | fade (0.5s) |
| Opening → 第一個空間 | fade (0.5s) |
| Stats → CTA | fade (0.5s) |

### Remotion 架構
```
remotion/
├── Root.tsx
├── ReelEstateVideo.tsx     ← 主 composition + 轉場邏輯
├── types.ts
└── compositions/
    ├── OpeningScene.tsx    ← 標題 + 地址 + 外觀照片 Ken Burns（premium exteriorPhoto）
    ├── ClipScene.tsx       ← 影片片段 + 空間標籤（同空間延續，空 label 不顯示）
    ├── KenBurnsScene.tsx   ← 小空間靜態圖 Ken Burns 動畫 + 空間標籤
    ├── StagingScene.tsx    ← 虛擬裝潢靜態圖 + 「虛擬裝潢」badge
    ├── StatsScene.tsx      ← 物件資訊卡
    ├── CTAScene.tsx        ← 價格 + 聯絡方式
    └── CaptionsOverlay.tsx ← TikTok 風格字幕（逐字高亮）
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
  "exteriorPhoto": "https://r2.example.com/exterior.jpg",
  "scenes": [
    { "type": "opening", "durationInFrames": 219 },
    { "type": "clip", "src": "clips/客廳1.mp4", "label": "客廳", "durationInFrames": 152 },
    { "type": "clip", "src": "clips/客廳2.mp4", "label": "客廳", "durationInFrames": 152, "stagingImage": "images/客廳.jpg" },
    { "type": "ken_burns", "src": "images/陽台.jpg", "label": "陽台", "durationInFrames": 120 },
    { "type": "clip", "src": "clips/主臥.mp4", "label": "主臥", "durationInFrames": 192, "stagingImage": "images/主臥.jpg" },
    { "type": "stats", "durationInFrames": 165 },
    { "type": "cta", "durationInFrames": 96 }
  ],
  "narration": "audio/narration.mp3",
  "bgm": "audio/bgm.mp3",
  "captions": [
    { "text": "信義區", "startMs": 0, "endMs": 800 },
    { "text": "精裝", "startMs": 800, "endMs": 1200 },
    { "text": "兩房", "startMs": 1200, "endMs": 1800 }
  ],
  "mapboxToken": "pk.xxx",
  "community": "信義之星",
  "propertyType": "電梯大樓",
  "buildingAge": "5年"
}
```

> `exteriorPhoto` 只有 premium 方案才會出現（R2 URL，由 n8n 在接收 webhook 時上傳並傳入）。
> `mapboxToken` 由 orchestrator 從環境變數注入，不會出現在 log 中。

### 視覺風格
| 元素 | 選擇 |
|------|------|
| 字型 | Noto Sans TC |
| 色調 | 深色漸層疊層，文字白色 |
| 動畫 | 文字由下滑入，淡出 |
| 轉場 | fade / wipe |
| 空間標籤 | 半透明毛玻璃，左下角 |
| 虛擬裝潢 badge | 金色（#FFD700），右上角 |
| 字幕 | TikTok 風格，底部，當前詞高亮金色 |
| 音訊 | TTS 語音 + 低音量背景音樂 |

## 自動化架構

### 系統架構
```
Telegram（房仲傳照片 + 空間標記 + 物件文字）
  ↓
n8n（接收 webhook，依標記分組照片，上傳 R2，路由到 FastAPI）
  ↓
FastAPI Orchestrator（主控，管理 job state + 呼叫所有服務）
  │
  ├─ OpenClaw Agent（sub-processor，只做「思考」任務）
  │    → 接收 raw_text + labeled photos + premium flag
  │    → 整理物件資訊、VLM 分析照片、生成講稿、規劃裝潢
  │    → 回傳結構化 JSON，不直接操作任何外部服務
  │
  ├─ WaveSpeed API（Orchestrator 直接呼叫）
  │    ├─ `kwaivgi/kling-v2.5-turbo-pro/image-to-video`: 首尾幀 → 影片片段
  │    ├─ `google/nano-banana-2/edit`: 虛擬裝潢
  │    └─ `wavespeed-ai/qwen-image/edit-multiple-angles`: 第二角度生成
  │
  ├─ MiniMax T2A API（TTS，Chinese_casual_guide_vv2 預建語音）
  │
  ├─ RunPod Worker C（ForcedAligner + 後處理）
  │
  ├─ R2（素材暫存，步驟間傳遞）
  │
  └─ VPS Remotion Render（POST /render → MP4）
  ↓
Gate 審查（Telegram 推送 + 等回覆）→ 最終 MP4 → Telegram
```

**架構決策**：
- FastAPI + Redis 管理 job state，Agent 只負責分析規劃
- Agent 接收 raw_text + labeled photos + premium flag，一次呼叫完成所有思考任務
- 所有外部 API 呼叫、輪詢、素材上傳由 Orchestrator 負責
- 影片生成（Kling）和虛擬裝潢改用 WaveSpeed API，省去自建 Worker 維護

### 人工審查節點（三關）
| Gate | 時機 | 內容 | 不通過處理 | 實作 |
|------|------|------|-----------|------|
| Gate 1 | TTS 前 | 講稿文字 | 修改講稿 | Telegram 推送 + 等 callback |
| Gate 1.5 | TTS 後、素材生成前 | 語音試聽（語氣/斷句/發音） | 調整講稿或 TTS 參數，重跑 TTS（成本低） | Telegram 推送 + 等 callback |
| Gate 2 | 最終 render 前 | 預覽影片 | 調整後重新 render | Telegram 推送 + 等 callback |

### 拍攝規格
| 空間 | 張數 | 理由 |
|------|------|------|
| 客廳（大空間） | 2-3 張不同角度 | 直接配對給 Kling API |
| 其他房間 | 1 張 | Qwen Edit 生第二角度 |

### 部署
- **FastAPI Orchestrator**：待決定部署位置
- **WaveSpeed API**：Orchestrator 直接呼叫（Kling Pro / nano-banana-2 / qwen-multiple-angles）
- **MiniMax API**：TTS（speech-02-hd，同步 HTTP 呼叫）
- **RunPod Serverless**（非 Pod）：Worker C（ForcedAligner），用完即關
- **VPS**：Remotion render + 薄 API endpoint
- **R2**：步驟間傳遞檔案

## 成本估算（每支影片）

### Standard 方案
| 項目 | 數量 | 單價 | 小計 |
|------|------|------|------|
| Kling V2.5 Turbo Pro 首尾幀 5s（無音訊） | 6 clips | $0.35 | **$2.10** |
| 虛擬裝潢（`google/nano-banana-2/edit`） | 4 張 | $0.07 | **$0.28** |
| 多角度生成（`wavespeed-ai/qwen-image/edit-multiple-angles`） | 2 張 | $0.025 | **$0.05** |
| MiniMax T2A TTS | 1 次 | ~$0.01 | ~$0.01 |
| ForcedAligner（RunPod Worker C） | 1 次 | ~$0.01 | ~$0.01 |
| Remotion render（VPS） | 1 次 | ~$0 | ~$0 |
| **合計** | | | **~$2.44**（約 NT$76） |

### Premium 方案（額外成本）
| 項目 | 數量 | 單價 | 小計 |
|------|------|------|------|
| 外觀照片 Ken Burns（外觀照直接傳入，無需 AI 生成） | — | $0 | **$0** |
| **Premium 額外合計** | | | **+$0** |
| **Premium 總計** | | | **~$2.44**（約 NT$76，與 Standard 相同） |

> - Ken Burns 小空間省 $0.35/空間（不需 Kling 影片生成）
> - 影片生成（Kling Pro）佔成本 86%
> - 升級 Pro 版品質更好，但成本從 $1.53 → $2.44（↑ $0.91）
> - 未來若量大可考慮降回 Turbo Std（$0.21/5s）節省成本

## 商業規劃
| 項目 | 內容 |
|------|------|
| 每支成本 | ~$2.44（API 為主，Standard 與 Premium 相同） |
| 商業模式 | 免費測試 → 月費（分方案，高階含虛擬裝潢）→ OEM (B2B) |
| 目標客戶 | 房仲加盟體系 |
| 測試對象 | 身邊房仲朋友 |

## RunPod Worker 架構
只保留 Worker C（ForcedAligner），影片生成和虛擬裝潢改用 WaveSpeed API，TTS 改用 MiniMax T2A。

每個 Worker = Docker container，內含 ComfyUI（背景服務）+ handler.py。
ComfyUI 負責 GPU 推論，handler.py 串流程 + 後處理（純 CPU）。
部署方式：GitHub repo → RunPod GitHub Integration 自動 build + deploy。

```
reelestate-workers/               ← GitHub repo
├── worker-a-qwen-edit/            Worker A: 第二角度生成
│   ├── Dockerfile
│   ├── start.sh
│   ├── handler.py
│   └── workflows/
│       └── qwen_edit.json
│
└── worker-c-tts-aligner/          Worker C: 對齊 + 後處理（TTS 已遷移至 MiniMax T2A）
    ├── Dockerfile
    ├── start.sh
    ├── handler.py
    ├── process_alignment.py
    └── workflows/
        └── forced_aligner.json
```

### Worker 共用模式
- `start.sh`：啟動 ComfyUI 背景 → 等就緒 → 啟動 handler.py
- `handler.py`：接收 job → 下載素材 → 呼叫 ComfyUI API → 上傳結果到 R2 → 回傳 URL
- `Dockerfile`：繼承 ComfyUI base → 裝 custom nodes → 下載模型 → COPY handler + workflows
- 模型用 `huggingface-cli download` 在 build 時 bake 進 image
- VLM 分析由 Agent 自身 VLM 能力處理，不需要 Worker

### 各 Worker 模型與 Custom Nodes

**Worker A（Qwen Edit）**
- 模型：
  - `Comfy-Org/Qwen-Image_ComfyUI` → UNET(fp8), CLIP(qwen_2.5_vl_7b), VAE
  - `dx8152/Qwen-Edit-2509-Multiple-angles` → LoRA(镜头转换)
  - `lightx2v/Qwen-Image-Lightning` → LoRA(Lightning-8steps-V2.0)
- Custom Nodes：rgthree-comfy, comfyui-easy-use

**Worker C（ForcedAligner only）**
- 模型：全部由 custom nodes 自動下載
  - Whisper base, Qwen3-ASR 1.7B, Qwen3-ForcedAligner 0.6B
- Custom Nodes：comfyui-edgetts, ComfyUI-Qwen3-ASR
- 注：TTS 已遷移至 MiniMax T2A，Worker C 不再處理 TTS

### 已移除的 Workers
- ~~Worker B（Wan 2.2）~~→ 改用 **Kling V2.5 Turbo Std API**（品質更好，免維護）
- ~~Worker D（Z-Image + Upscale）~~→ 裝潢改用 **WaveSpeed `google/nano-banana-2/edit`**；Upscale 暫不需要（Kling 輸出品質已足夠）

## 目前進度
- ✅ 已手動完成第一支影片（到 Wan 2.2 + Upscale 為止）
- ✅ Remotion v1 render 成功（9 個空間，56 秒）
- ✅ OpenClaw Agent skill 設計完成（`agent/SKILL.md`）
- ✅ Remotion v2：音訊驅動時長 + 轉場邏輯重寫
- ✅ Qwen3-ForcedAligner 驗證（字元級 timestamps，需後處理）
- ✅ ForcedAligner 後處理腳本（`scripts/process_alignment.py`）
- ✅ VPS Remotion render endpoint（2026-03-11 部署完成）
- ✅ Worker C 部署完成（RunPod endpoint `391h73cn715crm`）
- ✅ nano-banana-2 虛擬裝潢測試（品質優於 Z-Image）
- ✅ 架構調整：Worker A/B/D 全改用 WaveSpeed API
- ✅ `google/nano-banana-2/edit` 虛擬裝潢測試（品質極佳，~38s）
- ✅ `wavespeed-ai/qwen-image/edit-multiple-angles` 多角度測試（~9.4s）
- ✅ `kwaivgi/kling-v2.5-turbo-pro/image-to-video` 首尾幀測試（品質佳，~95s）
- ✅ FastAPI Orchestrator E2E 測試通過（2026-03-15）
- ✅ WaveSpeed Semaphore(3) 併發控制
- ✅ TTS 遷移至 MiniMax T2A（speech-02-hd, Chinese_casual_guide_vv2）（2026-03-15）
- ✅ ClipScene 同空間標籤延續 + 空 label 不顯示（2026-03-15）
- ✅ KenBurnsScene 小空間靜態圖動畫（2026-03-15）
- ✅ 重命名 zImage/ZImageScene → stagingImage/StagingScene（2026-03-15）
- ✅ 移除空拍轉場（Google 3D/CesiumJS/Kling/renderStill）→ 改為外觀照片 Ken Burns crossfade（2026-03-16）

## 待辦優先順序

### 整合（當前階段）
1. ~~FastAPI Orchestrator 實作~~ ✅（E2E 測試通過 2026-03-15）
2. ~~空拍轉場 pipeline~~ ✅ 已移除，改為外觀照片 Ken Burns（2026-03-16）
3. VPS 部署 orchestrator + render server 更新（新增 MAPBOX_TOKEN 環境變數）
4. OpeningScene 實作 exteriorPhoto Ken Burns crossfade（premium）
5. 真實資料 E2E 測試
6. TTS 場景間停頓策略（延後處理）
