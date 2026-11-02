"""YES BANK email parsers.

Supported email types:
- yesbank_cc_debit_alert: Credit card spend/debit alert
- yesbank_account_credit_alert: Savings account credit alert (cheque deposit and other credits)
"""

import re

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BankParser, BaseEmailParser
from bank_email_parser.parsing import parse_amount, parse_date, parse_datetime

_CHEQUE_NARRATION_RE = re.compile(r"^CHQ\b", re.IGNORECASE)


class YesbankCcDebitAlertParser(BaseEmailParser):
    """YES BANK Credit Card debit (spend) alert.

    Matches emails like:
      'INR 1,234.56 has been spent on your YES BANK Credit Card ending with 1234
       at SAMPLE MERCHANT on 01-01-2026 at 08:30:15 pm. Avl Bal INR 50,000.00.'
    """

    bank = "yesbank"
    email_type = "yesbank_cc_debit_alert"

    _pattern = re.compile(
        r"INR\s+(\.\d{1,2}|[\d,]+(?:\.\d{2})?)\s+has been spent on your YES BANK Credit Card ending with (\d{4})\s+"
        r"at (.+?) on (\d{2}-\d{2}-\d{4}) at (\d{2}:\d{2}:\d{2})\s*(am|pm)"
        r"(?:\.\s*Avl Bal\s+INR\s+([\d,]+(?:\.\d{2})?))?",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse YES BANK CC debit alert.")

        amount = parse_amount(match.group(1))
        if amount is None:
            raise ParseError(f"Could not parse amount: {match.group(1)!r}")

        card_mask = match.group(2)
        counterparty = match.group(3).strip() or None

        txn_time = None
        if dt := parse_datetime(f"{match.group(4)} {match.group(5)} {match.group(6)}"):
            txn_date = dt.date()
            txn_time = dt.time()
        else:
            txn_date = parse_date(match.group(4))

        # Available balance (optional)
        balance = None
        if match.group(7):
            bal_amount = parse_amount(match.group(7))
            if bal_amount is not None:
                balance = Money(amount=bal_amount)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                transaction_time=txn_time,
                counterparty=counterparty,
                card_mask=card_mask,
                channel="card",
                balance=balance,
                raw_description=match.group(0).strip(),
            ),
        )


class YesbankAccountCreditAlertParser(BaseEmailParser):
    """YES BANK account credit alert.

    Matches emails like:
      'An amount of INR 4,321.00 has been credited to your A/C. No. XX9999
       on 15-JAN-2026 09:15:45 on account of CHQ DEP TESTBANK 14-JAN-26
       TEST BRANCH JANE DOE. Available Balance on 15-JAN-26 is INR 8,765.43
       and Total available balance (including linked deposits and Limit) is
       INR 8,765.43.'
    """

    bank = "yesbank"
    email_type = "yesbank_account_credit_alert"

    _pattern = re.compile(
        r"An amount of INR\s+(?P<amount>\.\d{1,2}|[\d,]+(?:\.\d{1,2})?)\s+"
        r"has been credited to your\s+A/C\.?\s*No\.?\s*(?P<account>[\w*]+)\s+"
        r"on\s+(?P<date>\d{1,2}-[A-Za-z]{3}-\d{2,4})(?:\s+(?P<time>\d{2}:\d{2}:\d{2}))?\s+"
        r"on account of\s+(?P<narration>.+?)\.(?=\s+Available Balance|\s+This service|\s*$)",
        re.IGNORECASE,
    )
    _balance_pattern = re.compile(
        r"Available Balance on\s+\S+\s+is\s+INR\s+(?P<balance>[\d,]+(?:\.\d{1,2})?)\b",
        re.IGNORECASE,
    )

    def _parse_balance(self, text: str) -> Money | None:
        """Extract the available balance from the normalized email text.

        Args:
            text: Normalized email text.

        Returns:
            The available balance as Money, or None if not present.
        """
        if not (bal_match := self._balance_pattern.search(text)):
            return None
        if (bal_amount := parse_amount(bal_match.group("balance"))) is None:
            return None
        return Money(amount=bal_amount)

    def parse(self, html: str) -> ParsedEmail:
        """Parse a YES BANK account credit alert email.

        Args:
            html: Raw HTML string of the email.

        Returns:
            ParsedEmail with the credit TransactionAlert.

        Raises:
            ParseError: If the email does not match the account credit format.
        """
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse YES BANK account credit alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        date_str = match.group("date")
        time_str = match.group("time")
        txn_time = None
        if time_str and (dt := parse_datetime(f"{date_str} {time_str}")):
            txn_date = dt.date()
            txn_time = dt.time()
        else:
            txn_date = parse_date(date_str)

        narration = match.group("narration").strip()
        channel = "cheque" if _CHEQUE_NARRATION_RE.match(narration) else None

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                transaction_time=txn_time,
                counterparty=narration,
                account_mask=match.group("account"),
                channel=channel,
                balance=self._parse_balance(text),
                raw_description=match.group(0).strip(),
            ),
        )


_PARSERS = (
    YesbankCcDebitAlertParser(),
    YesbankAccountCreditAlertParser(),
)


def parse(html: str) -> ParsedEmail:
    return YesbankParser().parse(html)


class YesbankParser(BankParser):
    bank = "yesbank"
    parsers = _PARSERS
