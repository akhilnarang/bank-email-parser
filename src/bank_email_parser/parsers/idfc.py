"""IDFC FIRST Bank email parsers.

Supported email types:
- idfc_account_alert: Savings account credit/debit alert (RTGS/NEFT/IMPS)
- idfc_cc_debit_alert: Credit card spend alert
"""
import re
from datetime import datetime

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import parse_amount


def _parse_idfc_date(date_str: str) -> datetime | None:
    """Parse IDFC date strings.

    Handles:
      - '29-08-2025 20:37:48' (DD-MM-YYYY HH:MM:SS)
      - '16 MAR 2026' (DD MMM YYYY, uppercase month)

    Normalizes month abbreviations to title case before parsing so that
    uppercase months like 'MAR' work on strict-locale platforms where
    ``strptime %b`` expects 'Mar'.
    """
    cleaned = date_str.strip()
    # Normalize uppercase month abbreviations (e.g. "16 MAR 2026" -> "16 Mar 2026")
    # so that %b works correctly on strict locale platforms.
    parts = cleaned.split()
    if len(parts) >= 2 and parts[1].isalpha():
        parts[1] = parts[1].title()
        cleaned = " ".join(parts)
    for fmt in ("%d-%m-%Y %H:%M:%S", "%d-%m-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


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
        txn_dt = _parse_idfc_date(date_time_str)

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
        txn_dt = _parse_idfc_date(match.group("date"))

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


_PARSERS = (
    IdfcAccountAlertParser(),
    IdfcCcDebitAlertParser(),
)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("idfc", html, _PARSERS)
