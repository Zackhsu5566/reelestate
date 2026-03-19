---
name: add-worker
description: 新增 AI Worker 服務到 ReelEstate pipeline
---

## Worker 架構

| Worker | 用途 | 平台 |
|--------|------|------|
| WaveSpeed | 虛擬裝潢、多角度生成、首尾幀影片 | WaveSpeed API |
| MiniMax T2A | TTS | MiniMax API |

## 新增 Worker 步驟

### 如果是新的 WaveSpeed model

使用 `add-wavespeed-model` skill。

### 如果是新的外部服務

1. **建立 service wrapper** `orchestrator/services/<worker_name>.py`

   參考 `orchestrator/services/wavespeed.py` 的結構：
   - `start()` / `close()` 管理 httpx client
   - `submit()` 回傳 job_id
   - `poll()` 輪詢直到完成，回傳 output URL
   - High-level method（組合 submit + poll）

2. **新增 config** `orchestrator/config.py`：
   - API endpoint URL
   - API token（從環境變數讀取）
   - poll timeout / interval

3. **更新 `models.py`**：新增對應的 `AssetTask` 欄位（如需追蹤狀態）

4. **更新 pipeline** `orchestrator/pipeline/jobs.py`：
   - 在適當的 pipeline stage 加入 worker 呼叫
   - 使用 `asset_tasks` dict 追蹤 crash recovery 狀態

5. **更新 `JobStatus` enum**（如需新的 pipeline stage）：
   在 `models.py` 的 `JobStatus` 中新增 status 值

6. **記憶體更新**：把新 worker 的 endpoint、token、用途加到 MEMORY.md

## 成本估算

每新增一個 AI 步驟，更新 MEMORY.md 中的「每支影片估算成本」。
