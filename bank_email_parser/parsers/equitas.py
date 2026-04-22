"""Equitas Small Finance Bank email parsers.

Supported email types:
- equitas_cc_alert: Credit card transaction (spend) alert
- equitas_cc_statement: Credit card statement email with password hint
"""

import re
from decimal import Decimal

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BankParser, BaseEmailParser
from bank_email_parser.parsing.dates import parse_date, parse_datetime


def _clean_amount(raw: str) -> Decimal:
    """Strip commas from a regex-captured amount."""
    return Decimal(raw.replace(",", ""))


class EquitasCcAlertParser(BaseEmailParser):
    """Equitas Small Finance Bank credit card transaction alert.

    Matches plain-text alerts like:
      'We inform you that INR 1,500.00 was spent on your Equitas Credit Card
       ending with 1234 at SAMPLE STORE on 15-01-2026 at 02:23:51 pm.
       Your available balance is INR 50,000.00.'
    """

    bank = "equitas"
    email_type = "equitas_cc_alert"

    _pattern = re.compile(
        r"We\s+inform\s+you\s+that\s+"
        r"(?P<currency>[A-Z]{3})\s*(?P<amount>[\d,]+\.\d{2})\s+"
        r"was\s+spent\s+on\s+your\s+Equitas\s+Credit\s+Card\s+"
        r"ending\s+with\s+(?P<card>\d{4})\s+"
        r"at\s+(?P<merchant>.+?)\s+"
        r"on\s+(?P<date>\d{2}-\d{2}-\d{4})\s+"
        r"at\s+(?P<time>\d{2}:\d{2}:\d{2}\s*[ap]m)\.\s*"
        r"Your\s+available\s+balance\s+is\s+"
        r"(?:INR|Rs\.?)\s*(?P<balance>[\d,]+\.\d{2})",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse Equitas credit card alert.")

        currency = match.group("currency").upper()
        amount = _clean_amount(match.group("amount"))
        card_mask = match.group("card")
        merchant = match.group("merchant").strip()
        transaction_time = None
        if dt := parse_datetime(f"{match.group('date')} {match.group('time')}"):
            transaction_date = dt.date()
            transaction_time = dt.time()
        else:
            transaction_date = parse_date(match.group("date"))
        balance = Money(
            amount=_clean_amount(match.group("balance")),
            currency="INR",
        )

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount, currency=currency),
                transaction_date=transaction_date,
                transaction_time=transaction_time,
                counterparty=merchant,
                balance=balance,
                card_mask=card_mask,
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class EquitasCcStatementParser(BaseEmailParser):
    """Equitas Small Finance Bank credit card statement email."""

    bank = "equitas"
    email_type = "equitas_cc_statement"

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        text_lower = text.lower()

        has_brand_anchor = (
            "equitas small finance bank" in text_lower
            and "equitas credit card" in text_lower
        )
        has_statement_marker = (
            "credit card e-statement" in text_lower
            or "credit card statement" in text_lower
        )
        has_password_marker = (
            "open your e-statement with the password" in text_lower
            or (
                "password" in text_lower
                and "adobe acrobat pdf" in text_lower
                and "date of birth in ddmm format" in text_lower
            )
        )

        if not (has_brand_anchor and has_statement_marker and has_password_marker):
            raise ParseError("Not an Equitas credit card statement email.")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            password_hint="First 4 letters of name in UPPER CASE (no spaces) + DDMM of birth",
        )


_PARSERS = (EquitasCcAlertParser(), EquitasCcStatementParser())


def parse(html: str) -> ParsedEmail:
    return EquitasParser().parse(html)


class EquitasParser(BankParser):
    bank = "equitas"
    parsers = _PARSERS
