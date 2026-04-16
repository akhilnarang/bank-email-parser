"""Kotak Bank parser package.

External imports remain stable via ``from bank_email_parser.parsers.kotak import KotakParser``.
"""

from bank_email_parser.models import ParsedEmail
from bank_email_parser.parsers.base import BankParser

from .accounts import KotakImpsCreditParser, KotakNachDebitParser, KotakNeftCreditParser
from .cards import (
    KotakCardRefundParser,
    KotakCardTransactionParser,
    KotakCcBillPaidParser,
    KotakCcTransactionParser,
)
from .digital import Kotak811TransactionParser, KotakDigitalTransactionParser
from .statement import KotakStatementEmailParser
from .upi import KotakUpiPaymentParser, KotakUpiReversalParser

_PARSERS = (
    KotakCcTransactionParser(),
    KotakCardTransactionParser(),
    KotakCardRefundParser(),
    KotakUpiPaymentParser(),
    KotakUpiReversalParser(),
    KotakImpsCreditParser(),
    KotakNeftCreditParser(),
    KotakNachDebitParser(),
    KotakDigitalTransactionParser(),
    Kotak811TransactionParser(),
    KotakCcBillPaidParser(),
    KotakStatementEmailParser(),
)


class KotakParser(BankParser):
    bank = "kotak"
    parsers = _PARSERS


def parse(html: str) -> ParsedEmail:
    return KotakParser().parse(html)


__all__ = [
    "Kotak811TransactionParser",
    "KotakCardRefundParser",
    "KotakCardTransactionParser",
    "KotakCcBillPaidParser",
    "KotakCcTransactionParser",
    "KotakDigitalTransactionParser",
    "KotakImpsCreditParser",
    "KotakNachDebitParser",
    "KotakNeftCreditParser",
    "KotakParser",
    "KotakStatementEmailParser",
    "KotakUpiPaymentParser",
    "KotakUpiReversalParser",
    "parse",
]
