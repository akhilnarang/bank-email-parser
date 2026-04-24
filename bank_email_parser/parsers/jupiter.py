"""Jupiter (Federal Bank-backed neobank) email parsers.

Supported email types:
- jupiter_upi_debit_alert: Outbound UPI payment confirmation sent from
  alerts@jupiter.money with headline 'Your UPI payment was successful'.
- jupiter_statement: Edge CSB Bank RuPay Credit Card statement email with a
  password-protected PDF attachment.
"""

from bs4 import BeautifulSoup

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BankParser, BaseEmailParser
from bank_email_parser.parsing.amounts import parse_amount
from bank_email_parser.parsing.dates import parse_date
from bank_email_parser.parsing.keys import normalize_key


class JupiterUpiDebitAlertParser(BaseEmailParser):
    """Jupiter outbound UPI payment alert.

    Matches the 'Your UPI payment was successful' / 'You paid' email body
    with a 2-column table listing: You paid, Paid to, Date, From,
    Transaction ID, Bank reference Number.

    The 'Paid to' value cell contains two <p> elements -- merchant name
    followed by the full VPA. We prefer the VPA as counterparty since it
    is more identifying across rebranded/renamed merchants.
    """

    bank = "jupiter"
    email_type = "jupiter_upi_debit_alert"

    _EXPECTED_KEYS = {
        "you paid",
        "paid to",
        "date",
        "transaction id",
        "bank reference number",
    }

    @staticmethod
    def _extract_paid_to(value_cell) -> tuple[str | None, str | None]:
        """Return (name, vpa) from the 'Paid to' value <td>.

        The cell contains two <p> tags: display name, then VPA (e.g.
        ``MERCHANT@ybl``). Either may be missing.
        """
        paragraphs = [
            p.get_text(strip=True)
            for p in value_cell.find_all("p")
            if p.get_text(strip=True)
        ]
        name: str | None = None
        vpa: str | None = None
        for entry in paragraphs:
            if "@" in entry and vpa is None:
                vpa = entry
            elif name is None:
                name = entry
        return name, vpa

    def parse(self, html: str) -> ParsedEmail:
        soup, text = self.prepare_html(html)

        # Narrow markers: headline + 'You paid' label together uniquely
        # identify this email type among Jupiter's other mails.
        lowered = text.lower()
        if (
            "your upi payment" not in lowered
            or "was successful" not in lowered
            or "you paid" not in lowered
        ):
            raise ParseError("Not a Jupiter UPI debit alert email.")

        fields: dict[str, str] = {}
        paid_to_cell: BeautifulSoup | None = None
        for row in soup.find_all("tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) != 2:
                continue
            key = normalize_key(cells[0].get_text(strip=True))
            if not key or key not in self._EXPECTED_KEYS:
                continue
            fields[key] = cells[1].get_text(strip=True)
            if key == "paid to":
                paid_to_cell = cells[1]

        raw_amount = fields.get("you paid")
        if not raw_amount:
            raise ParseError("Could not find 'You paid' amount in Jupiter email.")
        amount = parse_amount(raw_amount)
        if amount is None:
            raise ParseError(f"Could not parse Jupiter amount: {raw_amount!r}")

        counterparty: str | None = None
        if paid_to_cell is not None:
            name, vpa = self._extract_paid_to(paid_to_cell)
            counterparty = vpa or name

        transaction_date = None
        if raw_date := fields.get("date"):
            transaction_date = parse_date(raw_date)

        reference_number = fields.get("bank reference number") or None

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount, currency="INR"),
                transaction_date=transaction_date,
                counterparty=counterparty,
                reference_number=reference_number,
                channel="upi",
                raw_description=fields.get("paid to"),
            ),
        )


class JupiterStatementEmailParser(BaseEmailParser):
    """Jupiter Edge CSB Bank RuPay Credit Card statement email.

    The email body announces the monthly statement and tells the user how
    to open the attached password-protected PDF. Only the password hint is
    extracted -- there is no per-transaction structure in the body.

    Guard: require the distinctive 'statement is password protected' phrase
    together with a Jupiter brand anchor, to avoid eating other banks' or
    alert-type emails whose footers happen to mention 'statement'.
    """

    bank = "jupiter"
    email_type = "jupiter_statement"

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        lowered = text.lower()
        if "statement is password protected" not in lowered:
            raise ParseError("Not a Jupiter statement email.")
        if "jupiter" not in lowered and "edge csb" not in lowered:
            raise ParseError("Not a Jupiter statement email.")
        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            password_hint="First 4 characters of name (uppercase) + DDMM of birth",
        )


_PARSERS = (
    JupiterUpiDebitAlertParser(),
    JupiterStatementEmailParser(),
)


def parse(html: str) -> ParsedEmail:
    return JupiterParser().parse(html)


class JupiterParser(BankParser):
    bank = "jupiter"
    parsers = _PARSERS
