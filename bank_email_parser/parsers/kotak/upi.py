"""Kotak UPI-related email parsers."""

import re

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser
from bank_email_parser.utils import parse_amount, parse_date

from ._common import _parse_kotak_datetime


class KotakUpiPaymentParser(BaseEmailParser):
    """Kotak811 UPI payment."""

    bank = "kotak"
    email_type = "kotak_upi_payment"

    _pattern = re.compile(
        r"You\s+have\s+successfully\s+made\s+a\s+UPI\s+payment\s+of\s+"
        r"(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"towards\s+(?P<counterparty>.+?)\s+"
        r"through\s+the\s+Kotak811\s+App",
        re.IGNORECASE,
    )
    _upi_id_pattern = re.compile(r"UPI\s+ID\s*:\s*(?P<vpa>\S+)", re.IGNORECASE)
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


class KotakUpiCreditParser(BaseEmailParser):
    """Kotak811 UPI incoming credit.

    Matches the label:value alert 'You've received a UPI Credit in your Kotak
    A/c (XXNNNN)' with 'Date:', 'Amount:', 'Sender:', and 'UPI Reference
    Number (RRN):' rows. Distinct from the IMPS/NEFT credit prose formats.
    """

    bank = "kotak"
    email_type = "kotak_upi_credit"

    _pattern = re.compile(
        r"received\s+a\s+UPI\s+Credit\s+in\s+your\s+Kotak\s+A/c\s*"
        r"\(\s*(?P<account>\w+)\s*\)",
        re.IGNORECASE,
    )
    # ``\b`` keeps 'Date' out of 'Update:' and 'Amount' out of longer words.
    _amount_pattern = re.compile(
        r"\bAmount\s*:\s*(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )
    # Bounded and delimited on both sides. An empty sender matches the empty
    # capture and is rejected below; a trailing sender cannot bleed the footer
    # into the counterparty, which is the downstream event identity. The length
    # cap also keeps the lazy scan linear.
    _sender_pattern = re.compile(
        r"\bSender\s*:\s*(?P<sender>.{0,80}?)\s*"
        r"(?:UPI\s+Reference|View\s+balance|Date\s*:|Amount\s*:|$)",
        re.IGNORECASE,
    )
    _ref_pattern = re.compile(
        r"UPI\s+Reference\s+Number\s*\(RRN\)\s*:\s*(?P<ref>\d+)",
        re.IGNORECASE,
    )
    _date_pattern = re.compile(
        r"\bDate\s*:\s*(?P<date>\d{1,2}-[A-Za-z]{3}-\d{2,4})",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse Kotak UPI credit.")
        # Read the summary that follows the marker, so a decoy label earlier in
        # the email cannot supply the amount, date, sender, or reference. Every
        # field this format carries is required; a missing or unparseable one
        # means an unexpected shape, so raise rather than import a half-read
        # credit (a null reference has no dedup key).
        summary = text[match.end() :]

        if not (amount_match := self._amount_pattern.search(summary)):
            raise ParseError("Could not find amount in Kotak UPI credit email.")
        if (amount := parse_amount(amount_match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {amount_match.group('amount')!r}")

        sender_match = self._sender_pattern.search(summary)
        counterparty = sender_match.group("sender").strip() if sender_match else ""
        if not counterparty:
            raise ParseError("Could not find sender in Kotak UPI credit email.")

        if not (ref_match := self._ref_pattern.search(summary)):
            raise ParseError("Could not find UPI reference in Kotak UPI credit email.")

        if not (date_match := self._date_pattern.search(summary)):
            raise ParseError("Could not find date in Kotak UPI credit email.")
        if (txn_date := parse_date(date_match.group("date"))) is None:
            raise ParseError(f"Could not parse date: {date_match.group('date')!r}")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                counterparty=counterparty,
                reference_number=ref_match.group("ref"),
                account_mask=match.group("account"),
                channel="upi",
                raw_description=match.group(0).strip(),
            ),
        )


class KotakUpiReversalParser(BaseEmailParser):
    """Kotak Bank UPI transaction reversal credit."""

    bank = "kotak"
    email_type = "kotak_upi_reversal"

    _pattern = re.compile(
        r"(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"is\s+credited\s+to\s+your\s+Kotak\s+Bank\s+Account\s+(?P<account>\w+)\s+"
        r"for\s+reversal\s+of\s+UPI\s+transaction\s+(?P<ref>[\w-]+)",
        re.IGNORECASE,
    )
    _date_pattern = re.compile(
        r"sent\s+by\s+the\s+System\s*:\s*(?P<date>\d{2}/\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2})",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse Kotak UPI reversal.")
        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        txn_date = None
        txn_time = None
        if date_match := self._date_pattern.search(text):
            parsed = _parse_kotak_datetime(
                date_match.group("date"),
                date_match.group("time"),
            )
            if parsed:
                txn_date = parsed.date()
                txn_time = parsed.time()

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                transaction_time=txn_time,
                account_mask=match.group("account"),
                reference_number=match.group("ref"),
                channel="upi",
                raw_description=match.group(0).strip(),
            ),
        )
