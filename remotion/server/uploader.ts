import fs from "fs";

const R2_PROXY_URL = process.env.R2_PROXY_URL || "https://reelestate-r2-proxy.beingzackhsu.workers.dev";
const R2_UPLOAD_TOKEN = process.env.R2_UPLOAD_TOKEN || "reelestate-r2-proxy-token-2024";
const UPLOAD_TIMEOUT = 120_000;
const MAX_RETRIES = 2;

function log(jobId: string, msg: string) {
  console.log(JSON.stringify({ ts: new Date().toISOString(), jobId, module: "uploader", msg }));
}

async function uploadOnce(filePath: string, r2Key: string, contentType = "video/mp4"): Promise<string> {
  const fileBuffer = await fs.promises.readFile(filePath);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT);

  try {
    const resp = await fetch(`${R2_PROXY_URL}/${r2Key}`, {
      method: "PUT",
      headers: {
        "X-Upload-Token": R2_UPLOAD_TOKEN,
        "Content-Type": contentType,
      },
      body: fileBuffer,
      signal: controller.signal,
    });

    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`R2 upload failed: HTTP ${resp.status} - ${text}`);
    }

    const result = (await resp.json()) as { url: string };
    return result.url;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Upload a rendered MP4 to R2 and return the public URL.
 */
export async function uploadToR2(jobId: string, filePath: string): Promise<string> {
  const r2Key = `renders/${jobId}.mp4`;
  return uploadFile(jobId, filePath, r2Key, "video/mp4");
}

/**
 * Upload a still image (PNG) to R2 and return the public URL.
 */
export async function uploadStillToR2(jobId: string, filePath: string): Promise<string> {
  const r2Key = `stills/${jobId}.png`;
  return uploadFile(jobId, filePath, r2Key, "image/png");
}

async function uploadFile(jobId: string, filePath: string, r2Key: string, contentType: string): Promise<string> {
  const stat = await fs.promises.stat(filePath);
  log(jobId, `uploading ${(stat.size / 1024 / 1024).toFixed(1)}MB to ${r2Key}...`);

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const url = await uploadOnce(filePath, r2Key, contentType);
      log(jobId, `upload complete: ${url}`);
      return url;
    } catch (err) {
      if (attempt === MAX_RETRIES) throw err;
      log(jobId, `upload attempt ${attempt} failed, retrying...`);
      await new Promise((r) => setTimeout(r, 1_000));
    }
  }

  throw new Error("unreachable");
}

/**
 * Clean up the local output MP4.
 */
export async function cleanupOutput(filePath: string): Promise<void> {
  try {
    await fs.promises.unlink(filePath);
  } catch {
    // best-effort
  }
}
