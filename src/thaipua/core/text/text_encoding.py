"""Text-file codec detection (byte-order marks and content sniffing)."""

from pathlib import Path


def detect_text_encoding(file_path: str | Path) -> str:
    """Detect a file's encoding from its BOM, falling back to UTF-8 validity, then cp1252."""
    raw = Path(file_path).read_bytes()
    if raw.startswith(b"\xff\xfe\x00\x00"):
        return "utf-32-le"
    if raw.startswith(b"\x00\x00\xfe\xff"):
        return "utf-32-be"
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return "cp1252"
    return "utf-8"
