from __future__ import annotations

import re

_NAME_PATTERN = re.compile(r"^[\u4e00-\u9fff\u3400-\u4dbfa-zA-Z\s·]+$")
_COMPANY_PATTERN = re.compile(r"^[\u4e00-\u9fff\u3400-\u4dbfa-zA-Z\s·（）()\-、]+$")
_PHONE_PATTERN = re.compile(r"^09\d{8}$")
_LINE_ID_PATTERN = re.compile(r"^[a-z0-9._-]+$")

_SKIP_KEYWORDS = {"跳過", "略過"}


def validate_name(text: str) -> str | None:
    """驗證姓名：中英文、空白、中間點，最多 20 字。"""
    text = text.strip()
    if not text or len(text) > 20:
        return None
    if not _NAME_PATTERN.match(text):
        return None
    return text


def validate_company(text: str) -> str | None:
    """驗證公司名稱：中英文、括號、頓號等，最多 30 字。"""
    text = text.strip()
    if not text or len(text) > 30:
        return None
    if not _COMPANY_PATTERN.match(text):
        return None
    return text


def validate_phone(text: str) -> str | None:
    """驗證台灣手機號碼（09 開頭 10 碼），自動移除空白和破折號。"""
    normalized = re.sub(r"[\s\-]", "", text.strip())
    if not _PHONE_PATTERN.match(normalized):
        return None
    return normalized


def validate_line_id(text: str) -> str | None:
    """驗證 LINE ID，支援「跳過/略過」回傳 SKIP，自動轉小寫，最多 20 字。"""
    text = text.strip()
    if text in _SKIP_KEYWORDS:
        return "SKIP"
    text = text.lower()
    if not text or len(text) > 20:
        return None
    if not _LINE_ID_PATTERN.match(text):
        return None
    return text
