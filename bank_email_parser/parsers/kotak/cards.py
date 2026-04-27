"""Kotak card and card-payment email parsers."""

import re

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser
from bank_email_parser.utils import parse_amount, parse_date

from ._common import _parse_kotak_datetime


class KotakCcTransactionParser(BaseEmailParser):
    """Kotak Bank credit card spend alert."""

    bank = "kotak"
    email_type = "kotak_cc_transaction"

    _pattern = re.compile(
        r"(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"spent\s+(?:at|on)\s+(?P<merchant>.+?)\s+"
        r"on\s+(?P<date>\d{2}/\d{2}/\d{2,4})\s+"
        r"at\s+(?P<time>\d{2}:\d{2}:\d{2})\s+"
        r"using\s+your\s+Kotak\s+(?P<card_type>Credit|Debit)\s+Card\s+(?P<card>\w+)",
        re.IGNORECASE,
    )
    _credit_limit_pattern = re.compile(
        r"available\s+credit\s+limit\s+is\s+(?:Rs\.?|₹|INR)\s*(?P<limit>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse Kotak CC transaction.")
        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        txn_dt = _parse_kotak_datetime(match.group("date"), match.group("time"))
        balance = None
        if lim_match := self._credit_limit_pattern.search(text):
            if (lim_amount := parse_amount(lim_match.group("limit"))) is not None:
                balance = Money(amount=lim_amount)

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
                balance=balance,
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class KotakCardTransactionParser(BaseEmailParser):
    """Kotak Bank debit card POS transaction."""

    bank = "kotak"
    email_type = "kotak_card_transaction"

    _pattern = re.compile(
        r"Your\s+transaction\s+of\s+(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"(?:at|on)\s+(?P<merchant>.+?)\s+"
        r"using\s+Kotak\s+Bank\s+(?P<card_type>Debit|Credit)\s+Card\s+(?P<card>\w+)\s+"
        r"on\s+(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<time>\d{2}:\d{2}:\d{2})(?:\s+(?!from\b)[A-Z]{2,4})?\s+"
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


class KotakCardRefundParser(BaseEmailParser):
    """Kotak Bank debit card transaction refund/credit.

    Matches: 'The amount of Rs. 24.00 has been credited to your Kotak Bank Account
    XXXXXX3782 against your recent Debit Card transaction with RRN 610548800719.'
    """

    bank = "kotak"
    email_type = "kotak_card_refund"

    _pattern = re.compile(
        r"The\s+amount\s+of\s+(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"has\s+been\s+credited\s+to\s+your\s+Kotak\s+Bank\s+Account\s+(?P<account>\w+)\s+"
        r"against\s+your\s+recent\s+Debit\s+Card\s+transaction",
        re.IGNORECASE,
    )
    _rrn_pattern = re.compile(
        r"RRN\s+(?P<rrn>\w+)",
        re.IGNORECASE,
    )
    _footer_date_pattern = re.compile(
        r"sent\s+by\s+the\s+System\s*:\s*(?P<date>\d{2}/\d{2}/\d{2,4})\s+(?P<time>\d{2}:\d{2})",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse Kotak card refund.")
        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        reference_number = None
        if rrn_match := self._rrn_pattern.search(text):
            reference_number = rrn_match.group("rrn")

        txn_date = None
        txn_time = None
        if footer_match := self._footer_date_pattern.search(text):
            parsed = _parse_kotak_datetime(
                footer_match.group("date"),
                footer_match.group("time"),
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
                reference_number=reference_number,
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class KotakCreditCardPaymentParser(BaseEmailParser):
    """Kotak credit card payment confirmation.

    Matches: 'Thank you for your payment of Rs.X for your Kotak Credit Card
    ending with xxNNNN on DD-Mon-YYYY. Available credit limit is Rs.Y'
    """

    bank = "kotak"
    email_type = "kotak_cc_payment"

    _pattern = re.compile(
        r"Thank\s+you\s+for\s+your\s+payment\s+of\s+"
        r"(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"for\s+your\s+Kotak\s+Credit\s+Card\s+ending\s+with\s+(?P<card>\w+)\s+"
        r"on\s+(?P<date>\d{1,2}-\w{3}-\d{2,4})",
        re.IGNORECASE,
    )
    _credit_limit_pattern = re.compile(
        r"available\s+credit\s+limit\s+is\s+(?:Rs\.?|₹|INR)\s*(?P<limit>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse Kotak CC payment.")
        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        txn_date = parse_date(match.group("date"))

        balance = None
        if lim_match := self._credit_limit_pattern.search(text):
            if (lim_amount := parse_amount(lim_match.group("limit"))) is not None:
                balance = Money(amount=lim_amount)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                counterparty="Payment received",
                card_mask=match.group("card"),
                balance=balance,
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class KotakCcBillPaidParser(BaseEmailParser):
    """Kotak811 credit card bill payment confirmation."""

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
            raise ParseError(
                f"Could not parse amount: {amount_match.group('amount')!r}"
            )

        card_mask = None
        if card_match := self._card_pattern.search(text):
            card_mask = card_match.group("card").strip()

        txn_date = None
        if date_match := self._date_pattern.search(text):
            txn_date = parse_date(date_match.group("date"))

        counterparty = None
        if bank_match := self._bank_pattern.search(text):
            counterparty = bank_match.group("bank_name").strip()

        raw_description = f"CC bill paid: {amount} to {counterparty or 'unknown'}"
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
                raw_description=raw_description,
            ),
        )
