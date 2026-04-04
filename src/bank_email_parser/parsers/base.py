"""Base parser class and fallback-chain dispatcher for bank email parsers."""
from abc import ABC, abstractmethod
from collections.abc import Sequence

from bs4 import BeautifulSoup

from bank_email_parser.exceptions import ParseError, ParserStubError
from bank_email_parser.models import ParsedEmail
from bank_email_parser.utils import normalize_whitespace


class BaseEmailParser(ABC):
    bank: str
    email_type: str

    @staticmethod
    def prepare_html(html: str) -> tuple[BeautifulSoup, str]:
        """Parse HTML once and return both soup and normalized plain text."""
        soup = BeautifulSoup(html, "html.parser")
        text = normalize_whitespace(soup.get_text(separator=" ", strip=True))
        return soup, text

    @abstractmethod
    def parse(self, html: str) -> ParsedEmail:
        """Parse an HTML email body into a structured ParsedEmail."""
        ...


def parse_with_parsers(
    bank: str,
    html: str,
    parsers: Sequence[BaseEmailParser],
) -> ParsedEmail:
    """Try each parser in order until one succeeds."""
    errors: list[str] = []
    for parser in parsers:
        try:
            return parser.parse(html)
        except (ParseError, ParserStubError) as exc:
            errors.append(f"{parser.email_type}: {type(exc).__name__}")

    raise ParseError(
        f"No parser for bank {bank!r} could handle this email. "
        f"Tried: {', '.join(p.email_type for p in parsers)}. "
        f"Errors: {'; '.join(errors)}"
    )
