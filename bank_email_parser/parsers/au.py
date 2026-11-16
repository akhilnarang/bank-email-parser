"""AU Small Finance Bank email parsers."""

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import ParsedEmail
from bank_email_parser.parsers.base import BankParser, BaseEmailParser


class AuForeignRemittanceNoticeParser(BaseEmailParser):
    """AU outward foreign remittance confirmation with no ledger transaction.

    The email gives one INR total for the remittance. The bank debits that
    total as two amounts, the transfer and the conversion charge, and sends
    one SMS for each debit. The SMS rows are the ledger, so this email adds
    no transaction.
    """

    bank = "au"
    email_type = "au_foreign_remittance_notice"

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        normalized = text.lower()
        if not (
            "foreign remittance confirmation" in normalized
            and "has been booked successfully" in normalized
        ):
            raise ParseError("Not an AU foreign remittance confirmation.")
        return ParsedEmail(email_type=self.email_type, bank=self.bank)


class AuRemittanceRequestNoticeParser(BaseEmailParser):
    """AU notice that a remittance request is received, before any debit."""

    bank = "au"
    email_type = "au_remittance_request_notice"

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        normalized = text.lower()
        if not (
            "to remit" in normalized
            and "has been received" in normalized
            and "currently under process" in normalized
        ):
            raise ParseError("Not an AU remittance request notice.")
        return ParsedEmail(email_type=self.email_type, bank=self.bank)


_PARSERS = (
    AuForeignRemittanceNoticeParser(),
    AuRemittanceRequestNoticeParser(),
)


class AuParser(BankParser):
    bank = "au"
    parsers = _PARSERS


def parse(html: str) -> ParsedEmail:
    return AuParser().parse(html)
