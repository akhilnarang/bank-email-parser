"""HSBC Bank email parsers.

Supported email types:
- hsbc_cc_debit_alert: Credit card purchase/spend alert
- hsbc_cc_credit_alert: Credit card payment received
"""
import re
from datetime import datetime

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import parse_amount, parse_date


class HsbcCcDebitAlertParser(BaseEmailParser):
    """HSBC credit card purchase (debit) alert.

    Matches:
      'your Credit card no ending with 1234,has been used for INR 1500.00
       for payment to SAMPLE MERCHANT on 15 Jan 2026 at 10:30.'
    """

    bank = "hsbc"
    email_type = "hsbc_cc_debit_alert"

    _pattern = re.compile(
        r"Credit\s+card\s+no\s+ending\s+with\s+(?P<card>\d{4})\s*,?\s*"
        r"has\s+been\s+used\s+for\s+INR\s+(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"for\s+payment\s+to\s+(?P<merchant>.+?)\s+"
        r"on\s+(?P<date>\d{1,2}\s+\w{3}\s+\d{4})\s+"
        r"at\s+(?P<time>\d{2}:\d{2})\.",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse HSBC CC debit alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        date_str = match.group("date")
        time_str = match.group("time")
        txn_date = None
        txn_time = None
        for dt_str, fmt, has_time in (
            (f"{date_str} {time_str}", "%d %b %Y %H:%M", True),
            (date_str, "%d %b %Y", False),
        ):
            try:
                dt = datetime.strptime(dt_str, fmt)
                txn_date = dt.date()
                txn_time = dt.time() if has_time else None
                break
            except ValueError:
                continue

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                transaction_time=txn_time,
                counterparty=match.group("merchant").strip(),
                card_mask=match.group("card"),
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class HsbcCcCreditAlertParser(BaseEmailParser):
    """HSBC credit card payment received (credit) alert.

    Matches:
      'We have received credits of ₹ 5,000.00 on your HSBC credit card
       ending with 1234 on 15/01/2026.'
    """

    bank = "hsbc"
    email_type = "hsbc_cc_credit_alert"

    _pattern = re.compile(
        r"received\s+credits?\s+of\s+(?:₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"on\s+your\s+HSBC\s+credit\s+card\s+ending\s+with\s+(?P<card>\d{4})\s+"
        r"on\s+(?P<date>\d{2}/\d{2}/\d{4})\.",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse HSBC CC credit alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        txn_date = parse_date(match.group("date"))

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                counterparty="Payment received",
                card_mask=match.group("card"),
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


_PARSERS = (
    HsbcCcDebitAlertParser(),
    HsbcCcCreditAlertParser(),
)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("hsbc", html, _PARSERS)
