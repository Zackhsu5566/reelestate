---
name: add-wavespeed-model
description: 新增 WaveSpeed AI model 到 ReelEstate pipeline
---

新增 WaveSpeed model 前，先在 WaveSpeed 平台確認 model ID 與 payload 格式。

## WaveSpeed API 規格

- **Base URL**: `https://api.wavespeed.ai/api/v3/{model-path}`
- **認證**: `Authorization: Bearer <API_KEY>`
- **流程**: `POST` 送 job → 拿 `data.id` → 輪詢 `GET /api/v3/predictions/{id}/result`
- **結果**: `data.outputs[0]` = CloudFront URL

## 目前已整合 Models

| 用途 | Model ID | 估算時間 |
|------|---------|---------|
| 虛擬裝潢 | `google/nano-banana-2/edit` | ~38s |
| 多角度生成 | `wavespeed-ai/qwen-image/edit-multiple-angles` | ~9.4s |
| 首尾幀影片 | `kwaivgi/kling-v2.5-turbo-pro/image-to-video` | ~95s |

## 新增 Model 步驟

1. **新增 model constant** `orchestrator/services/wavespeed.py`：
   ```python
   MODEL_NEW = "vendor/model-name/task"
   ```

2. **新增 submit method**（如 payload 獨特）：
   ```python
   async def new_model_submit(self, ...) -> str:
       return await self.submit(MODEL_NEW, {...})
   ```

3. **新增 high-level method**（帶 crash recovery）：
   ```python
   async def new_model(self, ..., existing_id: str | None = None) -> str:
       if existing_id:
           return await self.poll(existing_id)
       pid = await self.new_model_submit(...)
       return await self.poll(pid)
   ```

4. **更新 pipeline** `orchestrator/pipeline/jobs.py`：
   - 在適當 stage 呼叫新 method
   - 將 prediction_id 存入 `asset_tasks` 供 crash recovery 使用

5. **測試**（先用 curl 確認 model 回傳格式）：
   ```bash
   curl -s https://api.wavespeed.ai/api/v3/<model-path> \
     -H "Authorization: Bearer <API_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"<param>": "<value>"}'
   ```

6. **更新成本估算**：在 MEMORY.md 的「每支影片估算成本」欄位更新

## Crash Recovery 模式

每個 WaveSpeed job 都要存 prediction_id 到 `asset_tasks`：
```python
job_state.asset_tasks["staging_room1"] = AssetTask(
    status="submitted",
    remote_job_id=prediction_id
)
```
重啟時用 `existing_id` 繼續輪詢，避免重複計費。
