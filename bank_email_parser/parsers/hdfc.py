"""HDFC Bank email parsers.

Supported email types:
- hdfc_upi_alert: UPI debit or credit alert
- hdfc_card_debit_alert: Credit or debit card POS/online transaction
- hdfc_reversal_alert: Card transaction reversal/refund
- hdfc_cheque_clearing: Cheque clearing notification
- hdfc_rupay_upi_debit: RuPay credit card UPI debit
- hdfc_imps_alert: IMPS transfer alert
- hdfc_account_transfer_debit_alert: Savings-to-PPF/SSY transfer debit
- hdfc_account_credit_alert: Savings-account inbound NEFT credit
- hdfc_account_neft_debit_alert: Savings-account outward NEFT debit
"""

import re

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BankParser, BaseEmailParser
from bank_email_parser.utils import parse_amount, parse_date, parse_datetime


def _clean_counterparty(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1].strip()
    return cleaned


class HdfcUpiAlertParser(BaseEmailParser):
    """HDFC Bank UPI transaction alert.

    Matches:
      'Rs.X has been debited from account XXXX to VPA ... on DD-MM-YY.'
      'Rs.X has been credited to account XXXX from VPA ... on DD-MM-YY.'
    """

    bank = "hdfc"
    email_type = "hdfc_upi_alert"

    # Debit. HDFC ships two coexisting variants, captured by one
    # alternated regex:
    #   classic: "Rs.5000.00 has been debited from account 1234
    #             to VPA merchant@upi Sample Merchant on 15-01-26."
    #   newer:   "Rs.50000.00 is debited from your account ending 7703
    #             towards VPA ppfas.common.mf@validicici (PPFASMF) on 08-05-26."
    _debit_pattern = re.compile(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"(?:has\s+been|is)\s+debited\s+from\s+(?:your\s+)?account\s+"
        r"(?:ending\s+)?(?P<account>\w+)\s+"
        r"(?:to|towards)\s+VPA\s+(?P<vpa>\S+)\s+(?P<counterparty>.+?)\s+"
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

    # Reference label varies between formats:
    #   classic: "Your UPI transaction reference number is 123456789012"
    #   newer:   "UPI transaction reference no.: 612853660835"
    _ref_pattern = re.compile(
        r"UPI\s+transaction\s+reference\s+(?:number\s+is|no\.?:?)\s+(?P<ref>\d+)",
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
                counterparty=_clean_counterparty(match.group("counterparty")),
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
    and the newer "We noticed a transaction on your Credit Card" wording
    (observed July 2026):
      'Thank you for using your HDFC Bank Credit Card ending in 1234 .You
       made a transaction of Rs. 422.00 at SAMPLE MERCHANT on 06-07-2026
       17:18:47 . Authorization code: 123456'
    """

    bank = "hdfc"
    email_type = "hdfc_card_debit_alert"

    _pattern = re.compile(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"(?:is|has\s+been)\s+debited\s+from\s+your\s+HDFC\s+Bank\s+"
        r"(?P<card_type>Credit|Debit)\s+Card\s+ending\s+(?P<card>\d{4})\s+"
        r"(?:towards|at)\s+(?P<merchant>.+?)\s+"
        r"on\s+(?P<date>\d{1,2}\s+\w{3},\s*\d{4})\s+"
        r"at\s+(?P<time>\d{2}:\d{2}:\d{2})\s*\.",
    )

    # Newer wording puts the card first and the amount second, uses a
    # numeric "DD-MM-YYYY HH:MM:SS" timestamp, and pads periods with a
    # space ("ending in 1234 .You made a transaction ... 17:18:47 .").
    _pattern_v2 = re.compile(
        r"HDFC\s+Bank\s+(?P<card_type>Credit|Debit)\s+Card\s+"
        r"ending\s+in\s+(?P<card>\d{4})\s*\.\s*"
        r"You\s+made\s+a\s+transaction\s+of\s+"
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"at\s+(?P<merchant>.+?)\s+"
        r"on\s+(?P<date>\d{1,2}-\d{1,2}-\d{4})\s+"
        r"(?P<time>\d{2}:\d{2}:\d{2})\s*\.",
    )

    # Only the newer wording carries one; harmless no-match on classic.
    _auth_code_pattern = re.compile(r"Authorization\s+code\s*:\s*(?P<code>\w+)")

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        for pattern in (self._pattern, self._pattern_v2):
            if match := pattern.search(text):
                break
        else:
            raise ParseError("Could not parse HDFC card debit alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        date_time_str = f"{match.group('date')} at {match.group('time')}"
        txn_dt = parse_datetime(date_time_str)

        reference_number = None
        if auth_match := self._auth_code_pattern.search(text):
            reference_number = auth_match.group("code")

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
                reference_number=reference_number,
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class HdfcReversalAlertParser(BaseEmailParser):
    """HDFC Bank transaction reversal alert.

    Matches: 'Transaction reversal of Rs.1500.00 has been initiated to your
    HDFC Bank Credit Card ending 1234. From Merchant: ... Date Time: ...'
    and the newer refund wording that embeds the phrase mid-sentence with a
    lowercase 't': 'A transaction reversal of Rs. 2.00 has been initiated
    to your HDFC Bank Credit Card ending 1234 From Merchant: ...'
    """

    bank = "hdfc"
    email_type = "hdfc_reversal_alert"

    _amount_pattern = re.compile(
        r"[Tt]ransaction\s+reversal\s+of\s+Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
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
            if dt := parse_datetime(m.group("datetime")):
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

    # Newer variant: "is debited" instead of "has been debited", an explicit
    # "and credited to VPA <vpa> (<Merchant>)" clause, and a spelled-out
    # "DD Mon, YYYY" date:
    #   "Rs.9.00 is debited from your HDFC Bank RuPay Credit Card ending 5854
    #    and credited to VPA uber1.rzp@hdfcbank (UBER INDIA SYSTEMS PRIVATE
    #    LIMITED) on 19 May, 2026."
    _pattern_v2 = re.compile(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"is\s+debited\s+from\s+your\s+HDFC\s+Bank\s+RuPay\s+Credit\s+Card\s+"
        r"(?:ending\s+)?(?P<card>\S+)\s+"
        r"and\s+credited\s+to\s+(?:VPA\s+)?(?P<vpa>\S+)\s+"
        r"(?:\((?P<counterparty>[^)]*)\)\s+)?"
        r"on\s+(?P<date>\d{1,2}\s+\w{3,9},?\s+\d{4})\.",
        re.DOTALL,
    )

    # Reference label varies: "UPI transaction reference number is 123"
    # (classic) and "UPI transaction reference no.: 123" (newer variant).
    # Anchored on the "UPI transaction reference" label so an unrelated
    # "reference no.:" elsewhere in the email is not captured.
    _ref_pattern = re.compile(
        r"UPI\s+transaction\s+reference\s+(?:number\s+is|no\.?:?)\s+(?P<ref>\d+)",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        for pattern in (self._pattern, self._pattern_v2):
            if match := pattern.search(text):
                break
        else:
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


class HdfcAccountTransferDebitParser(BaseEmailParser):
    """HDFC savings-to-PPF/SSY transfer debit alert.

    Matches: 'You have transferred Rs. 1,00,000.00 to your PPF/Sukanya
    Samriddhi Yojana Account No. ending with XX0000 from your A/c No. XX1111,
    through Online Banking on 05-06-2026.'

    Money leaves the savings account into the user's own PPF/SSY account over
    Online Banking, so ``direction`` is ``debit`` and ``channel`` is
    ``online``. The source A/c is the ``account_mask``; the destination
    PPF/SSY account is the ``counterparty``.
    """

    bank = "hdfc"
    email_type = "hdfc_account_transfer_debit_alert"

    _pattern = re.compile(
        r"You\s+have\s+transferred\s+Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"to\s+your\s+PPF/Sukanya\s+Samriddhi\s+Yojana\s+Account\s+No\.\s+"
        r"ending\s+with\s+(?P<dest>\w+)\s+"
        r"from\s+your\s+A/c\s+No\.\s+(?P<account>\w+)\s*,?\s*"
        r"through\s+Online\s+Banking\s+on\s+(?P<date>[\d\-]+)",
        re.DOTALL,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse HDFC account transfer debit alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=parse_date(match.group("date")),
                counterparty=f"PPF/SSY A/c {match.group('dest')}",
                account_mask=match.group("account"),
                channel="online",
                raw_description=match.group(0).strip(),
            ),
        )


class HdfcAccountCreditAlertParser(BaseEmailParser):
    """HDFC savings/current-account inbound NEFT credit alert.

    Matches the "You have received a credit" deposit email:
      'Amount received: INR 100.00  Account: XX0000  Date: 29-JUN-2026
       Reference Details: NEFT Cr-<route>-<remitter>-<beneficiary>-<UTR>
       Available Balance: INR 200.00'

    The NEFT reference is structured ``<route>-<remitter>-<beneficiary>
    -<UTR>``. The remitter (first dash-segment after the route code) is the
    counterparty; the beneficiary is the user. ``channel`` is ``neft``.
    """

    bank = "hdfc"
    email_type = "hdfc_account_credit_alert"

    _pattern = re.compile(
        r"Amount\s+received:\s*INR\s+(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"Account:\s*(?P<account>\w+)\s+"
        r"Date:\s*(?P<date>\d{1,2}-[A-Za-z]+-\d{4})\s+"
        # Reference is "<route>-<remitter>-<beneficiary>-<UTR>". Route is a
        # hyphen-free code and the UTR is a hyphen-free token; the remitter
        # is captured greedily so a hyphenated remitter name (e.g.
        # "STATE-BANK") stays intact, leaving the single-segment beneficiary
        # (the user) and the UTR pinned to the right.
        r"Reference\s+Details:\s*NEFT\s+Cr-(?P<route>[^-]+)-"
        r"(?P<counterparty>.+)-(?P<beneficiary>[^-]+)-(?P<ref>[^-\s]+)\s+"
        r"Available\s+Balance:\s*INR\s+(?P<balance>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE | re.DOTALL,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse HDFC account credit alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        balance = parse_amount(match.group("balance"))

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount),
                transaction_date=parse_date(match.group("date")),
                counterparty=match.group("counterparty").strip(),
                account_mask=match.group("account"),
                reference_number=match.group("ref").strip(),
                balance=Money(amount=balance) if balance is not None else None,
                channel="neft",
                raw_description=match.group(0).strip(),
            ),
        )


class HdfcAccountNeftDebitParser(BaseEmailParser):
    """HDFC savings account NEFT debit alert.

    This parser reads: 'Rs. 1234.56 has been deducted from your HDFC Bank
    account ending in XX0000 for a transfer to payee Sample Payee via NEFT
    using HDFC Bank Online Banking.'

    NEFT moves money from the savings account to an external payee. Thus
    ``direction`` is ``debit`` and ``channel`` is ``neft``. The source
    account gives ``account_mask``. The payee gives ``counterparty``.

    The email has no reference number, no balance, and no date or time.
    These fields stay empty.
    """

    bank = "hdfc"
    email_type = "hdfc_account_neft_debit_alert"

    # This pattern needs the words "to payee <name> via NEFT". Thus it does
    # not take the PPF/SSY transfer alert or the UPI alert. Those alerts use
    # "transferred ... to your PPF/Sukanya" and "to VPA".
    _pattern = re.compile(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"has\s+been\s+deducted\s+from\s+your\s+HDFC\s+Bank\s+account\s+"
        r"ending\s+in\s+(?P<account>\w+)\s+"
        r"for\s+a\s+transfer\s+to\s+payee\s+(?P<counterparty>.+?)\s+"
        # Use the full phrase at the end and not only "via NEFT". The name of
        # a payee can contain those two words. The capture would then stop too
        # soon and give an incomplete name.
        r"via\s+NEFT\s+using\s+HDFC\s+Bank\s+Online\s+Banking",
        re.DOTALL,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse HDFC account NEFT debit alert.")

        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                counterparty=_clean_counterparty(match.group("counterparty")),
                account_mask=match.group("account"),
                channel="neft",
                raw_description=match.group(0).strip(),
            ),
        )


class HdfcStatementEmailParser(BaseEmailParser):
    """HDFC account statement email."""

    bank = "hdfc"
    email_type = "hdfc_account_statement"

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        text_lower = text.lower()
        has_statement = (
            "smartstatement" in text_lower or "account statement" in text_lower
        )
        has_attachment = "password" in text_lower or "attached" in text_lower
        if not (has_statement and has_attachment):
            raise ParseError("Not an HDFC statement email")
        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            password_hint="Customer ID as the password",
        )


_PARSERS = (
    HdfcUpiAlertParser(),
    HdfcCardDebitAlertParser(),
    HdfcReversalAlertParser(),
    HdfcChequeClearingParser(),
    HdfcRupayUpiDebitParser(),
    HdfcImpsAlertParser(),
    HdfcAccountTransferDebitParser(),
    HdfcAccountCreditAlertParser(),
    HdfcAccountNeftDebitParser(),
    HdfcStatementEmailParser(),
)


def parse(html: str) -> ParsedEmail:
    return HdfcParser().parse(html)


class HdfcParser(BankParser):
    bank = "hdfc"
    parsers = _PARSERS
