---
name: deploy-update
description: 部署更新到 VPS（Remotion render server 或 orchestrator）
---

## Remotion Render Server 更新

**VPS**: `187.77.150.149`，container `reelestate-remotion`

```bash
# 1. push 到 GitHub
cd remotion && git push origin main

# 2. SSH 進 VPS 更新
ssh root@187.77.150.149 "
  cd /opt/reelestate && git pull &&
  cd remotion &&
  docker build -t reelestate-remotion . &&
  docker stop reelestate-remotion &&
  docker rm reelestate-remotion &&
  docker run -d --name reelestate-remotion --restart unless-stopped \
    -p 3100:3000 \
    -e PORT=3000 \
    -e RENDER_API_TOKEN=reelestate-render-token-2024 \
    -e R2_PROXY_URL=\$R2_PROXY_URL \
    -e R2_UPLOAD_TOKEN=\$R2_UPLOAD_TOKEN \
    reelestate-remotion
"

# 3. 驗證健康狀態
curl -sk https://187.77.150.149/health \
  -H "Host: render.replowapp.com" \
  -H "Authorization: Bearer reelestate-render-token-2024"
```

## Orchestrator 更新

**VPS**: `187.77.150.149`，repo `/opt/reelestate`，docker compose 在 `orchestrator/`

```bash
# 1. push 到 GitHub
git push origin master

# 2. SSH 進 VPS 更新
ssh root@187.77.150.149 "
  cd /opt/reelestate &&
  git pull &&
  cd orchestrator &&
  docker compose up -d --build
"

# 3. 驗證 container 正常啟動
ssh root@187.77.150.149 "docker logs orchestrator-orchestrator-1 --tail 5"
```

> **注意**：VPS 上是 `docker compose`（plugin 版），不是 `docker-compose`。

## 部署前檢查清單

- [ ] 環境變數確認（不 hardcode secrets）
- [ ] Dockerfile 沒有快取問題（必要時加 `--no-cache`）
- [ ] 部署後確認 container 正常啟動（檢查 logs）
- [ ] container 確認 `--restart unless-stopped`
