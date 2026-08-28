"""HSBC Bank email parsers.

Supported email types:
- hsbc_cc_debit_alert: Credit card purchase/spend alert
- hsbc_cc_credit_alert: Credit card payment received
- hsbc_cc_transaction_alert: Credit card purchase alert, 2026 wording
"""

import re

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BankParser, BaseEmailParser
from bank_email_parser.utils import parse_amount, parse_date, parse_datetime


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

        txn_time = None
        if dt := parse_datetime(f"{match.group('date')} {match.group('time')}"):
            txn_date = dt.date()
            txn_time = dt.time()
        else:
            # Fall back to date-only when the time is malformed, so a bad time
            # doesn't cause us to drop the date too.
            txn_date = parse_date(match.group("date"))

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


class HsbcCcTransactionAlertParser(BaseEmailParser):
    """HSBC credit card purchase alert, the wording in use from August 2026.

    Matches:
      'your HSBC Credit Card xx1234 was used for a transaction of INR 978.00
       at SAMPLE MERCHANT on 26/08/26.'

    The older alert names the card as 'ending with 1234' and carries a time.
    This one masks the card as 'xx1234', dates it DD/MM/YY, and has no time.
    """

    bank = "hsbc"
    email_type = "hsbc_cc_transaction_alert"

    _pattern = re.compile(
        r"your\s+HSBC\s+Credit\s+Card\s+[xX]+(?P<card>\d{4})\s+"
        r"was\s+used\s+for\s+a\s+transaction\s+of\s+"
        r"(?:INR|₹)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"at\s+(?P<merchant>.+?)\s+"
        # The period closes the sentence. Without it a merchant name holding a
        # date ("CAFE ON 01/02/26 ROAD") would end the match at the wrong date.
        r"on\s+(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\.",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse HSBC CC transaction alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        if (txn_date := parse_date(match.group("date"))) is None:
            raise ParseError(f"Could not parse date: {match.group('date')!r}")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                counterparty=match.group("merchant").strip(),
                card_mask=match.group("card"),
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


_PARSERS = (
    HsbcCcDebitAlertParser(),
    HsbcCcTransactionAlertParser(),
    HsbcCcCreditAlertParser(),
)


def parse(html: str) -> ParsedEmail:
    return HsbcParser().parse(html)


class HsbcParser(BankParser):
    bank = "hsbc"
    parsers = _PARSERS
