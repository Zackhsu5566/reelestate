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
│  ① 呼叫 Agent（sub-processor）                       │
│     → 傳入 raw_text + labeled photos + premium       │
│     → Agent 整理資訊、VLM 分析、寫講稿、規劃裝潢       │
│     → 回傳結構化 JSON                                 │
│                                                     │
│  📩 Gate 1：推講稿給房仲確認（LINE）                │
│                                                     │
│  ② MiniMax T2A：TTS（整段講稿）→ narration.mp3           │
│                                                     │
│  📩 Gate 1.5：推音訊試聽（LINE）                    │
│     不通過 → 調整講稿或 TTS 參數 → 重跑 TTS            │
│                                                     │
│  ③ 平行呼叫 WaveSpeed API：                           │
│     ├─ Qwen Edit（需要的空間）→ 第二角度圖              │
│     │    └→ Kling（首尾幀）→ 影片片段                   │
│     ├─ Kling（原圖配對的空間）→ 影片片段                │
│     ├─ nano-banana-2 → 虛擬裝潢圖（若 premium）        │
│                                                     │
│  ④ 素材到齊後：                                       │
│     → 組 input.json（固定 durationInFrames 常數）      │
│     → VPS Remotion render → 預覽影片                   │
│                                                     │
│  📩 Gate 2：推預覽影片給房仲確認（LINE）              │
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
| 小空間（陽台/廁所/浴室等） | 同樣使用 Kling 首尾幀影片 | 統一品質 |

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

## 語音策略

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

### TTS 流程
```
整段講稿 → MiniMax T2A → narration.mp3
                           ↓
              📩 Gate 1.5：房仲試聽
                           ↓ OK
              繼續素材生成 pipeline
```

### 時長決定方式
各 scene 時長使用**固定常數**，不再依賴語音對齊：

| 常數 | 值 | 時長 |
|------|---|------|
| OPENING_FRAMES | 300 | 10s |
| CLIP_FRAMES | 150 | 5s（每個房間） |
| STATS_FRAMES | 210 | 7s |
| CTA_FRAMES | 90 | 3s |
| TRANSITION_FRAMES | 15 | 0.5s（fade） |

影片總長 = Opening + (Clip × N) + Stats + CTA + 轉場。
TTS 音訊獨立播放，不影響場景時長。

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
- 裝潢圖以 wipe 轉場顯示（CLIP_FRAMES = 150 frames）
- 素材路徑：`public/images/<空間名稱>.jpg`

## 模型 / API 清單
| 模型 / API | 功能 | 部署方式 | 狀態 |
|------------|------|---------|------|
| `google/nano-banana-2/edit` | 虛擬裝潢 | **WaveSpeed API** | 已測試 ✅（品質極佳，~38s） |
| `wavespeed-ai/qwen-image/edit-multiple-angles` | 第二角度生成 | **WaveSpeed API** | 已測試 ✅（~9.4s） |
| `kwaivgi/kling-v2.5-turbo-pro/image-to-video` | 首尾幀 → 影片片段（無音訊） | **WaveSpeed API** | 已測試 ✅（品質佳，~95s） |
| MiniMax T2A (speech-02-hd) | 文字轉語音（Chinese_casual_guide_vv2） | **MiniMax API** | 已測試 ✅ |
| Qwen3-ForcedAligner | 語音文字對齊 → 字元級 timestamps | 已淘汰（改用 MiniMax T2A 內建對齊） | — |
| Remotion | 剪輯 + 字幕 + 動畫 | VPS | v2 完成 ✅ |

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
| Qwen3-ForcedAligner | 語音文字對齊 | 改用固定時長常數，不再需要語音對齊 |

## Opening 外觀展示（Premium only）

### 概念
Premium 方案在 Opening 地圖動畫結束後，crossfade 進入建築外觀影片，讓觀眾在進入室內空間前先看到建築外觀：

```
OpeningScene（Mapbox 地圖動畫 → crossfade → 外觀影片）
    → ClipScene × N（室內各空間影片）
```

- 外觀影片（`exteriorVideo`）由房仲上傳時標記 `exterior_photo`，直接透過 input.json 傳入
- 地圖動畫與文字 overlay 在 crossfade 時淡出
- 無額外標籤顯示

### Standard vs Premium

| | Standard | Premium |
|---|---|---|
| **Opening 地圖** | Mapbox only | Mapbox（同） |
| **外觀展示** | 無 | Mapbox 動畫結束後 crossfade 外觀影片 |
| **Render 時間影響** | 無差異 | 無差異 |
| **額外成本** | $0 | $0（外觀影片直接傳入，不需 AI 生成） |

### 技術實作
- **exteriorVideo**：房仲上傳時標記 `exterior_photo`，R2 URL 直接填入 OpeningScene
- **非關鍵任務**：`exteriorVideo` 缺失時跳過，Opening 直接接第一個室內空間

### 時序
```
step_generate 平行執行：
├─ _task_clip_direct × N    (~95s each, semaphore 限 3 併發)
└─ _task_staging × N        (~38s each, non-critical)
（外觀影片已由 n8n 上傳至 R2，無需額外 AI 生成步驟）
```

## Remotion 剪輯規劃

### 影片結構
```
OpeningScene（Mapbox 地圖動畫 → crossfade 外觀照, premium）→ [fade] → ClipScene × N（含 Staging reveal）→ [fade] → StatsScene → [fade] → CTAScene
```

各 scene 時長使用固定常數（見「時長決定方式」）。

### 轉場邏輯
| 切換情境 | 效果 |
|----------|------|
| 同空間 clip → clip | 無轉場（直接接，標籤延續不重新 fade in） |
| 不同空間之間 | fade (0.5s) |
| 最後一個 clip → Staging | wipe from-left (0.5s) |
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
    ├── OpeningScene.tsx    ← 標題 + 地址 + 外觀影片（premium exteriorVideo）
    ├── ClipScene.tsx       ← 影片片段 + 空間標籤（同空間延續，空 label 不顯示）
    ├── StagingScene.tsx    ← 虛擬裝潢靜態圖 + 「虛擬裝潢」badge
    ├── StatsScene.tsx      ← 物件資訊卡
    ├── CTAScene.tsx        ← 價格 + 聯絡方式
    └── MapboxFlyIn.tsx     ← Mapbox 地圖動畫元件
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
  "exteriorVideo": "https://r2.example.com/exterior.mp4",
  "scenes": [
    { "type": "opening", "durationInFrames": 300 },
    { "type": "clip", "src": "clips/客廳1.mp4", "label": "客廳", "durationInFrames": 150 },
    { "type": "clip", "src": "clips/客廳2.mp4", "label": "客廳", "durationInFrames": 150, "stagingImage": "images/客廳.jpg" },
    { "type": "clip", "src": "clips/陽台.mp4", "label": "陽台", "durationInFrames": 150 },
    { "type": "clip", "src": "clips/主臥.mp4", "label": "主臥", "durationInFrames": 150, "stagingImage": "images/主臥.jpg" },
    { "type": "stats", "durationInFrames": 140 },
    { "type": "cta", "durationInFrames": 90 }
  ],
  "narration": "audio/narration.mp3",
  "bgm": "audio/bgm.mp3",
  "mapboxToken": "pk.xxx",
  "community": "信義之星",
  "propertyType": "電梯大樓",
  "buildingAge": "5年"
}
```

> `exteriorVideo` 只有 premium 方案才會出現（R2 URL，由 n8n 在接收 webhook 時上傳並傳入）。
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
| 音訊 | TTS 語音 + 低音量背景音樂 |

## 自動化架構

### 系統架構
```
LINE（房仲傳照片 + 空間標記 + 物件文字）
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
  ├─ R2（素材暫存，步驟間傳遞）
  │
  └─ VPS Remotion Render（POST /render → MP4）
  ↓
Gate 審查（LINE Push API + 等 postback）→ 最終 MP4 → LINE
```

**架構決策**：
- FastAPI + Redis 管理 job state，Agent 只負責分析規劃
- Agent 接收 raw_text + labeled photos + premium flag，一次呼叫完成所有思考任務
- 所有外部 API 呼叫、輪詢、素材上傳由 Orchestrator 負責
- 影片生成（Kling）和虛擬裝潢改用 WaveSpeed API，省去自建 Worker 維護

### 人工審查節點（三關）
| Gate | 時機 | 內容 | 不通過處理 | 實作 |
|------|------|------|-----------|------|
| Gate 1 | TTS 前 | 講稿文字 | 修改講稿 | LINE Push API + 等 postback |
| Gate 1.5 | TTS 後、素材生成前 | 語音試聽（語氣/斷句/發音） | 調整講稿或 TTS 參數，重跑 TTS（成本低） | LINE Push API + 等 postback |
| Gate 2 | 最終 render 前 | 預覽影片 | 調整後重新 render | LINE Push API + 等 postback |

### 拍攝規格
| 空間 | 張數 | 理由 |
|------|------|------|
| 客廳（大空間） | 2-3 張不同角度 | 直接配對給 Kling API |
| 其他房間 | 1 張 | Qwen Edit 生第二角度 |

### 部署
- **FastAPI Orchestrator**：待決定部署位置
- **WaveSpeed API**：Orchestrator 直接呼叫（Kling Pro / nano-banana-2 / qwen-multiple-angles）
- **MiniMax API**：TTS（speech-02-hd，同步 HTTP 呼叫）
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
| Remotion render（VPS） | 1 次 | ~$0 | ~$0 |
| **合計** | | | **~$2.43**（約 NT$76） |

### Premium 方案（額外成本）
| 項目 | 數量 | 單價 | 小計 |
|------|------|------|------|
| 外觀影片（外觀照直接傳入，無需 AI 生成） | — | $0 | **$0** |
| **Premium 額外合計** | | | **+$0** |
| **Premium 總計** | | | **~$2.44**（約 NT$76，與 Standard 相同） |

> - 所有空間統一使用 Kling 影片
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

## 已淘汰的 RunPod Workers
所有 AI 推論已遷移至 WaveSpeed API 和 MiniMax API，不再使用 RunPod：

- ~~Worker A（Qwen Edit）~~→ 改用 WaveSpeed `wavespeed-ai/qwen-image/edit-multiple-angles`
- ~~Worker B（Wan 2.2）~~→ 改用 WaveSpeed Kling V2.5 Turbo Pro
- ~~Worker C（TTS + ForcedAligner）~~→ TTS 改用 MiniMax T2A，ForcedAligner 不再需要
- ~~Worker D（Z-Image + Upscale）~~→ 裝潢改用 WaveSpeed `google/nano-banana-2/edit`

## 目前進度
- ✅ 已手動完成第一支影片（到 Wan 2.2 + Upscale 為止）
- ✅ Remotion v1 render 成功（9 個空間，56 秒）
- ✅ OpenClaw Agent skill 設計完成（`agent/SKILL.md`）
- ✅ Remotion v2：固定時長常數 + 轉場邏輯重寫
- ✅ Qwen3-ForcedAligner 驗證（字元級 timestamps，需後處理）
- ✅ ForcedAligner 後處理腳本（`scripts/process_alignment.py`）
- ✅ VPS Remotion render endpoint（2026-03-11 部署完成）
- ✅ ~~Worker C 部署完成~~ → 已淘汰，ForcedAligner 不再需要
- ✅ nano-banana-2 虛擬裝潢測試（品質優於 Z-Image）
- ✅ 架構調整：Worker A/B/D 全改用 WaveSpeed API
- ✅ `google/nano-banana-2/edit` 虛擬裝潢測試（品質極佳，~38s）
- ✅ `wavespeed-ai/qwen-image/edit-multiple-angles` 多角度測試（~9.4s）
- ✅ `kwaivgi/kling-v2.5-turbo-pro/image-to-video` 首尾幀測試（品質佳，~95s）
- ✅ FastAPI Orchestrator E2E 測試通過（2026-03-15）
- ✅ WaveSpeed Semaphore(3) 併發控制
- ✅ TTS 遷移至 MiniMax T2A（speech-02-hd, Chinese_casual_guide_vv2）（2026-03-15）
- ✅ ClipScene 同空間標籤延續 + 空 label 不顯示（2026-03-15）
- ✅ ~~KenBurnsScene / Ken Burns 動畫~~ → 已移除（2026-03-19）
- ✅ 重命名 zImage/ZImageScene → stagingImage/StagingScene（2026-03-15）
- ✅ 移除空拍轉場（Google 3D/CesiumJS/Kling/renderStill）→ 改為外觀影片 crossfade（2026-03-16）
- ✅ Pipeline 簡化設計規劃完成（2026-03-18）
- ✅ Pipeline 簡化初始實作（Orchestrator + Remotion 重構）（2026-03-18）
- ✅ 競爭市場分析完成（`competitive-analysis-2026-03.md`）（2026-03-18）
- ✅ RunPod Workers 全部淘汰、所有參照清理完成（2026-03-19）
- ✅ 系統架構文件重整至根目錄（`ARCHITECTURE.md`）（2026-03-19）
- ✅ Remotion 視覺微調：fade/wipe 時間分離、staging hold、版面修正（2026-03-19）
- ✅ 移除 KenBurnsScene、CaptionsOverlay（改用固定時長常數）（2026-03-19）
- ✅ 移除 ForcedAligner 依賴（場景時長改用固定常數）（2026-03-19）

## 待辦優先順序

### 整合（當前階段）
1. ~~FastAPI Orchestrator 實作~~ ✅（E2E 測試通過 2026-03-15）
2. ~~空拍轉場 pipeline~~ ✅ 已移除，改為外觀影片 crossfade（2026-03-16）
3. ~~Pipeline 簡化~~ ✅ 初始實作完成（2026-03-18）
4. VPS 部署 orchestrator + render server 更新（新增 MAPBOX_TOKEN 環境變數）
5. ~~OpeningScene 實作 exteriorVideo crossfade（premium）~~ ✅（2026-03-19）
6. 真實資料 E2E 測試
