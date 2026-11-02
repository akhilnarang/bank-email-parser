"""HTML text and simple table extraction helpers."""

import re
from collections.abc import Set

from bs4 import BeautifulSoup

from bank_email_parser.parsing.keys import normalize_key

_WHITESPACE = re.compile(r"\s+")


def extract_table_pairs(
    soup: BeautifulSoup,
    expected_keys: Set[str] | None = None,
) -> dict[str, str]:
    """Extract key-value pairs from 2-column table rows in HTML."""
    data: dict[str, str] = {}
    for row in soup.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) != 2:
            continue
        key = normalize_key(cells[0].get_text(strip=True))
        value = cells[1].get_text(strip=True)
        if not key or not value:
            continue
        if expected_keys is not None and key not in expected_keys:
            continue
        data[key] = value
    return data


def normalize_whitespace(text: str) -> str:
    """Collapse all whitespace to single spaces."""
    cleaned = text.replace("\xa0", " ").replace("\u200c", "")
    return _WHITESPACE.sub(" ", cleaned).strip()
