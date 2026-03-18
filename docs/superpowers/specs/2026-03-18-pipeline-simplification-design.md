# Pipeline Simplification: 移除 TTS、Qwen Multi-Angle、降級 Kling

**日期**：2026-03-18
**狀態**：設計完成，待實作

---

## 目標

大幅簡化 ReelEstate pipeline，先專注把純影片做漂亮：

1. 移除 TTS（MiniMax T2A）+ ForcedAligner + 旁白字幕
2. 移除 Qwen Image Edit Multi-Angle
3. Kling 從 v2.5-turbo-pro（首尾幀模式）換成 v1.6-i2v-standard（單圖 + prompt）
4. 固定 Kling prompt（外觀 Drone Up / 室內 Rotate）
5. Staging 風格由客戶選模板，不由 Agent 決定

---

## 新 Pipeline 流程

### Before
```
analyzing → gate_script → tts → gate_audio → generating → rendering → gate_preview → delivering → done
```

### After
```
analyzing → generating → rendering → gate_preview → delivering → done
```

移除的狀態：`gate_script`、`tts`、`gate_audio`

### 步驟說明

| 步驟 | 內容 |
|------|------|
| **step_analyze** | Agent 分析 `raw_text` → 提取 PropertyInfo + 生成 title + 生成講稿（參考用）+ 整理空間名稱。分析完直接進入 `generating`（不觸發 Gate） |
| **step_generate** | 平行呼叫 Kling v1.6（所有空間 + 外觀）+ nano-banana-2 staging（premium） |
| **step_render** | 組裝 input.json → VPS Remotion render |
| **step_deliver** | 傳最終 MP4 |

### 移除的服務
- `services/minimax_tts.py` — 不再呼叫
- `services/worker_c.py` — 不再呼叫（ForcedAligner）
- `wavespeed.py` 中 Qwen Edit 相關方法 — 移除

---

## Kling v1.6-i2v-standard

### Model 切換
```python
# Before
MODEL_KLING = "kwaivgi/kling-v2.5-turbo-pro/image-to-video"
# After
MODEL_KLING = "kwaivgi/kling-v1.6-i2v-standard"
```

### API Payload
```python
{
    "image": image_url,        # 單圖輸入（移除 last_image）
    "duration": 5,
    "prompt": "...",           # 固定 prompt，見下方
    "guidance_scale": 0.3,     # 自然運鏡
}
```

### 固定 Prompt

| 空間類型 | Prompt |
|---------|--------|
| 外觀（`exteriorPhoto`） | `"Cinematic drone shot rising vertically high above the space, revealing more of the vast surroundings."` |
| 所有室內空間 | `"Slow horizontal camera pan from left to right across the room"` |

### 成本
- v1.6 Standard: **$0.25 / 5s**（v2.5 Pro 是 $0.35）

---

## 空間標記慣例

### 新慣例
| 標記 | 意義 | Kling 生成 | Render 時長 |
|------|------|-----------|------------|
| `X` | 正常空間 | 5s 影片 | 5s (150 frames) |
| `Xs` | 小空間 | 5s 影片（同上） | 3.5s (105 frames) |

### 移除
| 標記 | 原意義 | 移除原因 |
|------|--------|---------|
| ~~`Xk`~~ | Ken Burns 靜態圖 | 不再使用 Ken Burns |
| ~~`X.1`~~ | 配對第二張照片 | Kling v1.6 是單圖模式，不需配對 |

### 預處理（`main.py` `_preprocess_spaces()`）
- `s` 後綴 → `is_small_space=True`，label 去掉 `s`
- 每張照片獨立，同空間多張照片 = 多個獨立 clip

### 同空間多張照片的處理

**asset_tasks key 命名**：`clip:{space_name}:{photo_index}`
- 例：客廳有 2 張照片 → `clip:客廳:0`、`clip:客廳:1`

**step_generate**：遍歷每個空間的每張照片，各自呼叫一次 Kling v1.6。

**_build_render_input**：同空間多張照片按 index 順序組裝為多個 clip scene，全部 `label` 相同（觸發 Remotion 同空間無轉場邏輯）。最後一個 clip 若有 staging → 先做 ffmpeg 反轉再填入。

**範例**：客廳 2 張照片 + premium staging
```python
# asset_tasks
"clip:客廳:0" → output_url = "正播影片.mp4"
"clip:客廳:1" → output_url = "反轉影片.mp4"  # 最後一個，已 ffmpeg 反轉
"staging:客廳" → output_url = "staging.jpg"

# scenes 輸出
{"type": "clip", "src": "正播影片.mp4", "label": "客廳", "durationInFrames": 150},
{"type": "clip", "src": "反轉影片.mp4", "label": "客廳", "durationInFrames": 150, "stagingImage": "staging.jpg"},
```

---

## 反轉播放 + Staging 銜接

### 規則
- **有 staging 的空間**：同空間最後一個 clip 反轉播放（結尾回到原圖 → 無縫接 staging）
- **沒有 staging 的空間**：正常正播

### 同空間多張照片範例（premium，有 staging）
```
客廳 clip 1（正播 5s）→ 無轉場 → 客廳 clip 2（反轉 5s）→ wipe → 客廳 staging（2s）→ fade → 下一空間
```

### 無 staging 範例
```
主臥 clip 1（正播 5s）→ fade → 下一空間
```

### Remotion 實作
- `ClipSceneInput` 新增 `reverse?: boolean`
- **反轉方式**：Remotion `<OffthreadVideo>` 不支援 `playbackRate` 負值。因此反轉在 **render server 端用 ffmpeg** 處理：
  - `step_generate` 中 Kling 生成影片後，若該 clip 需要反轉（同空間最後一個且有 staging），orchestrator 下載影片 → `ffmpeg -i input.mp4 -vf reverse output.mp4` → 上傳 R2
  - 反轉後的影片 URL 填入 scene 的 `src`，Remotion 正常正播即可
  - 不需要 Remotion 端的 `reverse` prop（移除）
- **替代方案**：也可以在 render server 的 `downloadAssets` 階段用 ffmpeg 反轉。但在 orchestrator 端做更乾淨，因為可以與 Kling 任務串接

### 反轉實作位置：Orchestrator
- 新增 helper function `_reverse_video(video_url: str) -> str`
  - 下載影片到暫存檔
  - `ffmpeg -i input.mp4 -vf reverse -an output.mp4`（`-an` 丟棄音訊流，避免無音訊時報錯）
  - 上傳 R2，回傳新 URL
- 在 `_task_kling_video` 完成後，若需要反轉，串接 `_reverse_video`
- asset_tasks 不需要額外 key，反轉後的 URL 直接覆蓋 clip 的 output_url

---

## 固定時長

不再由 ForcedAligner 驅動，全部固定：

| Scene | Frames | 秒數 |
|-------|--------|------|
| Opening（Mapbox + 外觀影片） | 300 | 10s |
| Clip（正常空間） | 150 | 5s |
| Clip（小空間 `s`） | 105 | 3.5s |
| Staging | 60 | 2s |
| Stats | 140 | ~4.7s |
| CTA | 90 | 3s |
| Transition (fade/wipe) | 15 | 0.5s |

---

## Opening Scene：Mapbox + 外觀 Kling 影片

### 流程
```
exteriorPhoto（R2 URL）→ Kling v1.6 "Drone Up" → 5s 外觀影片
    ↓
OpeningScene: Mapbox 飛入 ~5s → crossfade → 外觀影片 ~5s
```

### 處理邏輯
- `_task_exterior_video()` 與其他空間 Kling 任務平行執行
- **非關鍵任務**：失敗時 Opening 只顯示 Mapbox 動畫
- asset_tasks key：`"clip:exterior"`

### 觸發條件
- 有 `exterior_photo` 就生成 Kling 外觀影片（**不分 Standard/Premium**）
- Standard 客戶如果提供了外觀照片，也會生成（額外 +$0.25）
- 沒有 `exterior_photo` → 跳過 `_task_exterior_video`，Opening 純 Mapbox 10s

---

## Staging 模板

### 客戶選擇
整個 job 統一一種風格，透過 `CreateJobRequest.staging_template` 傳入。

### 5 種預設模板

| Key | 名稱 | Prompt |
|-----|------|--------|
| `japanese_muji` | 日式無印風 | `Transform the interior into a Japanese Muji / Japandi style. Keep the original architecture unchanged, preserve all walls, windows, and layout. Use light wood materials, neutral color palette (beige, white, light brown), minimal furniture, clean lines. Add low-profile furniture, wooden textures, soft fabric, linen, and subtle decoration. Emphasize simplicity, calm atmosphere, and natural harmony. Soft natural lighting, airy space, uncluttered, zen feeling. Interior photography, highly realistic.` |
| `scandinavian` | 北歐風 | `Transform the interior into a Scandinavian style. Keep the original structure unchanged. Use white and light gray base, light wood flooring, simple modern furniture. Add cozy elements like fabric sofa, soft rug, warm lighting, indoor plants. Clean, functional, and bright atmosphere. Balanced minimalism with warmth. Interior photography, natural daylight, realistic materials.` |
| `modern_minimalist` | 現代簡約 | `Transform the interior into a modern minimalist style. Preserve the original layout completely. Use monochrome palette (white, gray, black), sleek furniture, clean surfaces. Reduce decoration, emphasize open space and geometry. Add subtle lighting accents and modern materials like glass and metal. High-end, clean, elegant atmosphere. Interior photography, sharp lines, realistic rendering.` |
| `modern_luxury` | 輕奢風 | `Transform the interior into a modern luxury style. Keep original structure unchanged. Use marble textures, gold accents, dark wood, and premium materials. Add elegant furniture, layered lighting, and refined decorations. Create a sophisticated, upscale atmosphere without clutter. Interior photography, high-end real estate style, realistic lighting.` |
| `warm_natural` | 自然溫馨風 | `Transform the interior into a warm natural style. Preserve all architectural elements. Use warm wood tones, soft fabrics, earthy colors (beige, brown, olive). Add cozy furniture, plants, and soft lighting. Comfortable, inviting, homey atmosphere. Interior photography, natural light, realistic.` |

### 套用邏輯
- Premium + `staging_template` 有值 → 所有空間統一套用對應 prompt
- Standard 或無 `staging_template` → 不生成 staging

### Staging prompt 注入點
- **Agent 不再生成 staging_prompt**。`SpaceInfo.staging_prompt` 欄位保留但由 orchestrator 填入。
- `step_generate` 中，orchestrator 根據 `state.staging_template` 查 `STAGING_TEMPLATES` 字典取得 prompt，再對每個空間呼叫 `_task_staging(state, space_name, photo_url, prompt)`。
- `SpaceInfo.needs_staging` 也不再由 Agent 決定：orchestrator 根據 `premium=True` + `staging_template` 有值 → 對所有空間生成 staging。

---

## Gate 簡化

### Before（3 關）
1. Gate 1：講稿文字確認
2. Gate 1.5：語音試聽
3. Gate 2：預覽影片確認

### After（1 關）
1. **Gate 2（preview）**：預覽影片確認 — 唯一保留的審查節點

---

## Agent SKILL.md 精簡

### 保留的職責
1. 從 `raw_text` 提取 PropertyInfo（地址、價格、坪數、格局、電話、姓名等）
2. 生成 5-8 字標題
3. 生成帶 section markers 的講稿（僅參考用）
4. 整理空間名稱（去除 `s` 後綴等）

### 移除的職責
- VLM 照片分析
- Qwen 旋轉角度決策
- 裝潢風格規劃 + staging_prompt 生成
- style_direction（風格方向）
- use_ken_burns 判斷
- estimated_video_duration_sec

### Agent Input 簡化
不再傳送照片 URL（省 token），只傳 `raw_text` + 空間 label 清單 + `premium` flag。

### Agent Output
```python
class AgentResult(BaseModel):
    property: PropertyInfo
    title: str
    narration: str               # 參考用
    spaces: list[SpaceInfo]      # 簡化版
    meta: AgentMeta | None = None
```

---

## Orchestrator Models 變化

### JobStatus
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

### SpaceInput
```python
class SpaceInput(BaseModel):
    label: str
    photos: list[str]
    is_small_space: bool = False    # 取代 force_ken_burns
```

### SpaceInfo（Agent 輸出）
```python
class SpaceInfo(BaseModel):
    name: str
    original_label: str | None = None
    photo_count: int
    photos: list[str] = []
    needs_staging: bool = False
    staging_prompt: str | None = None
```

### JobState 移除欄位
- `audio_url`
- `sections`
- `captions`
- `total_duration_ms`
- `total_duration_frames`

### CreateJobRequest 新增
```python
staging_template: str | None = None   # 客戶選的裝潢風格模板 key
```

---

## Remotion 端改動

### 移除的組件
- `KenBurnsScene.tsx`
- `CaptionsOverlay.tsx`
- `LocationScene.tsx`

### types.ts 變化
```typescript
// 移除
KenBurnsSceneInput
LocationSceneInput

// VideoInput 移除
narration: string
captions: Caption[]

// OpeningSceneInput 重命名
exteriorPhoto → exteriorVideo   // 現在是 Kling 影片 URL

// SceneInput 簡化
type SceneInput = OpeningSceneInput | ClipSceneInput | StatsSceneInput | CTASceneInput;
```

### ReelEstateVideo.tsx
- 移除 Audio（narration）
- 移除 CaptionsOverlay
- 移除 `ken_burns` / `location` case
- 保留 BGM

### ClipScene.tsx
- 不需改動（反轉由 orchestrator ffmpeg 處理，Remotion 正常正播）

### OpeningScene.tsx
- `exteriorPhoto` 靜態圖 → `exteriorVideo` Kling 影片播放

### StagingScene.tsx
- 保留不動

---

## Standard vs Premium

| | Standard | Premium |
|---|---|---|
| Opening | Mapbox only（無外觀照）/ Mapbox + 外觀 Kling Drone Up（有外觀照） | 同左 |
| Staging | 無 | 有（客戶選模板） |
| 反轉播放 | 無 | 有 staging 的空間反轉 |

> 外觀 Kling 影片的觸發條件是 `exterior_photo` 有值，**不分方案**。

---

## 成本估算

### Standard（~6 個空間，有外觀照）
| 項目 | 數量 | 單價 | 小計 |
|------|------|------|------|
| Kling v1.6 Std 5s | ~7 clips（含外觀） | $0.25 | **$1.75** |
| **合計** | | | **~$1.75** |

> 無外觀照時少 1 clip = **~$1.50**

### Premium（~6 個空間 + 外觀 + staging）
| 項目 | 數量 | 單價 | 小計 |
|------|------|------|------|
| Kling v1.6 Std 5s | ~7 clips（含外觀） | $0.25 | **$1.75** |
| Staging (nano-banana-2) | ~6 張 | $0.07 | **$0.42** |
| **合計** | | | **~$2.17** |

### Before vs After
| 方案 | Before | After | 省下 |
|------|--------|-------|------|
| Standard（有外觀） | ~$2.17 | ~$1.75 | -$0.42 (-19%) |
| Premium | ~$2.45 | ~$2.17 | -$0.28 (-11%) |

---

## Orchestrator 檔案改動清單

| 檔案 | 改動類型 |
|------|---------|
| `models.py` | 修改：JobStatus、SpaceInput、SpaceInfo、JobState、CreateJobRequest |
| `main.py` | 修改：`_preprocess_spaces()` 改 `s` 後綴處理 |
| `pipeline/jobs.py` | 大改：移除 step_tts、_task_align、_task_angle_then_clip、_task_clip_direct。新增 _task_kling_video、_task_exterior_video、_reverse_video（ffmpeg 反轉）。改寫 pipeline_runner、step_generate、_build_render_input |
| `pipeline/gates.py` | 修改：只保留 preview gate |
| `services/wavespeed.py` | 修改：換 model、移除 Qwen、改 Kling 簽名 |
| `services/minimax_tts.py` | 保留檔案，移除 import/呼叫 |
| `services/worker_c.py` | 保留檔案，移除 import/呼叫 |
| `services/agent.py` | 修改：簡化 input |
| `agent/SKILL.md` | 大改：精簡職責 |
| `config.py` | 修改：可移除 minimax/worker_c 設定 |
| `telegram/bot.py` | 修改：移除 send_gate_script、send_gate_audio |

## Remotion 檔案改動清單

| 檔案 | 改動類型 |
|------|---------|
| `types.ts` | 修改：移除類型、重命名 exteriorVideo |
| `ReelEstateVideo.tsx` | 大改：移除 ken_burns/location/narration/captions |
| `ClipScene.tsx` | 不需改動 |
| `StagingScene.tsx` | 保留不動 |
| `OpeningScene.tsx` | 修改：exteriorVideo 影片播放 |
| `KenBurnsScene.tsx` | 刪除或保留不用 |
| `CaptionsOverlay.tsx` | 刪除或保留不用 |
| `LocationScene.tsx` | 刪除或保留不用 |
