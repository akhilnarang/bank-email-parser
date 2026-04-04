"""Kotak Bank email parsers.

Supported email types:
- kotak_card_transaction: Debit card POS transaction alert
- kotak_upi_payment: Kotak811 UPI payment confirmation
- kotak_digital_transaction: Kotak811 digital transaction (minimal data)
- kotak811_transaction: Kotak811 app transaction (from no-reply@kotak.com)
- kotak_cc_bill_paid: Credit card bill payment confirmation (Kotak811 paying another bank's CC)
"""
import re
from datetime import datetime

from bs4 import BeautifulSoup

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import normalize_whitespace, parse_amount, parse_date


def _parse_kotak_datetime(date_str: str, time_str: str | None = None) -> datetime | None:
    """Parse Kotak date (DD/MM/YYYY) with optional time (HH:MM:SS)."""
    cleaned = date_str.strip()
    if time_str:
        combined = f"{cleaned} {time_str.strip()}"
        try:
            return datetime.strptime(combined, "%d/%m/%Y %H:%M:%S")
        except ValueError:
            pass
    # Date-only fallback
    try:
        return datetime.strptime(cleaned, "%d/%m/%Y")
    except ValueError:
        return None


class KotakCardTransactionParser(BaseEmailParser):
    """Kotak Bank debit card POS transaction.

    Currently only handles debit card POS transactions. The regex captures
    a card_type group (Debit|Credit) but the surrounding pattern is specific
    to debit card email phrasing, so credit card emails will not match.

    Matches:
      'Your transaction of Rs.2000.00 at SAMPLE STORE using Kotak Bank Debit Card
       XX1234 on 15/01/2026 10:30:00 from your account XX5678 has been processed.
       The transaction reference No is 123456789012 & Available balance is Rs.10000.00'
    """

    bank = "kotak"
    email_type = "kotak_card_transaction"

    _pattern = re.compile(
        r"Your\s+transaction\s+of\s+(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"at\s+(?P<merchant>.+?)\s+"
        r"using\s+Kotak\s+Bank\s+(?P<card_type>Debit|Credit)\s+Card\s+(?P<card>\w+)\s+"
        r"on\s+(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+"
        r"from\s+your\s+account\s+(?P<account>\w+)\s+"
        r"has\s+been\s+processed",
        re.IGNORECASE,
    )

    _ref_pattern = re.compile(
        r"transaction\s+reference\s+No\s+is\s+(?P<ref>\w+)",
        re.IGNORECASE,
    )

    _balance_pattern = re.compile(
        r"Available\s+balance\s+is\s+(?:Rs\.?|₹|INR)\s*(?P<balance>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse Kotak card transaction.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        txn_dt = _parse_kotak_datetime(match.group("date"), match.group("time"))

        reference_number = None
        if ref_match := self._ref_pattern.search(text):
            reference_number = ref_match.group("ref")

        balance = None
        if bal_match := self._balance_pattern.search(text):
            if (bal_amount := parse_amount(bal_match.group("balance"))) is not None:
                balance = Money(amount=bal_amount)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=txn_dt.date() if txn_dt else None,
                transaction_time=txn_dt.time() if txn_dt else None,
                counterparty=match.group("merchant").strip(),
                account_mask=match.group("account"),
                card_mask=match.group("card"),
                balance=balance,
                reference_number=reference_number,
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class KotakUpiPaymentParser(BaseEmailParser):
    """Kotak811 UPI payment.

    Matches:
      'You have successfully made a UPI payment of INR 500.00 towards
       Sample Merchant through the Kotak811 App.
       UPI ID: merchant@upi
       Date: 15/01/2026
       UPI Reference Number: 123456789012'
    """

    bank = "kotak"
    email_type = "kotak_upi_payment"

    _pattern = re.compile(
        r"You\s+have\s+successfully\s+made\s+a\s+UPI\s+payment\s+of\s+"
        r"(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"towards\s+(?P<counterparty>.+?)\s+"
        r"through\s+the\s+Kotak811\s+App",
        re.IGNORECASE,
    )

    _upi_id_pattern = re.compile(
        r"UPI\s+ID\s*:\s*(?P<vpa>\S+)",
        re.IGNORECASE,
    )

    _date_pattern = re.compile(
        r"Date\s*:\s*(?P<date>\d{2}/\d{2}/\d{4})",
        re.IGNORECASE,
    )

    _ref_pattern = re.compile(
        r"UPI\s+Reference\s+Number\s*:\s*(?P<ref>\w+)",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse Kotak UPI payment.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        txn_date = None
        if date_match := self._date_pattern.search(text):
            txn_date = parse_date(date_match.group("date"))

        reference_number = None
        if ref_match := self._ref_pattern.search(text):
            reference_number = ref_match.group("ref")

        raw_desc = match.group(0).strip()
        # Include the UPI ID in raw_description if present
        if upi_match := self._upi_id_pattern.search(text):
            raw_desc = f"{raw_desc} UPI ID: {upi_match.group('vpa')}"

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                counterparty=match.group("counterparty").strip(),
                reference_number=reference_number,
                channel="upi",
                raw_description=raw_desc,
            ),
        )


class KotakDigitalTransactionParser(BaseEmailParser):
    """Kotak811 digital transaction (minimal data).

    Matches:
      'Your transaction of [currency] AMOUNT has been processed successfully.'
    Plus an HTML table with Transaction ID, Amount, Status.

    This format provides very limited data -- most fields will be None.
    """

    bank = "kotak"
    email_type = "kotak_digital_transaction"

    _amount_pattern = re.compile(
        r"Your\s+transaction\s+of\s+(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"has\s+been\s+processed\s+successfully",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        soup, text = self.prepare_html(html)

        if not (match := self._amount_pattern.search(text)):
            raise ParseError("Could not parse Kotak digital transaction.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        # Try to extract transaction ID from the HTML table
        reference_number = None
        for row in soup.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                header = cells[0].get_text(strip=True).lower()
                if "transaction id" in header:
                    reference_number = cells[1].get_text(strip=True)
                    break

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                reference_number=reference_number,
                raw_description=match.group(0).strip(),
            ),
        )


class Kotak811TransactionParser(BaseEmailParser):
    """Kotak811 app transaction (from no-reply@kotak.com).

    Subject: "Your Kotak811 Transaction was Successful"

    Matches:
      'Your transaction for INR 5000.00 has been processed successfully.
       Here are your transaction details.
       Transaction ID: Ab3Xy7MnP5QrS9t246UvW8
       Amount: INR 5000.00
       Status: Successful'
    """

    bank = "kotak"
    email_type = "kotak811_transaction"

    _amount_pattern = re.compile(
        r"Your\s+transaction\s+for\s+(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"has\s+been\s+processed\s+successfully",
        re.IGNORECASE,
    )

    _txn_id_pattern = re.compile(
        r"Transaction\s+ID\s*:\s*(?P<txn_id>\S+)",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._amount_pattern.search(text)):
            raise ParseError("Could not parse Kotak811 transaction.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        reference_number = None
        if txn_match := self._txn_id_pattern.search(text):
            reference_number = txn_match.group("txn_id")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                reference_number=reference_number,
                raw_description=match.group(0).strip(),
            ),
        )


class KotakCcBillPaidParser(BaseEmailParser):
    """Kotak811 credit card bill payment confirmation (from no-reply@kotak.com).

    Subject: "Credit Card bill paid successfully!"

    Matches text like:
      'Your credit card bill was paid successfully!
       Bank: ICICI Credit card
       Card no: **** 4242
       Bill amount: ₹2,345
       Paid on: 14 March 2024'
    """

    bank = "kotak"
    email_type = "kotak_cc_bill_paid"

    _pattern = re.compile(
        r"Your\s+credit\s+card\s+bill\s+was\s+paid\s+successfully",
        re.IGNORECASE,
    )

    _bank_pattern = re.compile(
        r"Bank\s*:\s*(?P<bank_name>.+?)(?:\s*Card\s+no|\s*$)",
        re.IGNORECASE,
    )

    _card_pattern = re.compile(
        r"Card\s+no\s*:\s*(?P<card>[*\s\d]+)",
        re.IGNORECASE,
    )

    _amount_pattern = re.compile(
        r"Bill\s+amount\s*:\s*(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    _date_pattern = re.compile(
        r"Paid\s+on\s*:\s*(?P<date>\d{1,2}\s+\w+\s+\d{4})",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not self._pattern.search(text):
            raise ParseError("Could not parse Kotak CC bill paid.")

        if not (amount_match := self._amount_pattern.search(text)):
            raise ParseError("Could not find bill amount in Kotak CC bill paid email.")

        if (amount := parse_amount(amount_match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {amount_match.group('amount')!r}")

        card_mask = None
        if card_match := self._card_pattern.search(text):
            card_mask = card_match.group("card").strip()

        txn_date = None
        if date_match := self._date_pattern.search(text):
            txn_date = parse_date(date_match.group("date"))

        counterparty = None
        if bank_match := self._bank_pattern.search(text):
            counterparty = bank_match.group("bank_name").strip()

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                counterparty=counterparty,
                card_mask=card_mask,
                channel="card",
                raw_description=f"CC bill paid: {amount} to {counterparty or 'unknown'}",
            ),
        )


_PARSERS = (
    KotakCardTransactionParser(),
    KotakUpiPaymentParser(),
    KotakDigitalTransactionParser(),
    Kotak811TransactionParser(),
    KotakCcBillPaidParser(),
)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("kotak", html, _PARSERS)
