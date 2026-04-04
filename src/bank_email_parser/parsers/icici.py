"""ICICI Bank email parsers.

Supported email types:
- icici_cc_transaction_alert: Credit card purchase/spend alert
- icici_cc_payment_alert: Credit card payment received
- icici_bank_transfer_alert: Bank account IMPS/NEFT/RTGS transfer (debit)
- icici_net_banking_alert: Net banking payment (debit)
- icici_cc_reversal: Credit card reversal/refund (stub -- awaiting sample email)
"""
import re
from datetime import datetime

from bs4 import BeautifulSoup

from bank_email_parser.exceptions import ParseError, ParserStubError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import normalize_whitespace, parse_amount


def _resolve_currency(raw: str) -> str:
    """Map currency prefix to ISO code. Any 3-letter uppercase code passes through."""
    cleaned = raw.strip().rstrip(".")
    if cleaned in ("Rs", "₹"):
        return "INR"
    # Accept any 3-letter uppercase code (ISO 4217)
    if re.fullmatch(r"[A-Z]{3}", cleaned):
        return cleaned
    return "INR"


def _parse_icici_time(time_str: str) -> str | None:
    """Normalize ICICI time formats to HH:MM:SS.

    Handles: '03:27:39', '09:23 p.m.', '09:15 p.m.', '23:02 hours'
    """
    cleaned = time_str.strip().lower().replace(".", "").replace(" ", "")
    # Try 24h format first: "03:27:39"
    if m := re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})", cleaned):
        return cleaned
    # 24h format without seconds: "23:02hours" or "23:02"
    if m := re.fullmatch(r"(\d{2}):(\d{2})(?:hours)?", cleaned):
        return f"{m.group(1)}:{m.group(2)}:00"
    # 12h format: "0923pm" or "09:23pm"
    if m := re.fullmatch(r"(\d{1,2}):?(\d{2})\s*(am|pm)", cleaned):
        try:
            return datetime.strptime(f"{m.group(1)}:{m.group(2)} {m.group(3).upper()}", "%I:%M %p").strftime("%H:%M:00")
        except ValueError:
            return None
    return None


# Shared currency pattern: any 3-letter uppercase code, or Rs./₹
_CUR = r"(?P<currency>[A-Z]{3}|Rs\.?|₹)"


class IciciCcTransactionAlertParser(BaseEmailParser):
    """ICICI credit card purchase/spend alert.

    Matches: 'Your ICICI Bank Credit Card XXXX has been used for a transaction of <currency> <amount>
    on <date> at <time>. Info: <merchant>.'
    """

    bank = "icici"
    email_type = "icici_cc_transaction_alert"

    _txn_pattern = re.compile(
        r"Your\s+ICICI\s+Bank\s+Credit\s+Card\s+(?P<card>\w+)\s+"
        r"has\s+been\s+used\s+for\s+a\s+transaction\s+of\s+"
        rf"{_CUR}\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"on\s+(?P<date>.+?)\s+at\s+(?P<time>\d{2}:\d{2}:\d{2})\.\s*"
        r"Info:\s*(?P<info>.+?)(?=\.\s+(?:The\s|In\s+case|Available\s)|\.?\s*$)",
    )

    _limit_pattern = re.compile(
        r"Available\s+Credit\s+Limit\s+on\s+your\s+card\s+is\s+"
        r"(?P<limit_currency>[A-Z]{3}|Rs\.?|₹)\s*(?P<available>[\d,]+(?:\.\d+)?)",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._txn_pattern.search(text)):
            raise ParseError("Could not parse ICICI CC transaction alert.")

        currency = _resolve_currency(match.group("currency"))

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        transaction_date = self._parse_datetime(match.group("date"), match.group("time"))
        counterparty = match.group("info").strip().rstrip(".")

        balance = None
        if limit_match := self._limit_pattern.search(text):
            if (avl := parse_amount(limit_match.group("available"))) is not None:
                limit_cur = _resolve_currency(limit_match.group("limit_currency"))
                balance = Money(amount=avl, currency=limit_cur)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount, currency=currency),
                transaction_date=transaction_date.date() if transaction_date else None,
                transaction_time=transaction_date.time() if transaction_date else None,
                counterparty=counterparty,
                balance=balance,
                card_mask=match.group("card"),
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )

    @staticmethod
    def _parse_datetime(date_str: str, time_str: str) -> datetime | None:
        combined = f"{date_str.strip()} {time_str.strip()}"
        for fmt in ("%b %d, %Y %H:%M:%S", "%b %d, %y %H:%M:%S", "%d-%b-%Y %H:%M:%S"):
            try:
                return datetime.strptime(combined, fmt)
            except ValueError:
                continue
        return None


class IciciCcPaymentAlertParser(BaseEmailParser):
    """ICICI credit card payment received alert.

    Matches: 'We have received payment of INR <amount> on your ICICI Bank Credit Card
    account <card> on <date>.'
    """

    bank = "icici"
    email_type = "icici_cc_payment_alert"

    _pattern = re.compile(
        r"We\s+have\s+received\s+payment\s+of\s+"
        rf"{_CUR}\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"on\s+your\s+ICICI\s+Bank\s+Credit\s+Card\s+account\s+"
        r"(?P<card>[\dX\s*]+?)\s+on\s+(?P<date>[\w\-,\s]+?)\.",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse ICICI CC payment alert.")

        currency = _resolve_currency(match.group("currency"))

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        card_mask = re.sub(r"\s+", " ", match.group("card").strip())
        transaction_date = self._parse_date(match.group("date").strip())

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount, currency=currency),
                transaction_date=transaction_date,
                card_mask=card_mask,
                counterparty="Payment received",
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )

    @staticmethod
    def _parse_date(date_str: str):
        from datetime import date as date_type

        for fmt in ("%d-%b-%Y", "%d-%b-%y", "%b %d, %Y", "%b %d,%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(date_str.strip(), fmt).date()
            except ValueError:
                continue
        return None


class IciciBankTransferAlertParser(BaseEmailParser):
    """ICICI bank account IMPS/NEFT transfer alert.

    Matches: 'You have made an online IMPS payment of Rs. <amount> towards <name>
    on <date> at <time> from your ICICI Bank Savings Account XXXX1234.
    The Transaction ID is <id>.'
    """

    bank = "icici"
    email_type = "icici_bank_transfer_alert"

    # Counterparty uses .+? but anchored via lookahead on "on <Month> " or "on <DD->"
    # to avoid truncating names containing the word "on"
    _pattern = re.compile(
        r"You\s+have\s+made\s+an\s+online\s+(?P<channel>IMPS|NEFT|RTGS)\s+"
        r"payment\s+of\s+"
        rf"{_CUR}\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"towards\s+(?P<counterparty>.+?)\s+"
        r"on\s+(?P<date>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s*\d{4}|\d{1,2}-\w{3}-\d{2,4})\s+"
        r"at\s+(?P<time>.+?)\s+"
        r"from\s+your\s+ICICI\s+Bank\s+\w+\s+Account\s+(?P<account>\w+)\.",
    )

    _txn_id_pattern = re.compile(
        r"Transaction\s+ID\s+is\s+(?P<txn_id>[\w\-]+)",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse ICICI bank transfer alert.")

        currency = _resolve_currency(match.group("currency"))

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        transaction_date = self._parse_datetime(match.group("date"), match.group("time"))

        reference_number = None
        if txn_match := self._txn_id_pattern.search(text):
            reference_number = txn_match.group("txn_id")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount, currency=currency),
                transaction_date=transaction_date.date() if transaction_date else None,
                transaction_time=transaction_date.time() if transaction_date else None,
                counterparty=match.group("counterparty").strip(),
                account_mask=match.group("account"),
                reference_number=reference_number,
                channel=match.group("channel").lower(),
                raw_description=match.group(0).strip(),
            ),
        )

    @staticmethod
    def _parse_datetime(date_str: str, time_str: str) -> datetime | None:
        normalized_time = _parse_icici_time(time_str)
        if not normalized_time:
            return None
        combined = f"{date_str.strip()} {normalized_time}"
        for fmt in ("%b %d, %Y %H:%M:%S", "%b %d, %y %H:%M:%S", "%d-%b-%Y %H:%M:%S", "%d-%b-%y %H:%M:%S", "%b %d, %Y %H:%M:00", "%b %d, %y %H:%M:00"):
            try:
                return datetime.strptime(combined, fmt)
            except ValueError:
                continue
        return None


class IciciNetBankingAlertParser(BaseEmailParser):
    """ICICI net banking payment alert.

    Matches: 'You have made an online payment of INR <amount> towards <merchant>
    from your Account XX214 on <date> at <time> hours. The Transaction ID is <id>.'
    """

    bank = "icici"
    email_type = "icici_net_banking_alert"

    _pattern = re.compile(
        r"You\s+have\s+made\s+an\s+online\s+payment\s+of\s+"
        rf"{_CUR}\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"towards\s+(?P<counterparty>.+?)\s+"
        r"from\s+your\s+Account\s+(?P<account>\w+)\s+"
        r"on\s+(?P<date>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s*\d{4}|\d{1,2}-\w{3}-\d{2,4})\s+"
        r"at\s+(?P<time>.+?)\s+hours\.",
    )

    _txn_id_pattern = re.compile(
        r"Transaction\s+ID\s+is\s+(?P<txn_id>[\w\-]+)",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse ICICI net banking alert.")

        currency = _resolve_currency(match.group("currency"))

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        time_with_suffix = f"{match.group('time')} hours"
        transaction_date = self._parse_datetime(match.group("date"), time_with_suffix)

        reference_number = None
        if txn_match := self._txn_id_pattern.search(text):
            reference_number = txn_match.group("txn_id")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount, currency=currency),
                transaction_date=transaction_date.date() if transaction_date else None,
                transaction_time=transaction_date.time() if transaction_date else None,
                counterparty=match.group("counterparty").strip(),
                account_mask=match.group("account"),
                reference_number=reference_number,
                channel="netbanking",
                raw_description=match.group(0).strip(),
            ),
        )

    @staticmethod
    def _parse_datetime(date_str: str, time_str: str) -> datetime | None:
        normalized_time = _parse_icici_time(time_str)
        if not normalized_time:
            return None
        combined = f"{date_str.strip()} {normalized_time}"
        for fmt in ("%b %d, %Y %H:%M:%S", "%b %d, %y %H:%M:%S", "%d-%b-%Y %H:%M:%S", "%d-%b-%y %H:%M:%S", "%b %d, %Y %H:%M:00", "%b %d, %y %H:%M:00"):
            try:
                return datetime.strptime(combined, fmt)
            except ValueError:
                continue
        return None


class IciciCcReversalParser(BaseEmailParser):
    """ICICI credit card reversal/refund alert.

    From: credit_cards@icicibank.com
    Subject: "Reversal processed on your ICICI Bank Credit Card XX1234"

    TODO: No sample email available yet. Implement once a sample is obtained.
    Expected pattern: reversal of <currency> <amount> on card <card_mask>
    with transaction date and reference number.
    """

    bank = "icici"
    email_type = "icici_cc_reversal"

    def parse(self, html: str) -> ParsedEmail:
        raise ParserStubError(
            "ICICI CC reversal parser not yet implemented -- "
            "need a sample email to determine the exact format."
        )


_PARSERS = (
    IciciCcTransactionAlertParser(),
    IciciCcPaymentAlertParser(),
    IciciBankTransferAlertParser(),
    IciciNetBankingAlertParser(),
    IciciCcReversalParser(),
)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("icici", html, _PARSERS)
