"""OneCard (BOBCARD One) email parsers.

Supported email types:
- onecard_cc_statement: Monthly credit card statement email (summary-only, no PDF)
- onecard_debit_alert: Credit card purchase/spend alert (structured HTML with labeled fields)
"""

import re

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import (
    Money,
    ParsedEmail,
    StatementSummary,
    TransactionAlert,
)
from bank_email_parser.parsers.base import BankParser, BaseEmailParser
from bank_email_parser.parsing.amounts import parse_amount
from bank_email_parser.parsing.dates import parse_date, parse_datetime


class OnecardDebitAlertParser(BaseEmailParser):
    """OneCard / BOBCARD credit card transaction alert.

    Matches structured HTML with labeled fields:
      'Your BOBCARD One Credit Card ending in 1234 was used to make a payment.'
      Amount: INR  500.00
      Merchant: SAMPLE MERCHANT
      Date: 15/01/2026
      Time: 10:30:00
    """

    bank = "onecard"
    email_type = "onecard_debit_alert"

    _card_pattern = re.compile(
        r"(?:BOBCARD|OneCard).+?ending\s+in\s+(?P<card>\d{4})",
        re.IGNORECASE,
    )

    _fields_pattern = re.compile(
        r"Amount:\s*(?P<currency>INR|Rs\.?|₹|[A-Z]{3})\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r".*?Merchant:\s*(?P<merchant>.+?)\s+Date:\s*(?P<date>\d{2}/\d{2}/\d{4})\s+"
        r".*?Time:\s*(?P<time>\d{2}:\d{2}:\d{2})",
        re.DOTALL,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        # Extract card mask from intro line
        card_mask = None
        if m := self._card_pattern.search(text):
            card_mask = m.group("card")

        # Extract all fields via a single regex on the normalized text
        fm = self._fields_pattern.search(text)
        if not fm:
            raise ParseError("Could not find transaction fields in OneCard email.")

        # Amount
        amount = parse_amount(fm.group("amount"))
        if amount is None:
            raise ParseError(f"Could not parse amount: {fm.group('amount')!r}")

        # Currency
        raw_currency = fm.group("currency").strip()
        if raw_currency in ("Rs", "Rs.", "₹"):
            currency = "INR"
        else:
            currency = raw_currency

        # Merchant / counterparty
        counterparty = fm.group("merchant").strip() or None

        # Date and time
        date_str = fm.group("date")
        time_str = fm.group("time")

        txn_date = None
        txn_time = None
        if date_str:
            if dt := parse_datetime(f"{date_str} {time_str}"):
                txn_date = dt.date()
                txn_time = dt.time()
            else:
                txn_date = parse_date(date_str)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount, currency=currency),
                transaction_date=txn_date,
                transaction_time=txn_time,
                counterparty=counterparty,
                card_mask=card_mask,
                channel="card",
                raw_description=fm.group(0).strip(),
            ),
        )


class OnecardCcStatementParser(BaseEmailParser):
    """OneCard / BOBCARD monthly credit card statement (summary-only, no PDF).

    The email body carries the total due, minimum due, and payment due date as
    three parallel columns. No card mask or statement period is surfaced in the
    body, so those fields remain ``None``.
    """

    bank = "onecard"
    email_type = "onecard_cc_statement"

    # Marker: tolerates "e-statement" / "estatement" / "statement", arbitrary
    # whitespace, an optional adjective before the month, any month+year. The
    # brand-prefix + "credit card" + "statement for ... <year>" combination is
    # specific enough to avoid debit alerts, welcomes, or promos.
    _marker_pattern = re.compile(
        r"BOBCARD\s+One\s+Credit\s+Card\s+(?:e[-\s]?)?statement\s+for\s+"
        r"(?:\w+\s+){1,3}\d{4}",
        re.IGNORECASE,
    )
    # Amount/date rows: labels optionally followed by `:` and any whitespace.
    _total_pattern = re.compile(
        r"Total\s+amount\s+due\s*:?\s*(?P<amount>(?:₹|Rs\.?|INR)?\s*[\d,]+\.\d{2})",
        re.IGNORECASE,
    )
    _minimum_pattern = re.compile(
        r"Minimum\s+amount\s+due\s*:?\s*(?P<amount>(?:₹|Rs\.?|INR)?\s*[\d,]+\.\d{2})",
        re.IGNORECASE,
    )
    _due_date_pattern = re.compile(
        r"Payment\s+due\s+date\s*:?\s*(?P<date>\d{1,2}\s+\w+,?\s+\d{4})",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not self._marker_pattern.search(text):
            raise ParseError("Not a OneCard credit card statement email.")

        total_match = self._total_pattern.search(text)
        due_date_match = self._due_date_pattern.search(text)
        if not total_match or not due_date_match:
            raise ParseError(
                "Could not extract total amount due / due date from OneCard statement."
            )

        total_amount = parse_amount(total_match.group("amount"))
        if total_amount is None:
            raise ParseError(
                f"Could not parse total amount: {total_match.group('amount')!r}"
            )

        minimum_amount = None
        if minimum_match := self._minimum_pattern.search(text):
            minimum_amount = parse_amount(minimum_match.group("amount"))

        due_date = parse_date(due_date_match.group("date"))
        if due_date is None:
            raise ParseError(
                f"Could not parse due date: {due_date_match.group('date')!r}"
            )

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            statement=StatementSummary(
                total_amount_due=Money(amount=total_amount, currency="INR"),
                minimum_amount_due=(
                    Money(amount=minimum_amount, currency="INR")
                    if minimum_amount is not None
                    else None
                ),
                due_date=due_date,
                raw_description=text[:500],
            ),
        )


_PARSERS = (
    OnecardCcStatementParser(),
    OnecardDebitAlertParser(),
)


def parse(html: str) -> ParsedEmail:
    return OnecardParser().parse(html)


class OnecardParser(BankParser):
    bank = "onecard"
    parsers = _PARSERS
