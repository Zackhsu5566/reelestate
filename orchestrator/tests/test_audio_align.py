"""Tests for orchestrator.services.audio_align."""

import pytest

from orchestrator.services.audio_align import split_by_markers


class TestSplitByMarkers:
    def test_standard_narration(self):
        text = (
            "[OPENING]\n"
            "今天帶你來看這間\n"
            "\n"
            "[客廳]\n"
            "一進門就是超大面落地窗\n"
            "\n"
            "[MAP]\n"
            "位置就在信義安和站旁邊\n"
            "\n"
            "[STATS]\n"
            "整屋三十五坪\n"
            "\n"
            "[CTA]\n"
            "售價兩千九百八十萬\n"
        )
        sections = split_by_markers(text)
        assert len(sections) == 5
        assert sections[0]["marker"] == "OPENING"
        assert "今天帶你來看這間" in sections[0]["text"]
        assert sections[1]["marker"] == "客廳"
        assert sections[3]["marker"] == "STATS"
        assert sections[4]["marker"] == "CTA"

    def test_multiple_spaces(self):
        text = (
            "[OPENING]\n開場白\n\n"
            "[客廳]\n客廳描述\n\n"
            "[主臥]\n主臥描述\n\n"
            "[MAP]\n地圖\n\n"
            "[STATS]\n規格\n\n"
            "[CTA]\n聯繫\n"
        )
        sections = split_by_markers(text)
        assert len(sections) == 6
        assert sections[2]["marker"] == "主臥"

    def test_strips_pause_markers(self):
        text = "[OPENING]\n今天<#1.0#>帶你來看\n"
        sections = split_by_markers(text)
        assert "<#1.0#>" in sections[0]["text"]

    def test_empty_section(self):
        text = "[OPENING]\n\n[MAP]\n地圖\n"
        sections = split_by_markers(text)
        assert len(sections) == 2
        assert sections[0]["marker"] == "OPENING"
        assert sections[0]["text"].strip() == ""

    def test_no_markers(self):
        text = "一段沒有 marker 的文字"
        sections = split_by_markers(text)
        assert len(sections) == 0
