"""IDFC FIRST Bank email parsers.

Supported email types:
- idfc_account_alert: Savings account credit/debit alert (RTGS/NEFT/IMPS)
- idfc_cc_debit_alert: Credit card spend alert
- idfc_cc_credit_alert: Credit card payment received alert
- idfc_account_neft_beneficiary_credit_alert: NEFT beneficiary-received
  confirmation for an outward transfer
"""

import re

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BankParser, BaseEmailParser
from bank_email_parser.utils import parse_amount, parse_date, parse_datetime


class IdfcAccountAlertParser(BaseEmailParser):
    """IDFC FIRST Bank savings account credit/debit alert (RTGS/NEFT/IMPS).

    Matches:
      Credit: 'Your A/C XXXXXXX1234 has been credited with INR 50,000.00
               on 15-01-2026 10:30:00 vide RTGS payment reference ... received from ...'
      Debit:  'Your A/C XXXXXXX1234 has been debited by INR 25,000.00
               on 15-01-2026 11:00:00 vide RTGS payment reference ... paid to ...'
    """

    bank = "idfc"
    email_type = "idfc_account_alert"

    _pattern = re.compile(
        r"Your A/C (?P<account>\S+) has been (?P<direction>credited with|debited by) "
        r"INR\s*(?P<amount>[\d,]+\.\d{2}) on "
        r"(?P<date>\d{2}-\d{2}-\d{4})\s+(?P<time>\d{2}:\d{2}:\d{2}) "
        r"vide (?P<channel>\w+) payment reference (?P<ref>\S+) "
        r"(?:received from|paid to) (?P<counterparty>.+?)\.\s*(?=New balance|$)",
    )

    _balance_pattern = re.compile(
        r"New balance is INR\s*(?P<balance>[\d,]+\.\d{2})",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse IDFC account alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        direction_raw = match.group("direction")
        direction = "credit" if direction_raw == "credited with" else "debit"

        date_time_str = f"{match.group('date')} {match.group('time')}"
        # Intentionally tolerating None here: date format changes shouldn't
        # block the entire parse.  transaction_date will be None downstream.
        txn_dt = parse_datetime(date_time_str)

        balance = None
        if bal_match := self._balance_pattern.search(text):
            if (bal_amount := parse_amount(bal_match.group("balance"))) is not None:
                balance = Money(amount=bal_amount)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction=direction,
                amount=Money(amount=amount),
                transaction_date=txn_dt.date() if txn_dt else None,
                transaction_time=txn_dt.time() if txn_dt else None,
                counterparty=match.group("counterparty").strip(),
                account_mask=match.group("account"),
                reference_number=match.group("ref"),
                channel=match.group("channel").lower(),
                balance=balance,
                raw_description=match.group(0).strip(),
            ),
        )


class IdfcCcDebitAlertParser(BaseEmailParser):
    """IDFC FIRST Bank credit card debit alert.

    Matches:
      'INR 100.00 spent on your IDFC FIRST BANK Credit Card ending XX1234
       at SAMPLE MERCHANT on 15 JAN 2026.'
    """

    bank = "idfc"
    email_type = "idfc_cc_debit_alert"

    _pattern = re.compile(
        r"INR\s*(?P<amount>[\d,.]+)\s+"
        r"spent on your IDFC FIRST BANK Credit Card ending (?P<card>\S+) "
        r"at (?P<merchant>.+?) on (?P<date>\d{1,2}\s+[A-Z]{3}\s+\d{4})",
    )

    _limit_pattern = re.compile(
        r"Available Limit:\s*INR\s*(?P<limit>[\d,.]+)",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse IDFC CC debit alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        # Intentionally tolerating None: date format changes shouldn't
        # block the entire parse.  transaction_date will be None downstream.
        txn_dt = parse_datetime(match.group("date"))

        balance = None
        if lim_match := self._limit_pattern.search(text):
            if (lim_amount := parse_amount(lim_match.group("limit"))) is not None:
                balance = Money(amount=lim_amount)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=txn_dt.date() if txn_dt else None,
                counterparty=match.group("merchant").strip(),
                card_mask=match.group("card"),  # no time in CC debit alerts
                channel="card",
                balance=balance,
                raw_description=match.group(0).strip(),
            ),
        )


class IdfcCcCreditAlertParser(BaseEmailParser):
    """IDFC FIRST Bank credit card payment received alert.

    Matches:
      'Payment of Rs. 1,234.56 was received on your FIRST Wealth Credit Card
       ending with XX1234 on 15 May 2099.'
    """

    bank = "idfc"
    email_type = "idfc_cc_credit_alert"
    # You pay your own card bill, so this alert names no merchant. The
    # card mask shows which payment it reports.
    identifies_by = "card_mask"

    _pattern = re.compile(
        r"Payment\s+of\s+(?:Rs\.?|INR|₹)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"was\s+received\s+on\s+your\s+"
        r"(?:IDFC\s+FIRST\s+BANK\s+|FIRST\s+\w+\s+)?Credit\s+Card\s+"
        r"ending\s+with\s+(?P<card>\S+)\s+"
        r"on\s+(?P<date>\d{1,2}\s+\w+\s+\d{4})\.",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse IDFC CC credit alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        txn_dt = parse_datetime(match.group("date"))

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount),
                transaction_date=txn_dt.date() if txn_dt else None,
                counterparty="Payment received",
                card_mask=match.group("card"),
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class IdfcNeftBeneficiaryCreditParser(BaseEmailParser):
    """IDFC FIRST Bank NEFT beneficiary-received confirmation.

    Matches:
      'Your beneficiary BENEFICIARY NAME has received ₹12,345.00 on
       15-01-2026 transferred via NEFT UTR IDFB0000X0000000.'

    The email counterpart of the bank's SMS confirmation that a NEFT the
    user **initiated** reached the beneficiary — it is NOT a credit to the
    user's own account. ``direction="debit"`` because the event describes
    money leaving the user (the same outflow as the NEFT debit alert,
    here confirmed from the beneficiary's side); modelling it as a credit
    would falsely imply the user received funds. The body carries no
    account mask or balance; the beneficiary name is the counterparty and
    the UTR is the reference, so the consumer can dedupe against the
    matching NEFT debit by UTR. The shared
    ``idfc_account_neft_beneficiary_credit_alert`` email_type keeps the
    SMS and email confirmations of the same transfer on one event name.
    """

    bank = "idfc"
    email_type = "idfc_account_neft_beneficiary_credit_alert"

    _pattern = re.compile(
        r"Your\s+beneficiary\s+(?P<name>.+?)\s+has\s+received\s+"
        r"(?:₹|Rs\.?\s*|INR\s+)(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"on\s+(?P<date>\d{2}-\d{2}-\d{4})\s+"
        r"transferred\s+via\s+NEFT\s+UTR\s+(?P<ref>[A-Z0-9]+)",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse IDFC NEFT beneficiary-received alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        # The date is a mandatory field of this shape; a value the regex
        # accepted but the calendar rejects (e.g. 31-02) must fail loudly
        # rather than silently drop a body-provided date.
        if (txn_date := parse_date(match.group("date"))) is None:
            raise ParseError(f"Could not parse date: {match.group('date')!r}")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                counterparty=match.group("name").strip(),
                reference_number=match.group("ref"),
                channel="neft",
                raw_description=match.group(0).strip(),
            ),
        )


class IdfcStatementEmailParser(BaseEmailParser):
    """IDFC account statement email."""

    bank = "idfc"
    email_type = "idfc_account_statement"

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        if "statement" not in text.lower() or "password" not in text.lower():
            raise ParseError("Not an IDFC statement email")
        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            password_hint="Date of birth in DDMMYYYY format",
        )


_PARSERS = (
    IdfcAccountAlertParser(),
    IdfcCcDebitAlertParser(),
    IdfcCcCreditAlertParser(),
    # NEFT beneficiary-received confirmation: unique "Your beneficiary ...
    # has received ... via NEFT UTR ..." anchor; cannot collide with the
    # account or CC shapes.
    IdfcNeftBeneficiaryCreditParser(),
    IdfcStatementEmailParser(),
)


def parse(html: str) -> ParsedEmail:
    return IdfcParser().parse(html)


class IdfcParser(BankParser):
    bank = "idfc"
    parsers = _PARSERS
