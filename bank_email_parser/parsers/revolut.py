"""Revolut India email parsers.

Supported email types:
- revolut_pocket_topup: Pocket (prepaid wallet) top-up from a bank account.
  Revolut sends no SMS for a top-up, so this email is the only record.
"""

import re

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BankParser, BaseEmailParser
from bank_email_parser.parsing.amounts import parse_amount
from bank_email_parser.parsing.dates import parse_datetime

_AMT = r"(?:₹|INR|Rs\.?)\s*(?P<{name}>[\d,]+(?:\.\d+)?)"


class RevolutPocketTopupParser(BaseEmailParser):
    """Revolut Pocket top-up confirmation.

    Matches the 'Your Pocket has been credited successfully' email body:
      'Transaction date: 4 September 2026 9:15 AM IST'
      'Amount credited: ₹500'
      'Your current Pocket balance is ₹750.'

    The email names no payer and gives no reference. The post-top-up balance
    tells two top-ups of the same amount apart.
    """

    bank = "revolut"
    email_type = "revolut_pocket_topup"

    _date_re = re.compile(
        r"Transaction\s+date:?\s*"
        r"(?P<when>\d{1,2}\s+[A-Za-z]+\s+\d{4},?\s+\d{1,2}:\d{2}\s*[AP]M)"
        r"(?:\s*IST)?",
        re.IGNORECASE,
    )
    _amount_re = re.compile(
        r"Amount\s+credited:?\s*" + _AMT.format(name="amount"), re.IGNORECASE
    )
    _balance_re = re.compile(
        r"current\s+Pocket\s+balance\s+is\s*" + _AMT.format(name="balance"),
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        """Parse a Pocket top-up email into a credit transaction."""
        _, text = self.prepare_html(html)
        lowered = text.lower()
        if "revolut" not in lowered or (
            "pocket has been credited" not in lowered
            and "money has been added to your pocket" not in lowered
        ):
            raise ParseError("Not a Revolut Pocket top-up email.")

        if not (amount_match := self._amount_re.search(text)):
            raise ParseError("Could not find the Revolut top-up amount.")
        if (amount := parse_amount(amount_match.group("amount"))) is None:
            raise ParseError("Could not parse the Revolut top-up amount.")

        if not (date_match := self._date_re.search(text)):
            raise ParseError("Could not find the Revolut top-up date.")
        if (when := parse_datetime(date_match.group("when"))) is None:
            raise ParseError("Could not parse the Revolut top-up date.")

        balance = None
        if (balance_match := self._balance_re.search(text)) and (
            balance_amount := parse_amount(balance_match.group("balance"))
        ) is not None:
            balance = Money(amount=balance_amount, currency="INR")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount, currency="INR"),
                transaction_date=when.date(),
                transaction_time=when.time(),
                balance=balance,
                raw_description=amount_match.group(0),
            ),
        )


_PARSERS = (RevolutPocketTopupParser(),)


def parse(html: str) -> ParsedEmail:
    """Parse a Revolut email through the bank dispatcher."""
    return RevolutParser().parse(html)


class RevolutParser(BankParser):
    """Dispatch a Revolut email to the matching parser."""

    bank = "revolut"
    parsers = _PARSERS
