"""Bank of Maharashtra (bom) email parsers.

Supported email types:
- bom_upi_debit_alert: UPI debit alert ('Your A/c No xx XXXX debited by INR ... with UPI RRN')
"""

import re

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import parse_date, parse_money

# Numeric amount: digits with optional commas and 2 decimal places
_AMT = r"[\d,]+(?:\.\d{2})?"

# Account mask: "xx 0967", "XX1234", "x1234", "XXXX5678"
_ACCT = r"(?P<account>[\w\s]*?\d{4})"


class BomUpiDebitAlertParser(BaseEmailParser):
    """Bank of Maharashtra UPI debit alert.

    Matches:
      'Your A/c No xx 0967 debited by INR 10,363.00 on 28-MAR-2026
       with UPI RRN :379672273425. A/c Bal is INR 0.13 CR and AVL Bal is INR 0.13 CR'
    """

    bank = "bom"
    email_type = "bom_upi_debit_alert"

    _pattern = re.compile(
        r"Your\s+A/c\s+No\s+" + _ACCT + r"\s+debited\s+by\s+"
        r"INR\s*(?P<amount>" + _AMT + r")"
        r"\s+on\s+"
        r"(?P<date>\d{1,2}-[A-Za-z]{3}-\d{2,4})"
        r"\s+with\s+UPI\s+RRN\s*:\s*"
        r"(?P<rrn>\d+)"
        r"(?:\.\s*A/c\s+Bal\s+is\s+"
        r"INR\s*(?P<balance>" + _AMT + r")\s*CR"
        r")?"
    )

    def parse(self, html: str) -> ParsedEmail:
        soup, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse Bank of Maharashtra UPI debit alert.")

        amount = parse_money(match.group("amount"))
        if amount is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        transaction_date = parse_date(match.group("date"))

        balance = None
        if bal_str := match.group("balance"):
            balance = parse_money(bal_str)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=amount,
                transaction_date=transaction_date,
                balance=balance,
                reference_number=match.group("rrn"),
                account_mask=match.group("account").strip(),
                channel="upi",
                raw_description=match.group(0).strip(),
            ),
        )


_PARSERS = (BomUpiDebitAlertParser(),)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("bom", html, _PARSERS)
