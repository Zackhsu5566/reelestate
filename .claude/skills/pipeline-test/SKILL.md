---
name: pipeline-test
description: 對 ReelEstate E2E pipeline 進行測試
---

## 完整 E2E 測試流程

### 1. 準備測試 payload

使用 `orchestrator/test_payload.json` 作為基礎，或自訂：

```json
{
  "raw_text": "台北市信義區忠孝東路 5 段 100 號 3 樓\n3 房 2 廳，45 坪，售價 2980 萬\n王小明 0912-345-678",
  "spaces": [
    {
      "label": "客廳",
      "photos": ["https://<r2-url>/test-photo.jpg"]
    }
  ],
  "premium": false,
  "line_user_id": "test-user",
  "callback_url": ""
}
```

### 2. 啟動 orchestrator（本地）

```bash
cd orchestrator && uvicorn main:app --reload --port 8000
```

### 3. 送出 job

```bash
curl -s http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d @test_payload.json | jq .
```

### 4. 輪詢 job 狀態

```bash
JOB_ID="<job_id>"
while true; do
  STATUS=$(curl -s http://localhost:8000/jobs/$JOB_ID | jq -r '.status')
  echo "$(date): $STATUS"
  [[ "$STATUS" == "done" || "$STATUS" == "failed" ]] && break
  sleep 5
done
```

### 5. 驗證各 pipeline stage

| Stage | 驗證方式 |
|-------|---------|
| `analyzing` | agent_result 中的 property / spaces 資料正確 |
| `tts` | audio_url 可存取，音訊長度合理 |
| `generating` | 所有 asset_tasks 都是 `completed` |
| `rendering` | preview_url 可存取，影片可播放 |
| `done` | final_url 存在 |

### 6. 個別 service 測試

```bash
# WaveSpeed staging
python -c "
import asyncio
from orchestrator.services.wavespeed import wavespeed
async def test():
    await wavespeed.start()
    url = await wavespeed.staging('<image_url>', '現代簡約風格客廳')
    print(url)
    await wavespeed.close()
asyncio.run(test())
"

# Render server health
curl -sk https://187.77.150.149/health \
  -H "Host: render.replowapp.com" \
  -H "Authorization: Bearer reelestate-render-token-2024"
```
