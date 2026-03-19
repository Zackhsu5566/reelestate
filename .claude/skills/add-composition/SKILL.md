---
name: add-composition
description: 新增 Remotion scene（composition）到 ReelEstate 影片
---

**寫任何 Remotion 程式碼前，必須先讀取相關規則：**
`C:\Users\being\skills\remotion-video-toolkit\rules\`

## 現有 Scene 結構

```
OpeningScene → [fade] → ClipScene × N → [fade] → StatsScene → [fade] → CTAScene
```

檔案位置：`remotion/src/compositions/`

## 新增 Scene 步驟

1. **建立 Scene 檔案** `remotion/src/compositions/<SceneName>.tsx`

   - 讀取 `remotiontheme3.15` 資料夾中的視覺風格參考
   - 使用 `useCurrentFrame()` + `interpolate()` 做動畫
   - 字型使用 `@remotion/google-fonts/NotoSansTC`
   - 尺寸固定 1080 × 1920（9:16）

2. **定義時長常數**（在 `CLAUDE.md` 已定義的常數下新增）：

   ```ts
   export const NEW_SCENE_FRAMES = <n> * 30; // <n>s
   ```

3. **更新 `remotion/src/types.ts`**：新增 props 型別

4. **更新 `remotion/src/ReelEstateVideo.tsx`**：
   - import scene
   - 在 `<Sequence>` 中排入正確位置
   - 計算 `from` offset（加總前面所有 scene 的 frames）

5. **更新 `remotion/src/Root.tsx`**：調整 `durationInFrames`

6. **更新 `orchestrator/services/render.py`**：確認 inputProps 包含新 scene 所需資料

7. **本地驗證**：

   ```bash
   cd remotion && npx remotion render ReelEstateVideo out/test.mp4 --props=input.json
   ```

## 轉場規則

Scene 間一律使用 `fade` from `@remotion/transitions`，15 frames（0.5s）。
詳見 `remotion-video-toolkit/rules/transitions.md`。
