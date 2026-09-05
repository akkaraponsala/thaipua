"""Domain constants for Thai-to-PUA encoding and composite glyph generation."""

from thaipua.core.domain.thai import CONSONANTS

PUA_RANGE_START: int = 0xE000
PUA_RANGE_END: int = 0xF8FF
STRING_TABLE_EXTENSIONS = {".ILSTRINGS", ".DLSTRINGS", ".STRINGS"}
SARA_AM_REPLACEMENTS: list[tuple[str, str]] = [("่ำ", "ํ่า"), ("้ำ", "ํ้า"), ("๊ำ", "ํ๊า"), ("๋ำ", "ํ๋า"), ("ำ", "ํา")]
THAI_CONSONANT_CHARS: str = "".join(chr(consonant.value) for consonant in CONSONANTS)
