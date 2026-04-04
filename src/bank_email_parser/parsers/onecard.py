"""OneCard (BOBCARD One) email parsers.

Supported email types:
- onecard_debit_alert: Credit card purchase/spend alert (structured HTML with labeled fields)
"""
import re
from datetime import datetime

from bs4 import BeautifulSoup

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import normalize_whitespace, parse_amount


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
            dt_str = f"{date_str} {time_str}".strip() if time_str else date_str
            for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
                try:
                    dt = datetime.strptime(dt_str, fmt)
                    txn_date = dt.date()
                    txn_time = dt.time() if " " in fmt else None
                    break
                except ValueError:
                    continue

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


_PARSERS = (
    OnecardDebitAlertParser(),
)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("onecard", html, _PARSERS)
