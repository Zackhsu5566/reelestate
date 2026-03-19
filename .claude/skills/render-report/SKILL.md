---
name: render-report
description: 偵錯 Remotion render 問題：把有問題的 input 送到 render server 重現錯誤
---

當使用者回報影片 render 異常，執行以下步驟重現問題。

## 步驟

1. **確認 input.json**

   把問題的 payload 放到 `remotion/input.json`（格式參考 `concept.md`）。

2. **本地 render 測試**

   ```bash
   cd remotion
   npx remotion render ReelEstateVideo out/debug.mp4 --props=input.json --log=verbose
   ```

3. **若問題只在 VPS 出現，送到 render server**

   ```bash
   curl -sk https://187.77.150.149/render \
     -H "Host: render.replowapp.com" \
     -H "Authorization: Bearer reelestate-render-token-2024" \
     -H "Content-Type: application/json" \
     -d @remotion/input.json
   ```

   拿到 `jobId` 後輪詢狀態：

   ```bash
   curl -sk https://187.77.150.149/render/<jobId> \
     -H "Host: render.replowapp.com" \
     -H "Authorization: Bearer reelestate-render-token-2024"
   ```

4. **查 VPS container log**

   ```bash
   ssh root@187.77.150.149 "docker logs reelestate-remotion --tail=100 -f"
   ```

5. **常見問題 checklist**
   - 中文檔名 → assets.ts 是否正確轉為英文索引名（`clip-0.mp4`）
   - `bundle()` 前是否先 `downloadAssets()`
   - R2 URL 是否可公開存取（curl 測試）
   - `isUrl()` 判斷是否正確（僅 `http(s)://` 開頭）
