"""Union Bank of India (UBoI) email parsers.

Supported email types:
- uboi_debit_alert: Account debit alert (IMPS/NEFT/RTGS), parsed from structured
  HTML with a 'Transaction Details' heading and a <ul><li> list.
"""
from bs4 import BeautifulSoup

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import parse_amount


class UboiDebitAlertParser(BaseEmailParser):
    """Union Bank of India debit alert (IMPS/NEFT/RTGS).

    Matches structured HTML with <h3>Transaction Details:</h3> followed by
    a <ul><li> list where each item uses ' - ' as the label/value delimiter.
    """

    bank = "uboi"
    email_type = "uboi_debit_alert"

    _FIELD_MAP = {
        "Payee Name": "counterparty",
        "Amount": "amount",
        "Transfer Type": "channel",
        "Bank Ref. No.": "reference",
        "Debited From": "account_mask",
    }

    def parse(self, html: str) -> ParsedEmail:
        soup, _ = self.prepare_html(html)

        # Locate the <h3>Transaction Details:</h3> heading
        heading = None
        for h3 in soup.find_all("h3"):
            if "transaction details" in h3.get_text(strip=True).lower():
                heading = h3
                break
        if heading is None:
            raise ParseError(
                "Could not find 'Transaction Details' heading in UBOI email."
            )

        # Extract key-value pairs from <li> elements
        ul = heading.find_next_sibling("ul")
        if ul is None:
            raise ParseError("Could not find <ul> after Transaction Details heading.")

        data: dict[str, str] = {}
        for li in ul.find_all("li"):
            text = li.get_text(strip=False).strip()
            parts = text.split(" - ", maxsplit=1)
            if len(parts) == 2:
                key, value = parts[0].strip(), parts[1].strip()
                if value and value.lower() != "null":
                    data[key] = value

        # Amount (required)
        raw_amount = data.get("Amount")
        if raw_amount is None:
            raise ParseError("Amount not found in UBOI transaction details.")

        amount = parse_amount(raw_amount)
        if amount is None:
            raise ParseError(f"Could not parse amount: {raw_amount!r}")

        # Account mask: last 4 digits
        account_mask = None
        if raw_account := data.get("Debited From"):
            account_mask = raw_account[-4:]

        # Build raw description from all list items
        raw_parts = [li.get_text(strip=False).strip() for li in ul.find_all("li")]
        raw_description = "; ".join(raw_parts)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=None,
                counterparty=data.get("Payee Name"),
                account_mask=account_mask,
                reference_number=data.get("Bank Ref. No."),
                channel=data.get("Transfer Type", "").lower() or None,
                balance=None,
                raw_description=raw_description,
            ),
        )


_PARSERS = (
    UboiDebitAlertParser(),
)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("uboi", html, _PARSERS)
