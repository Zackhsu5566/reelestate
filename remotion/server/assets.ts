import fs from "fs";
import path from "path";
import { pipeline } from "stream/promises";
import { Readable } from "stream";
import type { RenderInput, SceneInput, ClipScene, KenBurnsScene, OpeningSceneExt } from "./types";

const PUBLIC_DIR = path.resolve(__dirname, "..", "..", "public");
const PER_FILE_TIMEOUT = 30_000;
const MAX_RETRIES = 2;
const RETRY_DELAY = 1_000;

function log(jobId: string, msg: string) {
  console.log(JSON.stringify({ ts: new Date().toISOString(), jobId, module: "assets", msg }));
}

async function downloadFile(
  url: string,
  dest: string,
  timeout: number = PER_FILE_TIMEOUT,
): Promise<number> {
  await fs.promises.mkdir(path.dirname(dest), { recursive: true });
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  try {
    const resp = await fetch(url, { signal: controller.signal });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status} downloading ${url}`);
    }
    if (!resp.body) {
      throw new Error(`No response body for ${url}`);
    }
    const writeStream = fs.createWriteStream(dest);
    await pipeline(Readable.fromWeb(resp.body as any), writeStream);
    const stat = await fs.promises.stat(dest);
    return stat.size;
  } finally {
    clearTimeout(timer);
  }
}

async function downloadWithRetry(
  url: string,
  dest: string,
  retries: number = MAX_RETRIES,
): Promise<number> {
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      return await downloadFile(url, dest);
    } catch (err) {
      if (attempt === retries) throw err;
      await new Promise((r) => setTimeout(r, RETRY_DELAY));
    }
  }
  throw new Error("unreachable");
}

function isUrl(s: string): boolean {
  return s.startsWith("http://") || s.startsWith("https://");
}

function extFromUrl(url: string): string {
  const pathname = new URL(url).pathname;
  const ext = path.extname(pathname);
  return ext || ".mp4";
}

/**
 * Download all remote assets from a RenderInput and return a mapped input
 * where URLs have been replaced with local paths relative to public/.
 */
export async function downloadAssets(
  jobId: string,
  input: RenderInput,
): Promise<RenderInput> {
  const startTime = Date.now();
  const jobDir = path.join("jobs", jobId);
  const absJobDir = path.join(PUBLIC_DIR, jobDir);
  await fs.promises.mkdir(path.join(absJobDir, "clips"), { recursive: true });
  await fs.promises.mkdir(path.join(absJobDir, "images"), { recursive: true });
  await fs.promises.mkdir(path.join(absJobDir, "audio"), { recursive: true });

  const downloads: Promise<{ label: string; size: number }>[] = [];
  const mappedScenes: SceneInput[] = [];

  for (let i = 0; i < input.scenes.length; i++) {
    const scene = input.scenes[i];
    if (scene.type === "clip" || scene.type === "ken_burns") {
      const clip = scene as ClipScene | KenBurnsScene;
      let localSrc = clip.src;
      if (isUrl(clip.src)) {
        const ext = extFromUrl(clip.src);
        localSrc = `${jobDir}/clips/clip-${i}${ext}`;
        const absDest = path.join(PUBLIC_DIR, localSrc);
        downloads.push(
          downloadWithRetry(clip.src, absDest).then((size) => ({
            label: `clip-${i}`,
            size,
          })),
        );
      }

      let localStaging = clip.stagingImage;
      if (clip.stagingImage && isUrl(clip.stagingImage)) {
        const ext = extFromUrl(clip.stagingImage);
        localStaging = `${jobDir}/images/staging-${i}${ext}`;
        const absDest = path.join(PUBLIC_DIR, localStaging);
        downloads.push(
          downloadWithRetry(clip.stagingImage, absDest).then((size) => ({
            label: `staging-${i}`,
            size,
          })),
        );
      }

      mappedScenes.push({ ...clip, src: localSrc, stagingImage: localStaging });
    } else if (scene.type === "opening" && "exteriorPhoto" in scene) {
      const opening = scene as OpeningSceneExt;
      let localExterior = opening.exteriorPhoto;
      if (opening.exteriorPhoto && isUrl(opening.exteriorPhoto)) {
        const ext = extFromUrl(opening.exteriorPhoto);
        localExterior = `${jobDir}/images/exterior${ext}`;
        const absDest = path.join(PUBLIC_DIR, localExterior);
        downloads.push(
          downloadWithRetry(opening.exteriorPhoto, absDest).then((size) => ({
            label: "exterior",
            size,
          })),
        );
      }
      mappedScenes.push({ ...opening, exteriorPhoto: localExterior });
    } else {
      // stats/cta scenes may have a backgroundSrc URL that needs downloading
      let mapped = scene;
      if ("backgroundSrc" in scene && typeof scene.backgroundSrc === "string" && isUrl(scene.backgroundSrc)) {
        const ext = extFromUrl(scene.backgroundSrc);
        const localBg = `${jobDir}/images/bg-${i}${ext}`;
        const absDest = path.join(PUBLIC_DIR, localBg);
        downloads.push(
          downloadWithRetry(scene.backgroundSrc, absDest).then((size) => ({
            label: `bg-${i}`,
            size,
          })),
        );
        mapped = { ...scene, backgroundSrc: localBg };
      }
      mappedScenes.push(mapped);
    }
  }

  // Narration
  let localNarration = input.narration;
  if (isUrl(input.narration)) {
    const ext = extFromUrl(input.narration);
    localNarration = `${jobDir}/audio/narration${ext}`;
    downloads.push(
      downloadWithRetry(input.narration, path.join(PUBLIC_DIR, localNarration)).then(
        (size) => ({ label: "narration", size }),
      ),
    );
  }

  // BGM
  let localBgm = input.bgm;
  if (input.bgm && isUrl(input.bgm)) {
    const ext = extFromUrl(input.bgm);
    localBgm = `${jobDir}/audio/bgm${ext}`;
    downloads.push(
      downloadWithRetry(input.bgm, path.join(PUBLIC_DIR, localBgm)).then((size) => ({
        label: "bgm",
        size,
      })),
    );
  }

  // Execute all downloads in parallel
  log(jobId, `downloading ${downloads.length} assets...`);
  const results = await Promise.all(downloads);
  const totalSize = results.reduce((sum, r) => sum + r.size, 0);
  const elapsed = Date.now() - startTime;
  log(jobId, `downloaded ${results.length} assets, total ${(totalSize / 1024 / 1024).toFixed(1)}MB in ${elapsed}ms`);

  return {
    ...input,
    scenes: mappedScenes,
    narration: localNarration,
    bgm: localBgm,
  };
}

/**
 * Clean up downloaded assets for a job.
 */
export async function cleanupAssets(jobId: string): Promise<void> {
  const jobDir = path.join(PUBLIC_DIR, "jobs", jobId);
  try {
    await fs.promises.rm(jobDir, { recursive: true, force: true });
    log(jobId, "cleaned up assets");
  } catch {
    // best-effort cleanup
  }
}
