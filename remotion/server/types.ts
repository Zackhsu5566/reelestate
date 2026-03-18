// ── Server-side types for the render endpoint ──

export type JobStatus = "queued" | "rendering" | "completed" | "failed";

export interface Job {
  id: string;
  status: JobStatus;
  progress: number; // 0-100
  outputUrl?: string;
  error?: string;
  startedAt?: Date;
  completedAt?: Date;
}

// Caption type matching @remotion/captions (redefined to avoid importing React dep)
export interface CaptionItem {
  text: string;
  startMs: number;
  endMs: number;
  timestampMs: number | null;
  confidence: number | null;
}

// Scene types matching src/types.ts but with URLs instead of local paths
export interface OpeningScene {
  type: "opening";
  durationInFrames: number;
}

export interface ClipScene {
  type: "clip";
  src: string; // R2 URL or local path
  label: string;
  durationInFrames: number;
  stagingImage?: string; // R2 URL or local path
}

export interface KenBurnsScene {
  type: "ken_burns";
  src: string;
  label: string;
  durationInFrames: number;
  stagingImage?: string;
}

export interface POI {
  name: string;
  category: string;
  distance: string;
}

export interface OpeningSceneExt {
  type: "opening";
  durationInFrames: number;
  exteriorPhoto?: string;
  pois?: POI[];
}

export interface StatsScene {
  type: "stats";
  durationInFrames: number;
  backgroundSrc?: string;
}

export interface CTAScene {
  type: "cta";
  durationInFrames: number;
  backgroundSrc?: string;
}

export type SceneInput = OpeningScene | OpeningSceneExt | ClipScene | KenBurnsScene | StatsScene | CTAScene;

export interface RenderInput {
  title: string;
  location: string;
  address: string;
  size: string;
  layout: string;
  floor: string;
  price: string;
  contact: string;
  agentName: string;
  scenes: SceneInput[];
  narration: string; // URL
  bgm?: string; // URL
  captions: CaptionItem[];
  // Map / OpeningScene fields (optional)
  community?: string;
  propertyType?: string;
  buildingAge?: string;
  mapboxToken?: string;
  lat?: number;
  lng?: number;
  line?: string;
}

/** Redact sensitive fields for logging */
export function sanitizeForLog(input: RenderInput): Record<string, unknown> {
  const copy: Record<string, unknown> = { ...input };
  if (copy.mapboxToken) copy.mapboxToken = "***";
  return copy;
}

export interface RenderRequest {
  jobId: string;
  input: RenderInput;
}

export function validateRenderRequest(body: unknown): {
  valid: boolean;
  error?: string;
  data?: RenderRequest;
} {
  if (!body || typeof body !== "object") {
    return { valid: false, error: "Request body must be a JSON object" };
  }

  const b = body as Record<string, unknown>;

  if (!b.jobId || typeof b.jobId !== "string") {
    return { valid: false, error: "jobId is required and must be a string" };
  }

  if (!b.input || typeof b.input !== "object") {
    return { valid: false, error: "input is required and must be an object" };
  }

  const input = b.input as Record<string, unknown>;

  // Required fields
  for (const field of ["title", "narration"]) {
    if (!input[field] || typeof input[field] !== "string") {
      return {
        valid: false,
        error: `input.${field} is required and must be a string`,
      };
    }
  }

  // Optional string fields (allow empty string, null, or missing)
  for (const field of [
    "location",
    "address",
    "size",
    "layout",
    "floor",
    "price",
    "contact",
    "agentName",
  ]) {
    if (input[field] !== undefined && input[field] !== null && typeof input[field] !== "string") {
      return {
        valid: false,
        error: `input.${field} must be a string if provided`,
      };
    }
  }

  if (!Array.isArray(input.scenes) || input.scenes.length === 0) {
    return { valid: false, error: "input.scenes must be a non-empty array" };
  }

  for (let i = 0; i < input.scenes.length; i++) {
    const scene = input.scenes[i] as Record<string, unknown>;
    if (!scene.type) {
      return { valid: false, error: `scenes[${i}].type is required` };
    }
    if (!["opening", "clip", "ken_burns", "stats", "cta"].includes(scene.type as string)) {
      return { valid: false, error: `scenes[${i}].type "${scene.type}" is invalid` };
    }
    if (typeof scene.durationInFrames !== "number" || scene.durationInFrames <= 0) {
      return { valid: false, error: `scenes[${i}].durationInFrames must be a positive number` };
    }
    if (scene.type === "clip" || scene.type === "ken_burns") {
      if (!scene.src || typeof scene.src !== "string") {
        return { valid: false, error: `scenes[${i}].src is required for clip scenes` };
      }
      if (!scene.label || typeof scene.label !== "string") {
        return { valid: false, error: `scenes[${i}].label is required for clip scenes` };
      }
    }
  }

  if (!Array.isArray(input.captions)) {
    return { valid: false, error: "input.captions must be an array" };
  }

  return { valid: true, data: body as RenderRequest };
}
