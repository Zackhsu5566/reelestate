import type { Request, Response } from "express";
import type { Job } from "./types";
import { validateRenderRequest, sanitizeForLog } from "./types";
import { downloadAssets, cleanupAssets } from "./assets";
import { renderVideo } from "./renderer";
import { uploadToR2, cleanupOutput } from "./uploader";

const MAX_CONCURRENT = 1;
const jobs = new Map<string, Job>();
const pendingQueue: string[] = [];
let activeCount = 0;

// Store full request inputs keyed by jobId for deferred processing
const pendingInputs = new Map<string, any>();

function log(jobId: string, msg: string) {
  console.log(JSON.stringify({ ts: new Date().toISOString(), jobId, module: "handler", msg }));
}

async function processJob(jobId: string, input: any): Promise<void> {
  const job = jobs.get(jobId)!;
  job.status = "rendering";
  job.startedAt = new Date();
  activeCount++;

  let outputPath: string | undefined;

  try {
    // 1. Download assets (maps API keys redacted in log)
    log(jobId, `render request (input: ${JSON.stringify(sanitizeForLog(input)).slice(0, 200)}...)`);
    const mappedInput = await downloadAssets(jobId, input);

    // 2. Render
    log(jobId, "starting render");
    outputPath = await renderVideo(jobId, mappedInput, (progress) => {
      job.progress = progress;
    });

    // 3. Upload to R2
    log(jobId, "starting upload");
    const outputUrl = await uploadToR2(jobId, outputPath);

    // 4. Mark complete
    job.status = "completed";
    job.progress = 100;
    job.outputUrl = outputUrl;
    job.completedAt = new Date();
    log(jobId, `completed: ${outputUrl}`);
  } catch (err: any) {
    job.status = "failed";
    job.error = err.message || String(err);
    job.completedAt = new Date();
    log(jobId, `failed: ${err.stack || err.message}`);
  } finally {
    // Cleanup
    await cleanupAssets(jobId);
    if (outputPath) await cleanupOutput(outputPath);
    pendingInputs.delete(jobId);
    activeCount--;

    // Process next in queue
    processNext();
  }
}

function processNext(): void {
  while (activeCount < MAX_CONCURRENT && pendingQueue.length > 0) {
    const nextJobId = pendingQueue.shift()!;
    const input = pendingInputs.get(nextJobId);
    if (input) {
      processJob(nextJobId, input);
    }
  }
}

export function handleRender(req: Request, res: Response): void {
  const { valid, error, data } = validateRenderRequest(req.body);
  if (!valid || !data) {
    res.status(400).json({ error });
    return;
  }

  const { jobId, input } = data;

  // Idempotency: if job already exists, return current status
  const existing = jobs.get(jobId);
  if (existing) {
    res.status(200).json({ jobId, status: existing.status });
    return;
  }

  // Create job
  const job: Job = {
    id: jobId,
    status: "queued",
    progress: 0,
  };
  jobs.set(jobId, job);
  pendingInputs.set(jobId, input);

  if (activeCount < MAX_CONCURRENT) {
    processJob(jobId, input);
    res.status(202).json({ jobId, status: "rendering" });
  } else {
    pendingQueue.push(jobId);
    res.status(202).json({ jobId, status: "queued" });
  }
}

export function handleStatus(req: Request, res: Response): void {
  const { jobId } = req.params;
  const job = jobs.get(jobId);
  if (!job) {
    res.status(404).json({ error: "Job not found" });
    return;
  }

  res.json({
    jobId: job.id,
    status: job.status,
    progress: job.progress,
    outputUrl: job.outputUrl,
    error: job.error,
    startedAt: job.startedAt?.toISOString(),
    completedAt: job.completedAt?.toISOString(),
  });
}

export function handleHealth(_req: Request, res: Response): void {
  const currentJob = Array.from(jobs.values()).find((j) => j.status === "rendering");
  res.json({
    status: activeCount > 0 ? "busy" : "ready",
    currentJob: currentJob?.id || null,
    queueLength: pendingQueue.length,
    totalJobs: jobs.size,
  });
}
