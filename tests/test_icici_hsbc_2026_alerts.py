"""Parsers for alert wordings that appeared in 2026.

ICICI internet-banking fund transfers, ICICI savings account credit/debit
alerts, and the HSBC credit card alert wording in use from August 2026. All
samples are synthetic.
"""

from datetime import date, time
from decimal import Decimal

import pytest
from bank_email_parser.api import parse_email
from bank_email_parser.exceptions import ParseError


class TestIciciFundTransferAlert:
    SAMPLE_HTML = """
    <html><body>
      <p>Dear Customer,</p>
      <p>You have made an online ICICI fund transfer payment of Rs. 1,234.00
         towards Sample Payee Name from your ICICI Bank Savings Account XXXX4321
         on Aug 28, 2026 at 04:30 p.m.. The Transaction ID is ABC1234567.</p>
      <p>If you have not initiated this request, please call our Customer Care.</p>
      <p>Team ICICI Bank</p>
    </body></html>
    """

    def test_parses_the_transfer(self):
        result = parse_email("icici", self.SAMPLE_HTML)

        assert result.bank == "icici"
        assert result.email_type == "icici_fund_transfer_alert"
        txn = result.transaction
        assert txn is not None
        assert txn.direction == "debit"
        assert txn.amount.amount == Decimal("1234.00")
        assert txn.amount.currency == "INR"
        assert txn.counterparty == "Sample Payee Name"
        assert txn.account_mask == "XXXX4321"
        assert txn.reference_number == "ABC1234567"
        assert txn.transaction_date == date(2026, 8, 28)
        assert txn.transaction_time == time(16, 30)
        assert txn.channel == "netbanking"

    def test_the_payee_name_is_not_truncated_at_the_word_on(self):
        """A name containing 'on' must survive: the clause ends at 'from your'."""
        html = self.SAMPLE_HTML.replace("Sample Payee Name", "Sonia Ong Sample")

        txn = parse_email("icici", html).transaction

        assert txn is not None
        assert txn.counterparty == "Sonia Ong Sample"

    def test_a_24_hour_time_parses(self):
        html = self.SAMPLE_HTML.replace("04:30 p.m.", "16:30")

        txn = parse_email("icici", html).transaction

        assert txn is not None
        assert txn.transaction_time == time(16, 30)

    @pytest.mark.parametrize(
        "broken", ["Aug 99, 2026 at 04:30 p.m.", "Aug 28, 2026 at 99:99"]
    )
    def test_an_unreadable_timestamp_is_rejected(self, broken):
        """An undated ledger row is worse than a refusal."""
        html = self.SAMPLE_HTML.replace("Aug 28, 2026 at 04:30 p.m.", broken)

        with pytest.raises(ParseError):
            parse_email("icici", html)

    def test_it_does_not_shadow_the_imps_transfer_alert(self):
        """The IMPS alert has its own wording and clause order."""
        html = """
        <html><body>
          <p>You have made an online IMPS payment of Rs. 500.00 towards
             Sample Payee on Aug 28, 2026 at 10:00 from your ICICI Bank
             Savings Account XXXX4321. The Transaction ID is XYZ9876543.</p>
        </body></html>
        """

        result = parse_email("icici", html)

        assert result.email_type == "icici_bank_transfer_alert"


class TestIciciAccountTransactionAlert:
    SAMPLE_HTML = """
    <html><body>
      <p>Dear Customer,</p>
      <p>Greetings from ICICI Bank.</p>
      <p>Your ICICI Bank Account XX4321 has been credited with INR 91 on
         30-Jun-26. Info: XX4321:Int.Pd:30-03-2026 to 29-06-2026.</p>
      <p>NEVER SHARE your Card number, CVV, PIN, OTP with anyone.</p>
    </body></html>
    """

    def test_parses_the_credit(self):
        result = parse_email("icici", self.SAMPLE_HTML)

        assert result.bank == "icici"
        assert result.email_type == "icici_account_transaction_alert"
        txn = result.transaction
        assert txn is not None
        assert txn.direction == "credit"
        assert txn.amount.amount == Decimal("91")
        assert txn.amount.currency == "INR"
        assert txn.account_mask == "XX4321"
        assert txn.transaction_date == date(2026, 6, 30)

    def test_the_info_narration_becomes_the_counterparty(self):
        """The narration says what the money was. The footer must stay out of it."""
        txn = parse_email("icici", self.SAMPLE_HTML).transaction

        assert txn is not None
        assert txn.counterparty == "XX4321:Int.Pd:30-03-2026 to 29-06-2026"
        assert "NEVER SHARE" not in (txn.counterparty or "")

    def test_an_unknown_footer_does_not_bleed_into_the_narration(self):
        """The narration ends at its own sentence, not at a known footer word."""
        html = self.SAMPLE_HTML.replace(
            "Info: XX4321:Int.Pd:30-03-2026 to 29-06-2026.",
            "Info: Sample Interest Credit. Please do not reply to this email.",
        ).replace("<p>NEVER SHARE your Card number, CVV, PIN, OTP with anyone.</p>", "")

        txn = parse_email("icici", html).transaction

        assert txn is not None
        assert txn.counterparty == "Sample Interest Credit"

    def test_a_debit_reads_as_a_debit(self):
        html = self.SAMPLE_HTML.replace("credited with", "debited with")

        txn = parse_email("icici", html).transaction

        assert txn is not None
        assert txn.direction == "debit"


class TestHsbcCcTransactionAlert:
    SAMPLE_HTML = """
    <html><body>
      <p>Dear Customer,</p>
      <p>We&rsquo;re writing to confirm that your HSBC Credit Card xx4321 was
         used for a transaction of INR 978.00 at SAMPLE MERCHANT NAME on
         26/08/26.</p>
      <p>Available limit: INR 157242.85</p>
      <p>Amount due: INR 139757.15</p>
      <p>Regards, HSBC India</p>
    </body></html>
    """

    def test_parses_the_purchase(self):
        result = parse_email("hsbc", self.SAMPLE_HTML)

        assert result.bank == "hsbc"
        assert result.email_type == "hsbc_cc_transaction_alert"
        txn = result.transaction
        assert txn is not None
        assert txn.direction == "debit"
        assert txn.amount.amount == Decimal("978.00")
        assert txn.amount.currency == "INR"
        assert txn.counterparty == "SAMPLE MERCHANT NAME"
        assert txn.card_mask == "4321"
        assert txn.transaction_date == date(2026, 8, 26)
        assert txn.channel == "card"

    def test_the_date_is_day_first(self):
        """01/02/26 is 1 February, not 2 January. The date is ambiguous on
        purpose: a month-first reading would still pass an unambiguous one."""
        html = self.SAMPLE_HTML.replace("26/08/26", "01/02/26")

        txn = parse_email("hsbc", html).transaction

        assert txn is not None
        assert txn.transaction_date == date(2026, 2, 1)

    def test_a_merchant_holding_a_date_does_not_steal_the_date(self):
        html = self.SAMPLE_HTML.replace("SAMPLE MERCHANT NAME", "CAFE ON 01/02/26 ROAD")

        txn = parse_email("hsbc", html).transaction

        assert txn is not None
        assert txn.counterparty == "CAFE ON 01/02/26 ROAD"
        assert txn.transaction_date == date(2026, 8, 26)

    def test_the_available_limit_is_not_read_as_the_amount(self):
        txn = parse_email("hsbc", self.SAMPLE_HTML).transaction

        assert txn is not None
        assert txn.amount.amount == Decimal("978.00")

    def test_it_does_not_shadow_the_older_debit_alert(self):
        html = """
        <html><body>
          <p>your Credit card no ending with 4321,has been used for INR 1500.00
             for payment to SAMPLE MERCHANT on 15 Jan 2026 at 10:30.</p>
        </body></html>
        """

        result = parse_email("hsbc", html)

        assert result.email_type == "hsbc_cc_debit_alert"

    def test_an_unrelated_hsbc_email_is_rejected(self):
        html = "<html><body><p>Your HSBC Credit Card OTP is 123456.</p></body></html>"

        with pytest.raises(ParseError):
            parse_email("hsbc", html)
