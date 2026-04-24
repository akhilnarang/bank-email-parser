"""bank_email_parser -- parse bank transaction alert emails into structured data."""

from bank_email_parser.api import SUPPORTED_BANKS, parse_email
from bank_email_parser.exceptions import ParseError, UnsupportedEmailTypeError
from bank_email_parser.models import (
    Money,
    ParsedEmail,
    StatementSummary,
    TransactionAlert,
)

__all__ = [
    "Money",
    "ParseError",
    "ParsedEmail",
    "StatementSummary",
    "SUPPORTED_BANKS",
    "TransactionAlert",
    "UnsupportedEmailTypeError",
    "parse_email",
]
