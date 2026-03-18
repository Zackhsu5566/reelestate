import path from "path";
import fs from "fs";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import type { RenderInput } from "./types";

const ENTRY_POINT = path.resolve(__dirname, "..", "..", "src", "index.ts");
const PUBLIC_DIR = path.resolve(__dirname, "..", "..", "public");
const RENDER_TIMEOUT = 300_000; // 5 minutes

function log(jobId: string, msg: string) {
  console.log(JSON.stringify({ ts: new Date().toISOString(), jobId, module: "renderer", msg }));
}

/**
 * Bundle the Remotion project and render a video.
 * Must be called AFTER assets are downloaded to public/.
 */
export async function renderVideo(
  jobId: string,
  input: RenderInput,
  onProgress: (progress: number) => void,
): Promise<string> {
  const outputPath = path.resolve(__dirname, "..", "out", `${jobId}.mp4`);
  await fs.promises.mkdir(path.dirname(outputPath), { recursive: true });

  // Bundle WITH publicDir (snapshots public/ including newly downloaded assets)
  log(jobId, "bundling...");
  const bundleUrl = await bundle({
    entryPoint: ENTRY_POINT,
    publicDir: PUBLIC_DIR,
  });
  log(jobId, "bundle complete");

  // Select composition with dynamic metadata
  const composition = await selectComposition({
    serveUrl: bundleUrl,
    id: "ReelEstateVideo",
    inputProps: input as unknown as Record<string, unknown>,
  });

  // Render with timeout
  log(jobId, `rendering ${composition.durationInFrames} frames...`);
  const renderPromise = renderMedia({
    composition,
    serveUrl: bundleUrl,
    codec: "h264",
    outputLocation: outputPath,
    inputProps: input as unknown as Record<string, unknown>,
    concurrency: 2,
    onProgress: ({ progress }) => {
      const pct = Math.round(progress * 100);
      onProgress(pct);
      if (pct % 20 === 0) {
        log(jobId, `rendering ${pct}%`);
      }
    },
  });

  let timer: ReturnType<typeof setTimeout>;
  const timeoutPromise = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("Render timeout exceeded")), RENDER_TIMEOUT);
  });

  try {
    await Promise.race([renderPromise, timeoutPromise]);
  } finally {
    clearTimeout(timer!);
  }

  log(jobId, "render complete");

  // Clean up bundle temp files
  try {
    await fs.promises.rm(bundleUrl, { recursive: true, force: true });
  } catch {
    // best-effort
  }

  return outputPath;
}

