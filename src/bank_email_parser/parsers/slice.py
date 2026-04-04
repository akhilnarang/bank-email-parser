"""Slice (slice savings bank) email parsers.

Supported email types:
- slice_transaction_alert: UPI/IMPS/NEFT credit or debit alert ('received/sent via' pattern)
- slice_transfer_alert: IMPS/RTGS/NEFT debit alert ('transaction of ₹X from' pattern); skips 'initiated' emails
- slice_cc_payment_alert: Slice credit card bill repayment received
"""
import re
from decimal import Decimal
from decimal import InvalidOperation

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import (
    extract_table_pairs,
    parse_date,
)

# Amount pattern that handles zero-width non-joiner (\u200c) between digit groups
_AMT = r"[\d,\u200c]+(?:\.\d+)?"
# Account reference: "account xx0298", "a/c xx0298", "account ending XX0298"
_ACCT = r"(?:a/c|account(?:\s+ending)?)\s+(?P<account>[\w\-*]+)"

# All table keys we care about across Slice email types
_EXPECTED_TABLE_KEYS = {
    "transaction date", "date",
    "from", "to", "sender name",
    "beneficiary name", "beneficiary acc no", "beneficiary bank",
    "rrn", "imps ref no", "rtgs ref no",
}


def _clean_amount(raw: str) -> Decimal:
    """Strip commas and zero-width non-joiners from a regex-captured amount."""
    try:
        return Decimal(raw.replace(",", "").replace("\u200c", ""))
    except InvalidOperation:
        raise ParseError(f"Could not parse amount: {raw!r}")


class SliceTransactionAlertParser(BaseEmailParser):
    """Slice UPI/IMPS/NEFT credit/debit alerts using the 'received/sent via' pattern.

    Matches:
      'You have received ₹X via UPI in your slice bank account/a/c XXXX'
      'You have sent ₹X via UPI from your slice bank account/a/c XXXX'
    """

    bank = "slice"
    email_type = "slice_transaction_alert"

    _body_pattern = re.compile(
        r"You\s+have\s+(?P<direction>received|sent)\s+"
        rf"₹\s*(?P<amount>{_AMT})\s+"
        r"via\s+(?P<channel>\S+)\s+"
        rf"(?:in|from)\s+your\s+slice\s+(?:bank|savings)\s+{_ACCT}"
        r"(?:[.!]\s*Avl\.\s*Bal\.\s*₹\s*(?P<balance>[\d,\u200c]+(?:\.\d+)?))?"
    )

    def parse(self, html: str) -> ParsedEmail:
        soup, text = self.prepare_html(html)

        if not (match := self._body_pattern.search(text)):
            raise ParseError("Could not parse slice transaction alert body.")

        direction = "credit" if match.group("direction") == "received" else "debit"
        amount = _clean_amount(match.group("amount"))
        channel = match.group("channel").strip().lower()

        balance = None
        if bal_str := match.group("balance"):
            balance = Money(amount=_clean_amount(bal_str))

        table_data = extract_table_pairs(soup, expected_keys=_EXPECTED_TABLE_KEYS)

        transaction_date = None
        if date_str := (table_data.get("transaction date") or table_data.get("date")):
            transaction_date = parse_date(date_str)

        # Counterparty: "From"/"Sender Name" for credits, "To" for debits
        counterparty = (
            table_data.get("from") or table_data.get("sender name")
            if direction == "credit"
            else table_data.get("to") or table_data.get("beneficiary name")
        )

        reference_number = (
            table_data.get("rrn")
            or table_data.get("imps ref no")
            or table_data.get("rtgs ref no")
        )

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction=direction,
                amount=Money(amount=amount),
                transaction_date=transaction_date,
                counterparty=counterparty,
                balance=balance,
                reference_number=reference_number,
                account_mask=match.group("account"),
                channel=channel,
                raw_description=match.group(0).strip(),
            ),
        )


class SliceTransferAlertParser(BaseEmailParser):
    """Slice IMPS/RTGS debit alerts using the 'transaction of ₹X from' pattern.

    Matches:
      'IMPS transaction of ₹X from your slice bank a/c XXXX is successful!'
      'Your RTGS transaction of ₹X from your slice bank account ending XXXX has been completed successfully.'
    """

    bank = "slice"
    email_type = "slice_transfer_alert"

    _body_pattern = re.compile(
        r"(?:Your\s+)?(?P<channel>IMPS|RTGS|NEFT)\s+transaction\s+of\s+"
        rf"₹\s*(?P<amount>{_AMT})\s+"
        rf"from\s+your\s+slice\s+(?:bank|savings)\s+{_ACCT}",
        re.IGNORECASE,
    )

    # Pattern to detect "initiated" emails that should be skipped (the
    # "successful"/"completed" email will arrive separately).
    _initiated_pattern = re.compile(
        r"has\s+been\s+initiated", re.IGNORECASE,
    )
    _completed_pattern = re.compile(
        r"(?:is\s+successful|has\s+been\s+completed|successfully)", re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        soup, text = self.prepare_html(html)

        if not (match := self._body_pattern.search(text)):
            raise ParseError("Could not parse slice transfer alert body.")

        # Skip "initiated" emails to avoid duplicates -- the corresponding
        # "successful"/"completed" email will be parsed instead.
        if self._initiated_pattern.search(text) and not self._completed_pattern.search(text):
            raise ParseError("Skipping 'initiated' transfer email (not yet successful).")

        amount = _clean_amount(match.group("amount"))
        channel = match.group("channel").lower()

        table_data = extract_table_pairs(soup, expected_keys=_EXPECTED_TABLE_KEYS)

        transaction_date = None
        if date_str := (table_data.get("transaction date") or table_data.get("date")):
            transaction_date = parse_date(date_str)

        counterparty = table_data.get("beneficiary name")
        reference_number = (
            table_data.get("imps ref no")
            or table_data.get("rtgs ref no")
            or table_data.get("rrn")
        )

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=transaction_date,
                counterparty=counterparty,
                reference_number=reference_number,
                account_mask=match.group("account"),
                channel=channel,
                raw_description=match.group(0).strip(),
            ),
        )


class SliceCcPaymentAlertParser(BaseEmailParser):
    """Slice credit card bill payment received.

    Matches: 'We\u2019ve received your repayment of ₹X for the slice credit card.'
    """

    bank = "slice"
    email_type = "slice_cc_payment_alert"

    _pattern = re.compile(
        r"received\s+your\s+repayment\s+of\s+"
        rf"₹\s*(?P<amount>{_AMT})\s+"
        r"for\s+the\s+slice\s+credit\s+card",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse slice CC payment alert.")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=_clean_amount(match.group("amount"))),
                counterparty="Payment received",
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


_PARSERS = (
    SliceTransactionAlertParser(),
    SliceTransferAlertParser(),
    SliceCcPaymentAlertParser(),
)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("slice", html, _PARSERS)
