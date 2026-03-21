import pytest
from orchestrator.line.validators import validate_name, validate_company, validate_phone, validate_line_id


class TestValidateName:
    def test_valid_chinese(self):
        assert validate_name("王小明") == "王小明"

    def test_valid_with_dot(self):
        assert validate_name("乃木·希典") == "乃木·希典"

    def test_trim_whitespace(self):
        assert validate_name("  王小明  ") == "王小明"

    def test_empty(self):
        assert validate_name("") is None

    def test_too_long(self):
        assert validate_name("a" * 21) is None

    def test_invalid_chars(self):
        assert validate_name("王123!@#") is None


class TestValidateCompany:
    def test_valid(self):
        assert validate_company("信義房屋") == "信義房屋"

    def test_valid_with_parens(self):
        assert validate_company("永慶房屋（台北）") == "永慶房屋（台北）"

    def test_too_long(self):
        assert validate_company("a" * 31) is None


class TestValidatePhone:
    def test_valid(self):
        assert validate_phone("0912345678") == "0912345678"

    def test_with_dashes(self):
        assert validate_phone("0912-345-678") == "0912345678"

    def test_with_spaces(self):
        assert validate_phone("0912 345 678") == "0912345678"

    def test_invalid_prefix(self):
        assert validate_phone("0812345678") is None

    def test_too_short(self):
        assert validate_phone("091234") is None


class TestValidateLineId:
    def test_valid(self):
        assert validate_line_id("wang.ming") == "wang.ming"

    def test_uppercase_normalized(self):
        assert validate_line_id("Wang.Ming") == "wang.ming"

    def test_skip_keyword(self):
        assert validate_line_id("跳過") == "SKIP"

    def test_skip_keyword_alt(self):
        assert validate_line_id("略過") == "SKIP"

    def test_invalid_chars(self):
        assert validate_line_id("wang@ming") is None

    def test_too_long(self):
        assert validate_line_id("a" * 21) is None
