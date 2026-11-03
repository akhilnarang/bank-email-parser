"""YES BANK email parsers.

Supported email types:
- yesbank_cc_debit_alert: Credit card spend/debit alert
- yesbank_account_credit_alert: Savings account credit alert (cheque deposit and other credits)
- yesbank_account_debit_alert: Savings account debit alert (cheque, RTGS and other debits)
- yesbank_account_rtgs_completed_alert: RTGS settlement completion for an outward RTGS debit
"""

import re
from typing import ClassVar, Literal, NamedTuple

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BankParser, BaseEmailParser
from bank_email_parser.parsing import (
    parse_amount,
    parse_date,
    parse_datetime,
    parse_money,
)

_CHEQUE_NARRATION_RE = re.compile(r"^CHQ\b", re.IGNORECASE)
_RTGS_NARRATION_RE = re.compile(
    r"^RTGS:(?P<ref>[A-Z0-9]{8,})/(?P<name>.+)$", re.IGNORECASE
)
_HONORIFIC_RE = re.compile(r"^(?:Mr|Mrs|Ms|Miss|Dr|M/s)\.?\s+", re.IGNORECASE)


class _NarrationFields(NamedTuple):
    """Transaction fields that the account alert narration gives."""

    counterparty: str | None
    channel: str | None
    reference: str | None


def _split_narration(narration: str) -> _NarrationFields:
    """Split an account alert narration into the transaction fields.

    Args:
        narration: Narration text from the alert.

    Returns:
        The counterparty, channel and reference of the narration.
    """
    if match := _RTGS_NARRATION_RE.match(narration):
        name = _HONORIFIC_RE.sub("", match.group("name")).strip()
        return _NarrationFields(
            counterparty=name, channel="rtgs", reference=match.group("ref")
        )
    if _CHEQUE_NARRATION_RE.search(narration):
        return _NarrationFields(
            counterparty=narration, channel="cheque", reference=None
        )
    return _NarrationFields(counterparty=narration, channel=None, reference=None)


def _account_alert_pattern(verb: str) -> re.Pattern[str]:
    """Build the pattern for an account alert with the given verb.

    Args:
        verb: Past participle of the action, such as "debited".

    Returns:
        The compiled pattern for the account alert.
    """
    return re.compile(
        r"An amount of INR\s+(?P<amount>\.\d{1,2}|[\d,]+(?:\.\d{1,2})?)\s+"
        rf"has been {verb} (?:to|from) your\s+A/C\.?\s*No\.?\s*(?P<account>[\w*]+)\s+"
        r"on\s+(?P<date>\d{1,2}-[A-Za-z]{3}-\d{2,4})(?:\s+(?P<time>\d{2}:\d{2}:\d{2}))?\s+"
        r"on account of\s+(?P<narration>.+?)\.?(?=\s+Available Balance|\s+For any clarifications|\s+This service|\s*$)",
        re.IGNORECASE | re.DOTALL,
    )


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


class _YesbankAccountAlertParser(BaseEmailParser):
    """Shared parser for the YES BANK account credit and debit alerts."""

    _direction: ClassVar[Literal["debit", "credit"]]
    _pattern: ClassVar[re.Pattern[str]]
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
        """Parse a YES BANK account alert email.

        Args:
            html: Raw HTML string of the email.

        Returns:
            ParsedEmail with the account TransactionAlert.

        Raises:
            ParseError: If the email does not match the account alert format.
        """
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse YES BANK account alert.")

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
        fields = _split_narration(narration)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction=self._direction,
                amount=Money(amount=amount),
                transaction_date=txn_date,
                transaction_time=txn_time,
                counterparty=fields.counterparty,
                account_mask=match.group("account").strip(),
                balance=self._parse_balance(text),
                channel=fields.channel,
                reference_number=fields.reference,
                raw_description=match.group(0).strip(),
            ),
        )


class YesbankAccountCreditAlertParser(_YesbankAccountAlertParser):
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
    _direction = "credit"
    _pattern = _account_alert_pattern("credited")


class YesbankAccountDebitAlertParser(_YesbankAccountAlertParser):
    """YES BANK account debit alert.

    Matches emails like:
      'An amount of INR 12,345.00 has been debited to your A/C. No. XX0000
       on 21-AUG-2026 10:20:30 on account of RTGS:YESBR9999010100000000/Mr JANE DOE
       Available Balance on 21-AUG-26 is INR 23,456.78 and Total available
       balance (including linked deposits and Limit) is INR 23,456.78.'
    """

    bank = "yesbank"
    email_type = "yesbank_account_debit_alert"
    _direction = "debit"
    _pattern = _account_alert_pattern("debited")


class YesbankAccountRtgsCompletedParser(BaseEmailParser):
    """YES BANK RTGS settlement completion alert.

    This email reports the settlement of an outward RTGS debit. It has
    ``ledger_role="completion"``, ``direction="debit"`` and
    ``channel="rtgs"``. It gives no ``account_mask`` and no ``counterparty``
    because the email names only the beneficiary account.

    Matches emails like:
      'RTGS Transaction with reference number YESBR9999010100000000 for
       INR 12,345.00 has been credited to the beneficiary account number
       XXXXXXX9999 on 21-08-2026 at 10:20:30.'
    """

    bank = "yesbank"
    email_type = "yesbank_account_rtgs_completed_alert"

    _pattern = re.compile(
        r"RTGS\s+Transaction\s+with\s+reference\s+number\s+(?P<ref>(?=[A-Z0-9]{8,})[A-Z]*[0-9][A-Z0-9]*)\s+"
        r"for\s+INR\s+(?P<amount>[\d,]+(?:\.\d{1,2})?)\s+has\s+been\s+credited\s+to\s+the\s+beneficiary\s+"
        r"account\s+number\s+(?P<account>\w+)\s+on\s+(?P<date>\d{2}-\d{2}-\d{4})\s+at\s+(?P<time>\d{2}:\d{2}:\d{2})",
        re.IGNORECASE | re.DOTALL,
    )

    def parse(self, html: str) -> ParsedEmail:
        """Parse a YES BANK RTGS completion alert email.

        Args:
            html: Raw HTML string of the email.

        Returns:
            ParsedEmail with the completion TransactionAlert.

        Raises:
            ParseError: If the email does not match the RTGS completion format.
        """
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse YES BANK RTGS completion alert.")

        if (amount := parse_money(match.group("amount"), "INR")) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        date_str = match.group("date")
        time_str = match.group("time")
        txn_time = None
        if dt := parse_datetime(f"{date_str} {time_str}"):
            txn_date = dt.date()
            txn_time = dt.time()
        else:
            txn_date = parse_date(date_str)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            ledger_role="completion",
            transaction=TransactionAlert(
                direction="debit",
                amount=amount,
                transaction_date=txn_date,
                transaction_time=txn_time,
                reference_number=match.group("ref"),
                channel="rtgs",
                raw_description=(
                    f"beneficiary_account={match.group('account')} "
                    f"{match.group(0).strip()}"
                ),
            ),
        )


_PARSERS = (
    YesbankCcDebitAlertParser(),
    YesbankAccountCreditAlertParser(),
    YesbankAccountDebitAlertParser(),
    YesbankAccountRtgsCompletedParser(),
)


def parse(html: str) -> ParsedEmail:
    return YesbankParser().parse(html)


class YesbankParser(BankParser):
    bank = "yesbank"
    parsers = _PARSERS
