"""Axis Bank email parsers.

Supported email types:
- axis_cc_debit_alert: Credit card debit (spend) alert, parsed from label/value div layout
- axis_neft_alert: NEFT transfer alert (stub -- awaiting sample email)
"""
import re
from decimal import Decimal

from bs4 import BeautifulSoup

from bank_email_parser.exceptions import ParseError, ParserStubError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import normalize_whitespace, parse_date

# CSS style fragments used to identify label vs value divs in the card layout
_LABEL_MARKER = "color:#777777"
_VALUE_MARKER = "color:#333333"

# Field key normalization: strip trailing colons, dots, asterisks, and whitespace
_KEY_CLEANUP = re.compile(r"[\s:.*]+$")

# Map normalized label text to internal field names
_FIELD_MAP = {
    "transaction amount": "amount",
    "merchant name": "merchant",
    "axis bank credit card no": "card_mask",
    "date & time": "date_time",
    "date &amp; time": "date_time",
    "available limit": "balance",
    "total credit limit": "total_limit",
}

# Amount pattern: optional currency prefix, then digits (no commas in observed emails,
# but handle them defensively)
_AMOUNT_RE = re.compile(r"([A-Z]{3})\s+([\d,]+(?:\.\d+)?)")


def _parse_money(raw: str) -> Money:
    """Parse 'INR 5830' or 'INR&nbsp;5830' into a Money object."""
    cleaned = normalize_whitespace(raw)
    if m := _AMOUNT_RE.search(cleaned):
        return Money(
            amount=Decimal(m.group(2).replace(",", "")),
            currency=m.group(1),
        )
    raise ParseError(f"Could not parse money from: {raw!r}")


def _normalize_label(raw: str) -> str:
    """Normalize a label div's text for lookup in _FIELD_MAP."""
    return _KEY_CLEANUP.sub("", raw.strip()).lower()


def _extract_label_value_pairs(soup: BeautifulSoup) -> dict[str, str]:
    """Extract label/value pairs from Axis card-layout divs.

    Labels have style containing color:#777777, values have color:#333333.
    Each label div is immediately followed by a value div.
    """
    pairs: dict[str, str] = {}

    label_divs = soup.find_all(
        "div", style=lambda s: s and _LABEL_MARKER in s,
    )

    for label_div in label_divs:
        label_text = label_div.get_text(strip=True)
        normalized = _normalize_label(label_text)

        if normalized not in _FIELD_MAP:
            continue

        # Only accept the immediate next sibling if it's a value div
        next_el = label_div.find_next_sibling()
        if next_el and next_el.name == "div" and next_el.get("style") and _VALUE_MARKER in next_el.get("style", ""):
            pairs[_FIELD_MAP[normalized]] = next_el.get_text(strip=True)

    return pairs


class AxisCcDebitAlertParser(BaseEmailParser):
    """Axis Bank credit card debit (spend) alert.

    Parses the structured HTML card layout with label/value div pairs
    used in Axis CC transaction notification emails.
    """

    bank = "axis"
    email_type = "axis_cc_debit_alert"

    def parse(self, html: str) -> ParsedEmail:
        soup, _ = self.prepare_html(html)
        fields = _extract_label_value_pairs(soup)

        if not (amount_raw := fields.get("amount")):
            raise ParseError(
                "Could not find Transaction Amount in Axis CC debit alert."
            )

        amount = _parse_money(amount_raw)

        transaction_date = None
        if date_raw := fields.get("date_time"):
            # Format: '28-12-2025, 19:08:29 IST' -- extract just the date portion
            date_part = date_raw.split(",")[0].strip()
            transaction_date = parse_date(date_part)

        balance = None
        if balance_raw := fields.get("balance"):
            balance = _parse_money(balance_raw)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=amount,
                transaction_date=transaction_date,
                counterparty=fields.get("merchant"),
                balance=balance,
                card_mask=fields.get("card_mask"),
                channel="card",
                raw_description=f"Axis CC debit: {amount_raw} at {fields.get('merchant', 'unknown')}",
            ),
        )


class AxisNeftAlertParser(BaseEmailParser):
    """Axis Bank NEFT transfer alert.

    Subject: "NEFT is initiated from your account"

    TODO: No sample email available yet. Implement once a sample is obtained.
    Expected fields: amount, account_mask, counterparty, reference_number,
    transaction_date.
    """

    bank = "axis"
    email_type = "axis_neft_alert"

    def parse(self, html: str) -> ParsedEmail:
        raise ParserStubError(
            "Axis NEFT alert parser not yet implemented -- "
            "need a sample email to determine the exact format."
        )


_PARSERS = (
    AxisCcDebitAlertParser(),
    AxisNeftAlertParser(),
)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("axis", html, _PARSERS)
