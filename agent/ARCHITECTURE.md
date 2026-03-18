> **DEPRECATED（2026-03-14）**：此文件為早期設計草案，已被 `ARCHITECTURE.md`（FastAPI Orchestrator 架構）取代。
> Worker A/B/D 已全部改用 WaveSpeed API，TTS 改用 MiniMax T2A，前端改用 Telegram。
> 保留此文件僅供歷史參考。

# ReelEstate Agent Orchestrator 架構設計

## Context

ReelEstate 目前 4 個 RunPod Worker（A/B/C/D）和 Remotion Render Server 都已有 API 合約，但缺少一個中央 orchestrator 將它們串起來。現有的 `agent/SKILL.md` 只是簡單的 input.json 生成器（v1），需要重寫為完整的 pipeline 控制器。

目標：設計一個跑在 OpenClaw 上的 Agent Orchestrator，自動驅動整條影片生成 pipeline。

**前端整合**：n8n + LINE（不是 Telegram）
- 房仲透過 LINE 傳照片 + 資料 → n8n 處理（上傳照片到 R2、整理表單）→ 呼叫 OpenClaw Agent
- 3 個審核閘門（Gate 1/1.5/2）也透過 n8n → LINE 通知房仲 + 接收回覆
- OpenClaw Agent 不直接面對房仲，只處理乾淨的結構化資料

---

## 架構決策

| 決策 | 選擇 | 原因 |
|------|------|------|
| 控制中心 | Python state-machine (`orchestrator.py`) | Lobster 不支援平行分支；Python 可處理 dependency graph |
| 平行執行 | Python submit + OpenClaw sub-agents 背景 poll | Sub-agents 不阻塞主 agent，完成時自動回報 |
| 審核閘門 | n8n webhook callback | Agent 透過 n8n 傳 LINE 通知，n8n 收到回覆後 callback Agent |
| 前端入口 | n8n + LINE | n8n 處理收件 + 上傳 R2 + 整理表單，Agent 收乾淨資料 |
| 狀態管理 | 每個 job 一個 JSON 檔 (`/tmp/reelestate_jobs/{job_id}/state.json`) | 簡單、跨 gate 持久化、agent 可隨時查看 |
| Skill 結構 | 一個 SKILL.md + 多個 Python 輔助腳本 | SKILL.md 管流程邏輯，Python 管 API 呼叫和狀態 |

---

## 檔案結構

```
C:\Users\being\Projects\ReelEstate\agent\
├── SKILL.md                 # OpenClaw skill：完整 pipeline 指令（重寫）
├── orchestrator.py          # 狀態機驅動（CLI subcommands）
├── runpod_client.py         # RunPod API wrapper（submit + poll）
├── remotion_client.py       # Remotion render API wrapper
└── state.py                 # State schema、load/save、build_render_input()
```

Runtime 狀態（每個 job）:
```
/tmp/reelestate_jobs/{job_id}/
├── state.json               # Pipeline 狀態
├── script.txt               # 帶 [SECTION] markers 的講稿
└── plan.json                # VLM 分析輸出（空間、角度、配對）
```

---

## Pipeline 狀態機

```
INIT → SCRIPT_DRAFT → GATE_1_PENDING → TTS → GATE_1_5_PENDING
     → PARALLEL_PROCESSING → PREVIEW_RENDER → GATE_2_PENDING
     → UPSCALE → FINAL_RENDER → DELIVERED
```

### 各階段對應 OpenClaw 原語

| 階段 | 誰負責 | 怎麼做 |
|------|--------|--------|
| 0. 收件 | n8n | LINE 收照片+表單 → 上傳照片到 R2 → 整理成結構化 JSON → 呼叫 Agent |
| 1. VLM 分析 | Agent 本身 | 用 VLM 分析 R2 上的照片，規劃空間/角度/配對 |
| 2. 寫講稿 | Agent 本身 | 帶 `[SECTION]` markers 的旁白腳本 |
| 3. Gate 1 | Agent → n8n webhook → LINE | 傳講稿給房仲，n8n 收到回覆後 callback Agent |
| 4. TTS | `orchestrator.py run-tts` | 呼叫 Worker C TTS，blocking poll（~30s） |
| 5. Gate 1.5 | Agent → n8n webhook → LINE | 傳音檔 URL 給房仲試聽 |
| 6. 平行處理 | `orchestrator.py submit-parallel` + sub-agents poll | 見下方 dependency graph |
| 7. 預覽 render | `orchestrator.py render-preview` | 組裝 RenderInput + 呼叫 Remotion |
| 8. Gate 2 | Agent → n8n webhook → LINE | 傳預覽 MP4 給房仲 |
| 9. Upscale | `orchestrator.py submit-upscale` + sub-agent poll | Worker D Upscale |
| 10. 最終 render | `orchestrator.py render-final` | 用 HQ clips 重新 render |
| 11. 交付 | Agent → n8n → LINE | 傳最終 MP4 URL |

---

## 平行處理 Dependency Graph

```
                    ┌─── Worker C Align（獨立）
                    │
Gate 1.5 OK ────────┼─── Worker D Staging ×N（各空間，獨立）
                    │
                    ├─── Worker A ×M（單照片空間 → angle2）
                    │         │
                    │         └──→ Worker B（依賴 A 的輸出）
                    │
                    └─── Worker B ×K（多照片空間，獨立）
```

**兩階段提交**：
1. `submit-parallel`：提交所有獨立 job（Align、Staging、Worker A、多照片 Worker B）
2. Worker A 完成後 → `submit-dependent-b`：提交依賴 A 的 Worker B job

**Sub-agent 分配**（最多 4 個背景 agent）：
- Sub-agent 1：poll Worker A jobs
- Sub-agent 2：poll Worker B 獨立 jobs
- Sub-agent 3：poll Worker C Align
- Sub-agent 4：poll Worker D Staging jobs

---

## orchestrator.py CLI 介面

```
orchestrator.py init                 # 建立 job state
orchestrator.py approve --gate X     # 標記 gate 通過
orchestrator.py run-tts              # TTS（blocking poll ~30s）
orchestrator.py submit-parallel      # 提交所有獨立 GPU jobs
orchestrator.py submit-dependent-b   # 提交依賴 A 的 Worker B
orchestrator.py poll-category --cat X  # Poll 某類別直到完成（sub-agent 用）
orchestrator.py check-parallel       # 檢查是否所有平行 job 完成
orchestrator.py render-preview       # 組裝 + 預覽 render
orchestrator.py submit-upscale       # 提交 upscale jobs
orchestrator.py render-final         # 最終 render
orchestrator.py resume               # 讀取 state，判斷目前階段，輸出下一步指令
orchestrator.py status               # 印出目前狀態摘要
```

所有命令都吃 `--job-id`，讀寫 `/tmp/reelestate_jobs/{job_id}/state.json`。

---

## State JSON Schema（關鍵欄位）

```json
{
  "job_id": "re_20260312_abc123",
  "stage": "PARALLEL_PROCESSING",
  "property": { "title", "location", "address", "size", "layout", "floor", "price", "contact", "agentName", "has_staging" },
  "spaces": [
    {
      "name": "客廳",
      "photos": ["url1", "url2"],
      "needs_qwen_edit": false,
      "wan_pairs": [{"first_frame": "url", "last_frame": "url", "clip_name": "客廳1"}],
      "staging_prompt": "...",
      "staging_url": null
    }
  ],
  "script": { "text": "...", "approved": false },
  "tts": { "runpod_run_id": null, "audio_url": null, "approved": false },
  "alignment": { "sections": [], "captions": [], "total_duration_ms": null },
  "gpu_tasks": {
    "worker_a": { "<space>": { "runpod_run_id", "status", "output_url" } },
    "worker_b": { "<clip>": { "runpod_run_id", "status", "output_url", "blocked_by?" } },
    "worker_d_staging": { "<space>": { "runpod_run_id", "status", "output_url" } }
  },
  "preview_render": { "remotion_job_id", "output_url", "approved" },
  "upscale": { "<clip>": { "runpod_run_id", "status", "output_url" } },
  "final_render": { "remotion_job_id", "output_url" },
  "errors": []
}
```

---

## n8n ↔ Agent 介面

### n8n → Agent（觸發 pipeline）
n8n 收到 LINE 訊息後，整理成結構化 JSON，透過 OpenClaw API 或 `openclaw agent --message` 觸發：

```json
{
  "action": "new_job",
  "property": {
    "address": "台北市信義區永吉路123號",
    "price": "2,980萬",
    "size": "35坪",
    "layout": "2房2廳1衛",
    "floor": "12F / 15F",
    "features": "採光佳、近捷運",
    "agent_name": "王小明",
    "company": "信義房屋",
    "phone": "0912-345-678",
    "has_staging": true
  },
  "photos": [
    {"space": "客廳", "urls": ["https://assets.replowapp.com/uploads/xxx/1.jpg", "https://assets.replowapp.com/uploads/xxx/2.jpg"]},
    {"space": "主臥", "urls": ["https://assets.replowapp.com/uploads/xxx/3.jpg"]}
  ],
  "line_user_id": "U1234567890",
  "callback_url": "https://n8n.example.com/webhook/reelestate-gate"
}
```

### Agent → n8n（審核閘門）
Agent 在 Gate 1/1.5/2 時，POST 到 n8n callback URL：

```json
{
  "gate": "script",
  "job_id": "re_20260312_abc123",
  "line_user_id": "U1234567890",
  "content": "講稿文字 or 音檔URL or 影片URL",
  "resume_url": "https://openclaw-gateway/api/agent/resume?job_id=re_20260312_abc123&gate=script"
}
```

n8n 收到後：
1. 透過 LINE 傳內容給房仲
2. 房仲回覆 OK/修改
3. n8n POST 回 Agent 的 resume_url，附上 `{"approved": true}` 或 `{"approved": false, "feedback": "..."}`

### 關鍵：Agent 暫停/恢復機制
Gate 期間 Agent 不需要保持 session。流程：
1. Agent 完成階段工作 → 儲存 state → POST 到 n8n → 結束 session
2. n8n 收到房仲回覆 → 呼叫 OpenClaw Agent → Agent 讀取 state → 從下一階段繼續

這表示 `orchestrator.py` 需要一個 `resume` 命令，讀取 state 判斷目前階段，繼續執行。

---

## 錯誤處理

| 錯誤類型 | 策略 |
|----------|------|
| RunPod job FAILED | 重試最多 3 次，記錄到 `state.errors` |
| RunPod timeout (>10min) | 取消 + 重試 1 次，仍失敗則通知使用者 |
| Remotion render FAILED | 檢查錯誤訊息，驗證 URL 後重試 |
| 網路錯誤 | 指數退避重試（5s, 15s, 30s） |
| State 損壞 | 每次寫入前保留 `.bak` 備份 |

---

## 環境變數

```
RUNPOD_API_KEY=<key>
RUNPOD_ENDPOINT_A=<TBD>
RUNPOD_ENDPOINT_B=<TBD>
RUNPOD_ENDPOINT_C=391h73cn715crm
RUNPOD_ENDPOINT_D=<TBD>
REMOTION_RENDER_TOKEN=reelestate-render-token-2024
R2_PROXY_URL=https://reelestate-r2-proxy.beingzackhsu.workers.dev
R2_UPLOAD_TOKEN=reelestate-r2-proxy-token-2024
```

---

## 實作順序

1. **`state.py`** — State schema + load/save + `build_render_input()`
2. **`runpod_client.py`** — RunPod API wrapper
3. **`remotion_client.py`** — Remotion API wrapper
4. **`orchestrator.py`** — CLI subcommands，逐步實作各階段
5. **`SKILL.md`** — 重寫為完整 pipeline 指令

## 系統架構圖

```
房仲（LINE）
    ↕
n8n（前端 + 審核閘門）
    │  ├─ 收件：LINE 照片+表單 → 上傳 R2 → 整理 JSON
    │  ├─ Gate 通知：Agent POST → n8n → LINE 傳給房仲
    │  └─ Gate 回覆：房仲 LINE 回覆 → n8n → 呼叫 Agent resume
    ↕
OpenClaw Agent（orchestrator）
    │  ├─ VLM 分析照片
    │  ├─ 寫講稿
    │  └─ 呼叫 orchestrator.py 各 subcommand
    ↕
orchestrator.py（Python 狀態機）
    ├─→ RunPod Workers A/B/C/D（GPU 推論）
    ├─→ Remotion Render Server（影片合成）
    └─→ R2（素材暫存 + CDN 交付）
```

## 驗證方式

1. 用 Worker C（已部署）測試 `run-tts` + `submit-parallel`（Align action）
2. Mock Worker A/B/D（未部署）的 submit/poll 流程，驗證狀態機轉換
3. 用 Remotion Server 測試 `render-preview`（已部署）
4. n8n ↔ Agent 介面可用 webhook.site 模擬測試
5. 完整端到端測試需等 Worker A/B/D 部署後
