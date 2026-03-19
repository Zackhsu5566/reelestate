---
name: add-api-field
description: 新增欄位到 orchestrator API（CreateJobRequest / JobState / AgentResult 等）
---

新增 API 欄位時，需同步更新所有使用到該資料的層級。

## 欄位類型與位置

| 資料流向 | 相關 model |
|---------|-----------|
| 使用者輸入 | `CreateJobRequest` |
| Pipeline 狀態 | `JobState` |
| Agent 分析輸出 | `AgentResult`, `SpaceInfo`, `PropertyInfo` |
| Sub-task 追蹤 | `AssetTask` |
| Space 輸入 | `SpaceInput` |

## 步驟

1. **更新 `orchestrator/models.py`**：
   - 在對應 model 加入欄位
   - 有預設值的欄位才能放非必填（`field: type = default`）
   - 新必填欄位需確認所有建立該 model 的地方都有傳入

2. **更新 Agent prompt**（如 `AgentResult` 相關欄位）：
   `orchestrator/services/agent.py`
   - 更新 system prompt / structured output schema

3. **更新 pipeline 使用點**：
   `orchestrator/pipeline/jobs.py`
   - 讀取新欄位、傳給下游 service

4. **更新 Remotion inputProps**（如果欄位會傳到 render）：
   `orchestrator/services/render.py`
   - 確認 `input_props` dict 包含新欄位
   - 更新 `remotion/src/types.ts` 中的 inputProps 型別

5. **向後相容**：
   - Redis 中存的舊 `JobState` 可能沒有新欄位 → 一律給預設值
   - Pydantic 的 `model_validate()` 對未知欄位是 ignore，不影響舊資料

6. **測試**：
   ```bash
   # 確認 API schema 正確
   curl -s http://localhost:8000/openapi.json | jq '.components.schemas.CreateJobRequest'
   ```

## 命名規範

- Python 用 `snake_case`
- TypeScript inputProps 用 `camelCase`
- 兩者在 `render.py` 轉換（`total_duration_ms` → `totalDurationMs`）
