"""IndusInd Bank email parsers.

Supported email types:
- indusind_cc_transaction_alert: Credit card spend/transaction alert (inline prose)
- indusind_dc_transaction_alert: Debit card transaction alert (intro + HTML table)
- indusind_account_alert: Savings account credit/debit alert (UPI, inline prose)
- indusind_cc_payment_alert: Credit card payment confirmation
"""
import re
from datetime import datetime

from bs4 import BeautifulSoup

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import (
    extract_table_pairs,
    normalize_key,
    parse_amount,
    parse_date,
)


def _parse_indusind_datetime(date_str: str, time_str: str | None = None) -> datetime | None:
    """Parse IndusInd date strings with optional 12-hour time."""
    cleaned_date = date_str.strip()
    if time_str is not None:
        cleaned_time = time_str.strip().upper()
        try:
            return datetime.strptime(
                f"{cleaned_date} {cleaned_time}",
                "%d-%m-%Y %I:%M:%S %p",
            )
        except ValueError:
            pass
    try:
        return datetime.strptime(cleaned_date, "%d-%m-%Y")
    except ValueError:
        return None


class IndusindCcPaymentAlertParser(BaseEmailParser):
    """IndusInd Bank credit card payment confirmation.

    Matches: 'Thank you for your Payment of INR X towards your IndusInd Bank Credit Card.
    Your payment is credited to your Credit Card account on DD/MM/YYYY.'
    """

    bank = "indusind"
    email_type = "indusind_cc_payment_alert"

    _pattern = re.compile(
        r"Payment\s+of\s+(?:INR|Rs\.?|₹)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"towards\s+your\s+IndusInd\s+Bank\s+Credit\s+Card",
        re.IGNORECASE,
    )

    _date_pattern = re.compile(
        r"credited\s+to\s+your\s+Credit\s+Card\s+account\s+on\s+(?P<date>[\d/\-]+)",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse IndusInd CC payment alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        transaction_date = None
        if date_match := self._date_pattern.search(text):
            transaction_date = parse_date(date_match.group("date"))

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount),
                transaction_date=transaction_date,
                counterparty="Payment received",
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class IndusindCcTransactionAlertParser(BaseEmailParser):
    """IndusInd Bank credit card spend/transaction alert (inline prose).

    Matches: 'The transaction on your IndusInd Bank Credit Card ending 1234
    for INR 1,000.00 on 15-01-2026 12:00:01 am at SAMPLE MERCHANT
    is Approved. Available Limit: INR 50,000.00.'
    """

    bank = "indusind"
    email_type = "indusind_cc_transaction_alert"

    _pattern = re.compile(
        r"transaction\s+on\s+your\s+IndusInd\s+Bank\s+Credit\s+Card\s+"
        r"ending\s+(?P<card>\d+)\s+"
        r"for\s+(?:INR|Rs\.?|₹)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"on\s+(?P<date>\d{2}-\d{2}-\d{4})\s+"
        r"(?P<time>\d{1,2}:\d{2}:\d{2}\s*(?:am|pm))\s+"
        r"at\s+(?P<merchant>.+?)\s+is\s+Approved",
        re.IGNORECASE,
    )

    _limit_pattern = re.compile(
        r"Available\s+Limit:\s*(?:INR|Rs\.?|₹)\s*(?P<limit>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse IndusInd CC transaction alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        transaction_dt = _parse_indusind_datetime(
            match.group("date"),
            match.group("time"),
        )

        balance = None
        if limit_match := self._limit_pattern.search(text):
            if (limit_amt := parse_amount(limit_match.group("limit"))) is not None:
                balance = Money(amount=limit_amt)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=transaction_dt.date() if transaction_dt else None,
                transaction_time=transaction_dt.time() if transaction_dt else None,
                counterparty=match.group("merchant").strip(),
                balance=balance,
                card_mask=match.group("card"),
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class IndusindDcTransactionAlertParser(BaseEmailParser):
    """IndusInd Bank debit card transaction alert (intro sentence + HTML table).

    Matches intro: 'transaction initiated via your IndusInd Bank Debit Card
    ending 5678 is successful'
    Table rows: Merchant Name, Amount*, Date, Time
    Balance line: 'The balance available in your account is INR 0.00'
    """

    bank = "indusind"
    email_type = "indusind_dc_transaction_alert"

    _intro_pattern = re.compile(
        r"transaction\s+initiated\s+via\s+your\s+IndusInd\s+Bank\s+Debit\s+Card\s+"
        r"ending\s+(?P<card>\d+)\s+is\s+successful",
        re.IGNORECASE,
    )

    _balance_pattern = re.compile(
        r"balance\s+available\s+in\s+your\s+account\s+is\s+"
        r"(?:INR|Rs\.?|₹)\s*(?P<balance>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    _FIELD_PREFIXES = {"merchant name": "merchant", "amount": "amount", "date": "date", "time": "time"}

    def _extract_fields(self, soup: BeautifulSoup) -> dict[str, str]:
        """Extract table fields using prefix matching on normalized keys.

        Handles verbose labels like 'Amount*(*Including Tax...)' by matching
        on the prefix 'amount' rather than requiring an exact match.
        """
        fields: dict[str, str] = {}
        for row in soup.find_all("tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) != 2:
                continue
            key = normalize_key(cells[0].get_text(strip=True))
            if not key:
                continue
            for prefix, field_name in self._FIELD_PREFIXES.items():
                if key == prefix or key.startswith(prefix):
                    fields[field_name] = cells[1].get_text(strip=True)
                    break
        return fields

    def parse(self, html: str) -> ParsedEmail:
        soup, text = self.prepare_html(html)

        if not (intro_match := self._intro_pattern.search(text)):
            raise ParseError("Could not parse IndusInd DC transaction alert.")

        table_data = self._extract_fields(soup)

        if not (raw_amount := table_data.get("amount")):
            raise ParseError("Could not find Amount in table data.")

        # Strip currency prefix from table amount value (e.g. "INR 130,000.00")
        cleaned_amount = re.sub(r"^(?:INR|Rs\.?|₹)\s*", "", raw_amount)
        if (amount := parse_amount(cleaned_amount)) is None:
            raise ParseError(f"Could not parse amount: {raw_amount!r}")

        transaction_dt = None
        if date_str := table_data.get("date"):
            transaction_dt = _parse_indusind_datetime(date_str, table_data.get("time"))

        counterparty = table_data.get("merchant")

        balance = None
        if bal_match := self._balance_pattern.search(text):
            if (bal_amt := parse_amount(bal_match.group("balance"))) is not None:
                balance = Money(amount=bal_amt)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=transaction_dt.date() if transaction_dt else None,
                transaction_time=transaction_dt.time() if transaction_dt else None,
                counterparty=counterparty,
                balance=balance,
                card_mask=intro_match.group("card"),
                channel="card",
                raw_description=intro_match.group(0).strip(),
            ),
        )


class IndusindAccountAlertParser(BaseEmailParser):
    """IndusInd Bank account credit/debit alert (UPI, inline prose).

    Matches: 'Your IndusInd Bank Account No. 10XXXXXX1234 has been Credited
    for INR 1,000.00 towards UPI/123456789012/...'
    """

    bank = "indusind"
    email_type = "indusind_account_alert"

    _pattern = re.compile(
        r"IndusInd\s+Bank\s+Account\s+No\.\s*(?P<account>[\dX]+)\s+"
        r"has\s+been\s+(?P<direction>Credited|Debited)\s+"
        r"for\s+(?:INR|Rs\.?|₹)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"towards\s+(?P<description>.+?)\.\s*(?:The\s+balance|$)",
        re.IGNORECASE,
    )

    _balance_pattern = re.compile(
        r"balance\s+available\s+in\s+your\s+Account\s+is\s+"
        r"(?:INR|Rs\.?|₹)\s*(?P<balance>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse IndusInd account alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        direction = "credit" if match.group("direction").lower() == "credited" else "debit"
        description = match.group("description").rstrip(".")

        # Extract channel from description (e.g. "UPI/..." -> "upi")
        channel = description.split("/", 1)[0].lower() if "/" in description else None

        balance = None
        if bal_match := self._balance_pattern.search(text):
            if (bal_amt := parse_amount(bal_match.group("balance"))) is not None:
                balance = Money(amount=bal_amt)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction=direction,
                amount=Money(amount=amount),
                counterparty="Payment received" if direction == "credit" else None,
                balance=balance,
                account_mask=match.group("account"),
                channel=channel,
                raw_description=description,
            ),
        )


_PARSERS = (
    IndusindCcTransactionAlertParser(),
    IndusindDcTransactionAlertParser(),
    IndusindAccountAlertParser(),
    IndusindCcPaymentAlertParser(),
)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("indusind", html, _PARSERS)
