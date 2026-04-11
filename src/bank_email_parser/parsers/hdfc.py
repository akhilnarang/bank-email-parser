"""HDFC Bank email parsers.

Supported email types:
- hdfc_upi_alert: UPI debit or credit alert
- hdfc_card_debit_alert: Credit or debit card POS/online transaction
- hdfc_reversal_alert: Card transaction reversal/refund
- hdfc_cheque_clearing: Cheque clearing notification
- hdfc_rupay_upi_debit: RuPay credit card UPI debit
- hdfc_imps_alert: IMPS transfer alert
"""

import re
from datetime import datetime

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers
from bank_email_parser.utils import parse_amount, parse_date


def _parse_hdfc_date(date_str: str) -> datetime | None:
    """Parse HDFC card date+time strings like '14 Feb, 2026 at 16:35:07'.

    Handles:
      - '14 Feb, 2026' (date only)
      - '14 Feb, 2026 at 16:35:07' (date + time)

    Note: ``%b`` relies on the system locale for month abbreviations.
    This assumes an English (C/POSIX) locale, which is fine for a
    single-user self-hosted tool.
    """
    cleaned = date_str.strip()
    for fmt in ("%d %b, %Y at %H:%M:%S", "%d %b, %Y"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


class HdfcUpiAlertParser(BaseEmailParser):
    """HDFC Bank UPI transaction alert.

    Matches:
      'Rs.X has been debited from account XXXX to VPA ... on DD-MM-YY.'
      'Rs.X has been credited to account XXXX from VPA ... on DD-MM-YY.'
    """

    bank = "hdfc"
    email_type = "hdfc_upi_alert"

    # Debit: "Rs.5000.00 has been debited from account 1234 to VPA merchant@upi Sample Merchant on 15-01-26."
    _debit_pattern = re.compile(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"has\s+been\s+debited\s+from\s+account\s+(?P<account>\w+)\s+"
        r"to\s+VPA\s+(?P<vpa>\S+)\s+(?P<counterparty>.+?)\s+"
        r"on\s+(?P<date>[\d\-]+)\.",
    )

    # Credit: "Rs.500.00 has been credited to account 1234 from VPA ... on DD-MM-YY."
    _credit_pattern = re.compile(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"has\s+been\s+credited\s+to\s+account\s+(?P<account>\w+)\s+"
        r"from\s+VPA\s+(?P<vpa>\S+)\s+(?P<counterparty>.+?)\s+"
        r"on\s+(?P<date>[\d\-]+)\.",
    )

    # Alt credit: "Rs. 5000.00 is successfully credited to your account **1234 by VPA ... on DD-MM-YY."
    _credit_alt_pattern = re.compile(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"is\s+successfully\s+credited\s+to\s+your\s+account\s+(?P<account>\S+)\s+"
        r"by\s+VPA\s+(?P<vpa>\S+)\s+(?P<counterparty>.+?)\s+"
        r"on\s+(?P<date>[\d\-]+)\.",
    )

    _ref_pattern = re.compile(
        r"UPI\s+transaction\s+reference\s+number\s+is\s+(?P<ref>\d+)",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if match := self._debit_pattern.search(text):
            direction = "debit"
        elif match := self._credit_pattern.search(text):
            direction = "credit"
        elif match := self._credit_alt_pattern.search(text):
            direction = "credit"
        else:
            raise ParseError("Could not parse HDFC UPI alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        reference_number = None
        if ref_match := self._ref_pattern.search(text):
            reference_number = ref_match.group("ref")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction=direction,
                amount=Money(amount=amount),
                transaction_date=parse_date(match.group("date")),
                counterparty=match.group("counterparty").strip(),
                account_mask=match.group("account"),
                reference_number=reference_number,
                channel="upi",
                raw_description=match.group(0).strip(),
            ),
        )


class HdfcCardDebitAlertParser(BaseEmailParser):
    """HDFC Bank credit/debit card transaction alert.

    Matches both CC and DC debit patterns:
      CC: 'Rs.1500.00 is debited from your HDFC Bank Credit Card ending 1234
           towards SAMPLE MERCHANT on 15 Jan, 2026 at 10:30:00.'
      DC: 'Rs.2000.00 is debited from your HDFC Bank Debit Card ending 5678
           at SAMPLE STORE on 15 Jan, 2026 at 11:00:00.'
    """

    bank = "hdfc"
    email_type = "hdfc_card_debit_alert"

    _pattern = re.compile(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"is\s+debited\s+from\s+your\s+HDFC\s+Bank\s+"
        r"(?P<card_type>Credit|Debit)\s+Card\s+ending\s+(?P<card>\d{4})\s+"
        r"(?:towards|at)\s+(?P<merchant>.+?)\s+"
        r"on\s+(?P<date>\d{1,2}\s+\w{3},\s*\d{4})\s+"
        r"at\s+(?P<time>\d{2}:\d{2}:\d{2})\.",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse HDFC card debit alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        date_time_str = f"{match.group('date')} at {match.group('time')}"
        txn_dt = _parse_hdfc_date(date_time_str)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=txn_dt.date() if txn_dt else None,
                transaction_time=txn_dt.time() if txn_dt else None,
                counterparty=match.group("merchant").strip(),
                card_mask=match.group("card"),
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class HdfcReversalAlertParser(BaseEmailParser):
    """HDFC Bank transaction reversal alert.

    Matches: 'Transaction reversal of Rs.1500.00 has been initiated to your
    HDFC Bank Credit Card ending 1234. From Merchant: ... Date Time: ...'
    """

    bank = "hdfc"
    email_type = "hdfc_reversal_alert"

    _amount_pattern = re.compile(
        r"Transaction\s+reversal\s+of\s+Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"has\s+been\s+initiated\s+to\s+your\s+HDFC\s+Bank\s+"
        r"(?:Credit|Debit)\s+Card\s+ending\s+(?P<card>\d{4})",
    )

    _merchant_pattern = re.compile(
        r"From\s+Merchant\s*:\s*(?P<merchant>.+?)(?:\s+Date\s+Time\s*:|$)",
    )

    _datetime_pattern = re.compile(
        r"Date\s+Time\s*:\s*(?P<datetime>\d{1,2}\s+\w{3},\s*\d{4}\s+at\s+\d{2}:\d{2}:\d{2})",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._amount_pattern.search(text)):
            raise ParseError("Could not parse HDFC reversal alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        counterparty = None
        if m := self._merchant_pattern.search(text):
            counterparty = m.group("merchant").strip()

        txn_date = None
        txn_time = None
        if m := self._datetime_pattern.search(text):
            if dt := _parse_hdfc_date(m.group("datetime")):
                txn_date = dt.date()
                txn_time = dt.time()

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                transaction_time=txn_time,
                counterparty=counterparty,
                card_mask=match.group("card"),
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class HdfcChequeClearingParser(BaseEmailParser):
    """HDFC Bank cheque clearing notification.

    Matches: 'cheque no. NNNN has been successfully cleared,
    and an amount of Rs. INR 50,000.00 has been deducted from your account ending XXXXXXXX'
    """

    bank = "hdfc"
    email_type = "hdfc_cheque_clearing"

    _pattern = re.compile(
        r"cheque\s+no\.\s*(?P<cheque>\d+)\s+has\s+been\s+successfully\s+cleared.*?"
        r"(?:Rs\.?\s*)?(?:INR\s*)?(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"has\s+been\s+deducted\s+from\s+your\s+account\s+ending\s+(?P<account>\w+)",
        re.IGNORECASE | re.DOTALL,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse HDFC cheque clearing alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                account_mask=match.group("account"),
                reference_number=match.group("cheque"),
                channel="cheque",
                raw_description=match.group(0).strip(),
            ),
        )


class HdfcRupayUpiDebitParser(BaseEmailParser):
    """HDFC RuPay Credit Card UPI debit.

    Matches:
      'Rs.500.00 has been debited from your HDFC Bank RuPay Credit Card XX1234
       to merchant@upi Sample Store on 15-01-26.'
      'Rs.500.00 has been debited from your HDFC Bank RuPay Credit Card ending 1234
       to VPA merchant@upi on 15-01-26.'
    """

    bank = "hdfc"
    email_type = "hdfc_rupay_upi_debit"

    _pattern = re.compile(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"has\s+been\s+debited\s+from\s+your\s+HDFC\s+Bank\s+RuPay\s+Credit\s+Card\s+"
        r"(?:ending\s+)?(?P<card>\S+)\s+"
        r"to\s+(?:VPA\s+)?(?P<vpa>\S+)(?:\s+(?P<counterparty>.+?))?\s+"
        r"on\s+(?P<date>[\d\-]+)\.",
        re.DOTALL,
    )

    _ref_pattern = re.compile(r"reference\s+number\s+is\s+(?P<ref>[\d]+)")

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse HDFC RuPay UPI debit alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        reference_number = None
        if ref_match := self._ref_pattern.search(text):
            reference_number = ref_match.group("ref")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=parse_date(match.group("date")),
                counterparty=(
                    match.group("counterparty") or match.group("vpa")
                ).strip(),
                card_mask=match.group("card"),
                reference_number=reference_number,
                channel="upi",
                raw_description=match.group(0).strip(),
            ),
        )


class HdfcImpsAlertParser(BaseEmailParser):
    """HDFC IMPS transfer alert.

    Matches: 'INR 10,000.00 has been debited from your account ending xxxxxxxxxx1234
    on 15-01-26 and credited to the account ending xxxxxxxxxx5678 via IMPS.'
    """

    bank = "hdfc"
    email_type = "hdfc_imps_alert"

    _pattern = re.compile(
        r"INR\s+(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"has\s+been\s+debited\s+from\s+your\s+account\s+ending\s+(?P<account>\w+)\s+"
        r"on\s+(?P<date>[\d\-]+)\s+"
        r"and\s+credited\s+to\s+the\s+account\s+ending\s+(?P<dest>\w+)\s+"
        r"via\s+IMPS\.",
        re.DOTALL,
    )

    _ref_pattern = re.compile(r"IMPS\s+reference\s+number\s+is\s+(?P<ref>[\d]+)")

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse HDFC IMPS alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        reference_number = None
        if ref_match := self._ref_pattern.search(text):
            reference_number = ref_match.group("ref")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=parse_date(match.group("date")),
                counterparty=match.group("dest").strip(),
                account_mask=match.group("account"),
                reference_number=reference_number,
                channel="imps",
                raw_description=match.group(0).strip(),
            ),
        )


_PARSERS = (
    HdfcUpiAlertParser(),
    HdfcCardDebitAlertParser(),
    HdfcReversalAlertParser(),
    HdfcChequeClearingParser(),
    HdfcRupayUpiDebitParser(),
    HdfcImpsAlertParser(),
)


def parse(html: str) -> ParsedEmail:
    return parse_with_parsers("hdfc", html, _PARSERS)
