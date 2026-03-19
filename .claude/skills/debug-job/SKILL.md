---
name: debug-job
description: 偵錯失敗的 pipeline job（從 Redis 狀態、log、asset_tasks 追蹤問題根因）
---

當 job 狀態變成 `failed` 或卡在某個 stage，依照以下步驟排查。

## 步驟

### 1. 取得完整 job 狀態

```bash
curl -s http://localhost:8000/jobs/<job_id> | jq .
```

重點欄位：
- `status`: 卡在哪個 stage
- `errors`: 錯誤訊息列表
- `asset_tasks`: 各 WaveSpeed job 的 status / remote_job_id / error

### 2. 依 stage 排查

| Stage | 常見問題 |
|-------|---------|
| `analyzing` | Agent prompt 格式、structured output 解析失敗 |
| `tts` | MiniMax T2A API 錯誤、音訊 URL 無效 |
| `generating` | WaveSpeed API 錯誤、R2 URL 無法存取、圖片格式問題 |
| `rendering` | Remotion bundle 失敗、inputProps schema 不符、assets 下載失敗 |

### 3. 追蹤 WaveSpeed job

```bash
# 用 asset_tasks 中的 remote_job_id 直接查 WaveSpeed
PRED_ID="<prediction_id>"
curl -s "https://api.wavespeed.ai/api/v3/predictions/$PRED_ID/result" \
  -H "Authorization: Bearer <API_KEY>" | jq '.data | {status, error, outputs}'
```

### 4. 查 R2 URL 可存取性

```bash
curl -I "<r2_url>"
# 期望: HTTP 200，Content-Type: image/jpeg 或 video/mp4
```

### 5. 重新執行失敗的 job

因為 `asset_tasks` 記錄了已完成的工作，可以安全地重新觸發：
```bash
curl -s -X POST http://localhost:8000/jobs/<job_id>/retry | jq .
```
（如果尚未實作 retry endpoint，手動清除 `status=failed` 改回上一個 stage）

### 6. 完整 orchestrator log

```bash
# 本地開發
tail -f orchestrator/logs/app.log

# VPS（如已部署）
ssh root@187.77.150.149 "docker logs reelestate-orchestrator --tail=200 -f"
```

## Crash Recovery 機制

`asset_tasks` 中 `status=submitted` 的 job 在重啟後會繼續輪詢（不重新送），
`status=completed` 的不會重跑。這個機制在 `pipeline/jobs.py` 實作。
