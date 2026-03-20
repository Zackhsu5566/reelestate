from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


# ── Job Status ──


class JobStatus(str, Enum):
    analyzing = "analyzing"
    generating = "generating"
    rendering = "rendering"
    gate_preview = "gate_preview"
    delivering = "delivering"
    done = "done"
    failed = "failed"


# ── Asset Task (sub-task tracking for crash recovery) ──


class AssetTask(BaseModel):
    status: str = "pending"  # pending | submitted | completed | failed
    remote_job_id: str | None = None
    output_url: str | None = None
    error: str | None = None


# ── POI (nearby points of interest) ──


class POIInfo(BaseModel):
    name: str
    category: str  # mrt | supermarket | park | school | hospital | other
    distance: str  # e.g. "步行3分鐘"
    source: str | None = None  # "extracted" | "inferred"
    lat: float | None = None
    lng: float | None = None


# ── Space (from Agent analysis) ──


class SpaceInfo(BaseModel):
    name: str  # 最終顯示名稱（可能已修正）
    original_label: str | None = None  # 原始 input label（pipeline 匹配用，不需修正時為 null）
    photo_count: int
    photos: list[str] = []  # R2 URLs
    needs_staging: bool = False
    staging_prompt: str | None = None


# ── Agent Meta ──


class AgentMeta(BaseModel):
    agent_version: str | None = None
    missing_fields: list[str] = []
    warnings: list[str] = []


# ── Agent Result ──


class AgentResult(BaseModel):
    property: PropertyInfo
    title: str
    narration: str
    spaces: list[SpaceInfo]
    meta: AgentMeta | None = None


class PropertyInfo(BaseModel):
    address: str | None = None
    location: str | None = None
    price: str | None = None
    size: str | None = None
    layout: str | None = None
    floor: str | None = None
    features: list[str] = []
    agent_name: str | None = None
    company: str | None = None
    phone: str | None = None
    line: str | None = None            # LINE ID
    pois: list[POIInfo] | None = None  # 生活機能 POI（座標由 Remotion geocoding 解析）
    community: str | None = None       # 社區名稱
    property_type: str | None = None   # 電梯大樓/透天/公寓
    building_age: str | None = None    # 屋齡


# ── Job State (stored in Redis) ──


class JobState(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.analyzing

    # Input
    raw_text: str = ""
    spaces_input: list[SpaceInput] = []
    premium: bool = False
    exterior_photo: str | None = None  # Building exterior photo URL (displayed in OpeningScene)
    line_user_id: str = ""

    # Agent output
    agent_result: AgentResult | None = None

    # Staging template
    staging_template: str | None = None

    # Asset tasks (crash-recoverable)
    asset_tasks: dict[str, AssetTask] = {}

    # Render
    preview_render_job_id: str | None = None
    preview_url: str | None = None
    thumbnail_url: str | None = None
    final_url: str | None = None

    # Errors
    errors: list[str] = []


class SpaceInput(BaseModel):
    label: str
    photos: list[str]  # R2 URLs
    is_small_space: bool = False  # Set by _preprocess_spaces when label ends with 's'


# ── API Request / Response ──


class CreateJobRequest(BaseModel):
    raw_text: str
    spaces: list[SpaceInput]
    premium: bool = False
    exterior_photo: str | None = None  # Building exterior photo URL
    staging_template: str | None = None
    line_user_id: str = ""


class GateCallbackRequest(BaseModel):
    approved: bool
    feedback: str | None = None
    gate: str  # "preview"


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    preview_url: str | None = None
    final_url: str | None = None
    errors: list[str] = []
