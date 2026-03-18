"""Anthropic SDK Agent: SKILL.md as system prompt + vision."""

from __future__ import annotations

import json
import re
from pathlib import Path

import anthropic

from orchestrator.config import settings
from orchestrator.models import AgentResult, SpaceInput

SKILL_PATH = Path(__file__).resolve().parents[2] / "agent" / "SKILL.md"


def _load_system_prompt() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _strip_code_fence(text: str) -> str:
    """Remove markdown code fences (```json ... ```) from agent response."""
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*\n(.*?)```\s*$", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _build_user_content(
    raw_text: str,
    spaces: list[SpaceInput],
    premium: bool,
) -> list[dict]:
    """Build user message content blocks: JSON text only (no images)."""
    input_json = {
        "raw_text": raw_text,
        "spaces": [{"label": s.label, "photos": s.photos} for s in spaces],
        "premium": premium,
    }
    return [{"type": "text", "text": json.dumps(input_json, ensure_ascii=False)}]


class AgentService:
    MAX_PARSE_RETRIES = 2

    async def analyze(
        self,
        raw_text: str,
        spaces: list[SpaceInput],
        premium: bool,
    ) -> AgentResult:
        """Call Claude with SKILL.md system prompt and photos, return AgentResult."""
        system_prompt = _load_system_prompt()
        user_content = _build_user_content(raw_text, spaces, premium)

        client_kwargs = {"api_key": settings.anthropic_api_key}
        if settings.anthropic_base_url:
            client_kwargs["base_url"] = settings.anthropic_base_url
        client = anthropic.AsyncAnthropic(**client_kwargs)
        messages = [{"role": "user", "content": user_content}]

        for attempt in range(1 + self.MAX_PARSE_RETRIES):
            message = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
            )

            # Extract text from response (skip ThinkingBlock from models like MiniMax M2.5)
            raw = next(
                (b.text for b in message.content if hasattr(b, "text") and b.type == "text"),
                message.content[-1].text if message.content else "",
            )
            cleaned = _strip_code_fence(raw)

            try:
                return AgentResult.model_validate_json(cleaned)
            except Exception:
                if attempt >= self.MAX_PARSE_RETRIES:
                    raise
                # Retry as multi-turn: append assistant response + user follow-up
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": (
                    "你的回覆無法解析為有效 JSON。請重新輸出純 JSON，不要包裹在 code block 中。"
                )})

        raise RuntimeError("Agent parse retries exhausted")


agent_service = AgentService()
