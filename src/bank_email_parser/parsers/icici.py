"""ICICI Bank email parsers.

Supported email types:
- icici_cc_transaction_alert: Credit card purchase/spend alert
- icici_cc_upi_payment_alert: Credit card payment received via UPI
- icici_cc_payment_alert: Credit card payment received
- icici_bank_transfer_alert: Bank account IMPS/NEFT/RTGS transfer (debit)
- icici_net_banking_alert: Net banking payment (debit)
- icici_cc_reversal: Credit card merchant reversal/refund (credit back to card)
"""

import re

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import parse_amount, parse_date, parse_datetime


def _resolve_currency(raw: str) -> str:
    """Map currency prefix to ISO code. Any 3-letter uppercase code passes through."""
    cleaned = raw.strip().rstrip(".")
    if cleaned in ("Rs", "₹"):
        return "INR"
    # Accept any 3-letter uppercase code (ISO 4217)
    if re.fullmatch(r"[A-Z]{3}", cleaned):
        return cleaned
    return "INR"


# Shared currency pattern: any 3-letter uppercase code, or Rs./₹
_CUR = r"(?P<currency>[A-Z]{3}|Rs\.?|₹)"

# ICICI netbanking alerts append "hours" to 24h times ('23:02 hours'); dateutil
# doesn't understand that suffix, so strip it before parsing.
_HOURS_SUFFIX = re.compile(r"\s*hours\s*$", re.IGNORECASE)


def _parse_icici_datetime(date_str: str, time_str: str):
    """Combine ICICI date + time strings and hand to dateutil."""
    cleaned_time = _HOURS_SUFFIX.sub("", time_str.strip())
    return parse_datetime(f"{date_str.strip()} {cleaned_time}")


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

        transaction_date = _parse_icici_datetime(
            match.group("date"), match.group("time")
        )
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


class IciciCcUpiPaymentAlertParser(BaseEmailParser):
    """ICICI credit card payment received via UPI.

    Matches: 'Payment of INR <amount> towards ICICI Bank Credit Card <card>
    has been received through UPI on <date>.'
    """

    bank = "icici"
    email_type = "icici_cc_upi_payment_alert"

    _pattern = re.compile(
        r"Payment\s+of\s+"
        rf"{_CUR}\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"towards\s+ICICI\s+Bank\s+Credit\s+Card\s+(?P<card>\w+)\s+"
        r"has\s+been\s+received\s+through\s+(?P<channel>UPI|IMPS|NEFT|RTGS)\s+"
        r"on\s+(?P<date>.+?)\.",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse ICICI CC UPI payment alert.")

        currency = _resolve_currency(match.group("currency"))

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        transaction_date = parse_date(match.group("date"))

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount, currency=currency),
                transaction_date=transaction_date,
                card_mask=match.group("card"),
                counterparty="Payment received",
                channel=match.group("channel").lower(),
                raw_description=match.group(0).strip(),
            ),
        )


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
        transaction_date = parse_date(match.group("date"))

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

        transaction_date = _parse_icici_datetime(
            match.group("date"), match.group("time")
        )

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

        transaction_date = _parse_icici_datetime(
            match.group("date"), match.group("time")
        )

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


class IciciCcReversalParser(BaseEmailParser):
    """ICICI credit card merchant reversal/refund alert.

    Matches: 'We have received merchant credit refund on your ICICI Bank Credit Card
    XXXX for <currency> <amount> on <date> from <merchant>.'
    """

    bank = "icici"
    email_type = "icici_cc_reversal"

    _pattern = re.compile(
        r"We\s+have\s+received\s+merchant\s+credit\s+refund\s+"
        r"on\s+your\s+ICICI\s+Bank\s+Credit\s+Card\s+(?P<card>\w+)\s+"
        rf"for\s+{_CUR}\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"on\s+(?P<date>(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s*\d{4})\s+"
        r"from\s+(?P<counterparty>.+?)\.",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse ICICI CC reversal alert.")

        currency = _resolve_currency(match.group("currency"))

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        transaction_date = parse_date(match.group("date"))

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount, currency=currency),
                transaction_date=transaction_date,
                counterparty=match.group("counterparty").strip(),
                card_mask=match.group("card"),
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class IciciStatementEmailParser(BaseEmailParser):
    """ICICI account statement email — extracts password hint."""

    bank = "icici"
    email_type = "icici_account_statement"

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        text_lower = text.lower()
        has_statement = "statement" in text_lower and "icici" in text_lower
        has_attachment = (
            "password" in text_lower
            or "attached" in text_lower
            or "download" in text_lower
        )
        if not (has_statement and has_attachment):
            raise ParseError("Not an ICICI statement email")
        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            password_hint="First 4 letters of name (uppercase) + DDMM of birth",
        )


_PARSERS = (
    IciciCcTransactionAlertParser(),
    IciciCcUpiPaymentAlertParser(),
    IciciCcPaymentAlertParser(),
    IciciBankTransferAlertParser(),
    IciciNetBankingAlertParser(),
    IciciCcReversalParser(),
    IciciStatementEmailParser(),
)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("icici", html, _PARSERS)
