---
name: pr
description: 建立 Pull Request（格式化、commit、push、gh pr create）
---

確認不在 main branch；如有需要先建立新分支。

## Commit 格式

```
`[component]`: [commit-message]
```

Component 對照：
- `orchestrator` — FastAPI 主程式、pipeline、services
- `remotion` — Remotion composition、scene、assets
- `r2-proxy` — R2 上傳 proxy
- `infra` — Dockerfile、docker-compose、nginx、deploy 設定

範例：`\`orchestrator\`: Add gate_preview retry logic`

如果跨多個 component，使用最主要的那個。

## 步驟

1. 格式化 Python 程式碼（orchestrator）：
   ```
   cd <changed_dir> && python -m ruff format . && python -m ruff check . --fix
   ```
2. 格式化 TypeScript 程式碼（remotion）：
   ```
   cd remotion && npx prettier --write src/
   ```
3. `git add` 相關檔案（避免 git add -A）
4. `git commit -m "[component]: message"`
5. `git push -u origin <branch>`
6. `gh pr create --title "[component]: message" --body "..."`

PR body 格式：
```
## 異動內容
- 條列式說明

## 測試方式
- [ ] 測試步驟

## 注意事項
- 如有 breaking change 或部署順序需求
```
