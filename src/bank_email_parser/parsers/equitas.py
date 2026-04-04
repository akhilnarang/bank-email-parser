"""Equitas Small Finance Bank email parsers.

Supported email types:
- equitas_cc_alert: Credit card transaction (spend) alert
"""
import re
from datetime import datetime
from decimal import Decimal

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import parse_date


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
        transaction_date = parse_date(match.group("date"))
        transaction_time = None
        try:
            transaction_dt = datetime.strptime(
                f"{match.group('date')} {match.group('time').upper()}",
                "%d-%m-%Y %I:%M:%S %p",
            )
        except ValueError:
            transaction_dt = None
        if transaction_dt is not None:
            transaction_date = transaction_dt.date()
            transaction_time = transaction_dt.time()
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


_PARSERS = (EquitasCcAlertParser(),)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("equitas", html, _PARSERS)
