"""Unit tests for text-file encoding detection from byte-order marks and content sniffing."""

from pathlib import Path

from thaipua.core.text.text_encoding import detect_text_encoding


def test_detects_utf32_le_bom(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"\xff\xfe\x00\x00" + "ก".encode("utf-32-le"))
    assert detect_text_encoding(path) == "utf-32-le"


def test_detects_utf32_be_bom(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"\x00\x00\xfe\xff" + "ก".encode("utf-32-be"))
    assert detect_text_encoding(path) == "utf-32-be"


def test_detects_utf16_le_bom(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"\xff\xfe" + "ก".encode("utf-16-le"))
    assert detect_text_encoding(path) == "utf-16-le"


def test_detects_utf16_be_bom(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"\xfe\xff" + "ก".encode("utf-16-be"))
    assert detect_text_encoding(path) == "utf-16-be"


def test_detects_utf8_sig_bom(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"\xef\xbb\xbfhello")
    assert detect_text_encoding(path) == "utf-8-sig"


def test_plain_utf8_content_has_no_bom(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("สวัสดี", encoding="utf-8")
    assert detect_text_encoding(path) == "utf-8"


def test_invalid_utf8_falls_back_to_cp1252(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"caf\xe9")
    assert detect_text_encoding(path) == "cp1252"
