"""Public API: parse_email() entry point and SUPPORTED_BANKS registry."""

from importlib import import_module

from bank_email_parser.exceptions import ParseError, UnsupportedEmailTypeError
from bank_email_parser.models import ParsedEmail

SUPPORTED_BANKS = (
    "axis",
    "bom",
    "equitas",
    "hdfc",
    "hsbc",
    "icici",
    "idfc",
    "indusind",
    "kotak",
    "onecard",
    "sbi",
    "slice",
    "uboi",
)


def parse_email(bank: str, html: str) -> ParsedEmail:
    """Parse an HTML email body for a given bank.

    Dynamically imports the bank's parser module and calls its parse() function.
    Each bank module owns its own parser list and fallback ordering.

    Args:
        bank: Bank identifier (e.g. 'icici', 'slice', 'hdfc').
        html: The HTML body of the email.

    Returns:
        ParsedEmail with structured transaction data.

    Raises:
        UnsupportedEmailTypeError: If bank is not recognized.
        ParseError: If no parser could handle the email.
    """
    if not isinstance(bank, str):
        raise UnsupportedEmailTypeError(
            f"Expected 'bank' to be a string, got {type(bank).__name__}"
        )

    if not isinstance(html, str):
        raise ParseError(f"Expected 'html' to be a string, got {type(html).__name__}")

    bank = bank.strip().lower()

    if bank not in SUPPORTED_BANKS:
        raise UnsupportedEmailTypeError(
            f"Unknown bank: {bank!r}. Supported: {SUPPORTED_BANKS}"
        )

    if len(html) > 500_000:
        raise ParseError("Input HTML too large (>500KB).")

    module = import_module(f"bank_email_parser.parsers.{bank}")

    if not callable(parse := getattr(module, "parse", None)):
        raise ParseError(
            f"bank_email_parser.parsers.{bank!r} does not define parse(html)"
        )

    return parse(html)
