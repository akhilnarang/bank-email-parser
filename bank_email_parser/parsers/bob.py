"""BOBCARD (Bank of Baroda) email parsers.

Supported email types:
- bob_cc_transaction_alert: BOBCARD credit card spend alert
"""

import re

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BankParser, BaseEmailParser
from bank_email_parser.parsing import parse_amount, parse_date


class BobCcTransactionAlertParser(BaseEmailParser):
    """BOBCARD credit card spend alert.

    Matches alerts like:
      'Thank you for using your BOBCARD **0000 for a transaction of
       INR 1,000.00 at samplestore on 30-09-2026. Following this transaction,
       the available balance on your card is Rs 99,000.00, ...'
    """

    bank = "bob"
    email_type = "bob_cc_transaction_alert"

    _pattern = re.compile(
        r"using\s+your\s+BOBCARD\s+\**(?P<card>\d{4})\s+for\s+a\s+transaction\s+of\s+"
        r"INR\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+at\s+(?P<merchant>.+?)\s+"
        r"on\s+(?P<date>\d{2}-\d{2}-\d{4})\.\s+"
        r"Following\s+this\s+transaction,\s+the\s+available\s+balance\s+on\s+your\s+"
        r"card\s+is\s+Rs\.?\s*(?P<balance>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse BOBCARD transaction alert.")

        amount = parse_amount(match.group("amount"))
        balance = parse_amount(match.group("balance"))
        transaction_date = parse_date(match.group("date"))
        if amount is None or balance is None or transaction_date is None:
            raise ParseError("BOBCARD transaction alert has an unreadable field.")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount, currency="INR"),
                transaction_date=transaction_date,
                counterparty=match.group("merchant").strip(),
                balance=Money(amount=balance, currency="INR"),
                card_mask=match.group("card"),
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


_PARSERS = (BobCcTransactionAlertParser(),)


class BobParser(BankParser):
    bank = "bob"
    parsers = _PARSERS


def parse(html: str) -> ParsedEmail:
    return BobParser().parse(html)
