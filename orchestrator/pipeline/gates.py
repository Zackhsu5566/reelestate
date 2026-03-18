"""Gate callback handling: script / audio / preview approval."""

from __future__ import annotations

import asyncio
import logging

from orchestrator.models import JobStatus
from orchestrator.pipeline.jobs import pipeline_runner
from orchestrator.pipeline.state import store

logger = logging.getLogger(__name__)

# Gate → expected current status
GATE_STATUS_MAP = {
    "preview": JobStatus.gate_preview,
}

# Gate → next status after approval
GATE_NEXT_STATUS = {
    "preview": JobStatus.delivering,
}


async def handle_gate_callback(
    job_id: str, gate: str, approved: bool, feedback: str | None = None
) -> dict:
    """Process a gate callback. Returns status dict."""
    if gate not in GATE_STATUS_MAP:
        return {"ok": False, "error": f"Unknown gate: {gate}"}

    # Idempotency lock
    if not await store.try_acquire_gate_lock(job_id, gate):
        return {"ok": False, "error": "Gate callback already being processed"}

    try:
        state = await store.get(job_id)
        if state is None:
            return {"ok": False, "error": "Job not found"}

        expected = GATE_STATUS_MAP[gate]
        if state.status != expected:
            return {
                "ok": False,
                "error": f"Job is in {state.status.value}, expected {expected.value}",
            }

        if not approved:
            # Rejection: record feedback, keep current status
            if feedback:
                await store.append_error(job_id, f"Gate {gate} rejected: {feedback}")
            # Release lock so re-approval is possible after changes
            await store.release_gate_lock(job_id, gate)
            return {"ok": True, "action": "rejected", "gate": gate}

        # Approval: advance to next status and resume pipeline
        next_status = GATE_NEXT_STATUS[gate]
        await store.set_status(job_id, next_status)
        await store.release_gate_lock(job_id, gate)

        # Resume pipeline in background
        asyncio.create_task(pipeline_runner(job_id))

        return {"ok": True, "action": "approved", "gate": gate}

    except Exception as e:
        await store.release_gate_lock(job_id, gate)
        logger.exception(f"Gate callback error for {job_id}/{gate}")
        return {"ok": False, "error": str(e)}
