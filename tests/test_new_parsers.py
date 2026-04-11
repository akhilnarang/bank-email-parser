"""Tests for newly added parsers: Kotak811 Transaction, Kotak CC Bill Paid,
ICICI CC Reversal (stub), and Axis NEFT (stub)."""

from decimal import Decimal

import pytest

from bank_email_parser.api import parse_email
from bank_email_parser.exceptions import ParseError


class TestKotak811TransactionParser:
    """Test Kotak811TransactionParser with synthetic HTML matching the observed format."""

    SAMPLE_HTML = """
    <html><body>
    <table width="100%">
      <tr><td>Hello Sample Customer Name,</td></tr>
      <tr><td>Your transaction for INR 4321.00 has been processed successfully.
        Here are your transaction details.</td></tr>
      <tr><td>Transaction ID: Ab3Xy7MnP5QrS9t246UvW8</td></tr>
      <tr><td>Amount: INR 4321.00</td></tr>
      <tr><td>Status: Successful</td></tr>
      <tr><td>Team Kotak811,</td></tr>
    </table>
    </body></html>
    """

    def test_parses_kotak811_transaction(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.email_type == "kotak811_transaction"
        assert result.bank == "kotak"
        assert result.transaction.direction == "debit"
        assert result.transaction.amount.amount == Decimal("4321.00")
        assert result.transaction.amount.currency == "INR"
        assert result.transaction.reference_number == "Ab3Xy7MnP5QrS9t246UvW8"

    def test_parses_rupee_symbol(self):
        html = """
        <html><body>
        <table>
          <tr><td>Your transaction for ₹ 12345.00 has been processed successfully.</td></tr>
          <tr><td>Transaction ID: Cd4Za8LpR6TuV1w357XyQ9</td></tr>
          <tr><td>Amount: ₹ 12345.00</td></tr>
          <tr><td>Status: SUCCESS</td></tr>
        </table>
        </body></html>
        """
        result = parse_email("kotak", html)
        assert result.email_type == "kotak811_transaction"
        assert result.transaction.amount.amount == Decimal("12345.00")
        assert result.transaction.reference_number == "Cd4Za8LpR6TuV1w357XyQ9"


class TestKotakCcBillPaidParser:
    """Test KotakCcBillPaidParser with synthetic HTML matching the observed format."""

    SAMPLE_HTML = """
    <html><body>
    <table width="100%">
      <tr><td>
        <p>
          Hello CUSTOMER,<br><br>
          Your credit card bill was paid successfully!<br><br>
          Bank: ICICI Credit card<br>
          Card no: **** 4242<br>
          Bill amount: ₹2,345<br>
          Paid on: 14 March 2024<br><br>
          Digitally yours,<br>
          Kotak811
        </p>
      </td></tr>
    </table>
    </body></html>
    """

    def test_parses_cc_bill_paid(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.email_type == "kotak_cc_bill_paid"
        assert result.bank == "kotak"
        assert result.transaction.direction == "debit"
        assert result.transaction.amount.amount == Decimal("2345")
        assert result.transaction.amount.currency == "INR"
        assert result.transaction.card_mask == "**** 4242"

    def test_parses_date(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.transaction.transaction_date is not None
        assert result.transaction.transaction_date.year == 2024
        assert result.transaction.transaction_date.month == 3
        assert result.transaction.transaction_date.day == 14

    def test_extracts_bank_as_counterparty(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.transaction.counterparty is not None
        assert "ICICI" in result.transaction.counterparty

    def test_parses_hsbc_variant(self):
        html = """
        <html><body>
        <p>
          Hello CUSTOMER,<br><br>
          Your credit card bill was paid successfully!<br><br>
          Bank: HSBC Credit Card<br>
          Card no: **** 5151<br>
          Bill amount: ₹2,345<br>
          Paid on: 09 March 2024<br><br>
        </p>
        </body></html>
        """
        result = parse_email("kotak", html)
        assert result.email_type == "kotak_cc_bill_paid"
        assert result.transaction.card_mask == "**** 5151"
        assert "HSBC" in result.transaction.counterparty

    def test_parses_large_amount_with_commas(self):
        html = """
        <html><body>
        <p>
          Your credit card bill was paid successfully!<br>
          Bank: ICICI Credit card<br>
          Card no: **** 4242<br>
          Bill amount: ₹2,64,831.40<br>
          Paid on: 22 March 2024<br>
        </p>
        </body></html>
        """
        result = parse_email("kotak", html)
        assert result.transaction.amount.amount == Decimal("264831.40")


class TestKotakCcTransactionParser:
    """Test KotakCcTransactionParser for credit card spend alerts."""

    SAMPLE_HTML = """
    <html><body>
    <p>Transaction Successful.<br>
    INR 58 spent at Sample Store on 09/04/26
    at 09:01:05 using your Kotak Credit Card x5544.<br>
    Your available credit limit is INR 50000.5.</p>
    </body></html>
    """

    def test_parses_cc_transaction(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.email_type == "kotak_cc_transaction"
        assert result.bank == "kotak"
        assert result.transaction.direction == "debit"
        assert result.transaction.amount.amount == Decimal("58")
        assert result.transaction.counterparty == "Sample Store"
        assert result.transaction.card_mask == "x5544"
        assert result.transaction.channel == "card"

    def test_parses_date_and_time(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.transaction.transaction_date is not None
        assert result.transaction.transaction_date.year == 2026
        assert result.transaction.transaction_date.month == 4
        assert result.transaction.transaction_date.day == 9
        assert result.transaction.transaction_time is not None

    def test_parses_credit_limit(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.transaction.balance is not None
        assert result.transaction.balance.amount == Decimal("50000.5")

    def test_parses_without_credit_limit(self):
        html = """
        <html><body>
        <p>INR 1500.00 spent at Big Bazaar on 15/01/2026
        at 14:30:00 using your Kotak Credit Card x9988.</p>
        </body></html>
        """
        result = parse_email("kotak", html)
        assert result.email_type == "kotak_cc_transaction"
        assert result.transaction.amount.amount == Decimal("1500.00")
        assert result.transaction.counterparty == "Big Bazaar"
        assert result.transaction.balance is None

    def test_parses_on_variant(self):
        """'spent on MERCHANT' should also work (like 'spent at MERCHANT')."""
        html = """
        <html><body>
        <p>INR 250 spent on Swiggy on 20/03/26
        at 18:45:12 using your Kotak Credit Card x1122.</p>
        </body></html>
        """
        result = parse_email("kotak", html)
        assert result.email_type == "kotak_cc_transaction"
        assert result.transaction.counterparty == "Swiggy"


class TestKotakCardTransactionOnVariant:
    """Test KotakCardTransactionParser with 'on <merchant>' phrasing."""

    SAMPLE_HTML = """
    <html><body>
    <p>Dear Customer,<br>
    Your transaction of Rs.711.00 on Blinkit using Kotak Bank Debit Card XX4455
    on 11/04/2026 15:13:27 from your account XX9912 has been processed.<br>
    The transaction reference No is 912345678901 &amp; Available balance is Rs.12345.67.</p>
    </body></html>
    """

    def test_parses_on_variant(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.email_type == "kotak_card_transaction"
        assert result.bank == "kotak"
        assert result.transaction.direction == "debit"
        assert result.transaction.amount.amount == Decimal("711.00")
        assert result.transaction.counterparty == "Blinkit"
        assert result.transaction.card_mask == "XX4455"
        assert result.transaction.account_mask == "XX9912"
        assert result.transaction.channel == "card"
        assert result.transaction.reference_number == "912345678901"
        assert result.transaction.balance is not None
        assert result.transaction.balance.amount == Decimal("12345.67")

    def test_parses_date_and_time(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.transaction.transaction_date is not None
        assert result.transaction.transaction_date.year == 2026
        assert result.transaction.transaction_date.month == 4
        assert result.transaction.transaction_date.day == 11
        assert result.transaction.transaction_time is not None

    def test_at_variant_still_works(self):
        """Ensure the original 'at <merchant>' phrasing still parses."""
        html = """
        <html><body>
        <p>Your transaction of Rs.2000.00 at SAMPLE STORE using Kotak Bank Debit Card XX1234
        on 15/01/2026 10:30:00 from your account XX5678 has been processed.
        The transaction reference No is 123456789012 &amp; Available balance is Rs.10000.00.</p>
        </body></html>
        """
        result = parse_email("kotak", html)
        assert result.email_type == "kotak_card_transaction"
        assert result.transaction.counterparty == "SAMPLE STORE"
        assert result.transaction.amount.amount == Decimal("2000.00")


class TestKotakUpiReversalParser:
    """Test KotakUpiReversalParser with UPI reversal credit email."""

    SAMPLE_HTML = """
    <html><body>
    <p>Dear Customer,<br><br>
    Rs. 300.00 is credited to your Kotak Bank Account XXXXXX5678
    for reversal of UPI transaction NA-a1b2c3d4-e5f6-7890-abcd-ef0123456789.<br><br>
    Please check A/c activity for more details in Kotak Mobile Banking App.<br><br>
    We look forward to your continued patronage.<br><br>
    Warm regards,<br>Kotak Mahindra Bank<br><br>
    This message was sent by the System :01/04/26 03:17</p>
    </body></html>
    """

    def test_parses_upi_reversal(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.email_type == "kotak_upi_reversal"
        assert result.bank == "kotak"
        assert result.transaction.direction == "credit"
        assert result.transaction.amount.amount == Decimal("300.00")
        assert result.transaction.account_mask == "XXXXXX5678"
        assert (
            result.transaction.reference_number
            == "NA-a1b2c3d4-e5f6-7890-abcd-ef0123456789"
        )
        assert result.transaction.channel == "upi"

    def test_parses_date_and_time(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.transaction.transaction_date is not None
        assert result.transaction.transaction_date.year == 2026
        assert result.transaction.transaction_date.month == 4
        assert result.transaction.transaction_date.day == 1
        assert result.transaction.transaction_time is not None

    def test_parses_without_footer_date(self):
        """Reversal should still parse even without the System timestamp footer."""
        html = """
        <html><body>
        <p>Rs. 300.00 is credited to your Kotak Bank Account XX1234
        for reversal of UPI transaction ABC-123.</p>
        </body></html>
        """
        result = parse_email("kotak", html)
        assert result.email_type == "kotak_upi_reversal"
        assert result.transaction.amount.amount == Decimal("300.00")
        assert result.transaction.reference_number == "ABC-123"
        assert result.transaction.transaction_date is None


class TestKotakNeftCreditParser:
    """Test KotakNeftCreditParser for NEFT incoming credit (Email #280)."""

    SAMPLE_HTML = """
    <html><body>
    <p>Dear Customer,<br><br>
    Rs. 50000 has been credited to your Kotak Bank a/c XX5678 on 31-MAR-26
    via NEFT transaction from Acme Corp.<br>
    Your Unique Transaction Reference Number (UTR) is: INDBH0000000001234<br><br>
    Details of your transaction:<br>
    AMOUNT : INR 50000<br>
    SENDER : Acme Corp<br>
    SENDER BRANCH IFSC : INDB0000006<br>
    UNIQUE TRANSACTION REFERENCE NUMBER (UTR) : INDBH0000000001234<br>
    DATE OF CREDIT : 31-MAR-26<br><br>
    Warm Regards,<br>Team Kotak Mahindra Bank</p>
    </body></html>
    """

    def test_parses_neft_credit(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.email_type == "kotak_neft_credit"
        assert result.bank == "kotak"
        assert result.transaction.direction == "credit"
        assert result.transaction.amount.amount == Decimal("50000")
        assert result.transaction.account_mask == "XX5678"
        assert result.transaction.counterparty == "Acme Corp"
        assert result.transaction.reference_number == "INDBH0000000001234"
        assert result.transaction.channel == "neft"

    def test_parses_date(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.transaction.transaction_date is not None
        assert result.transaction.transaction_date.year == 2026
        assert result.transaction.transaction_date.month == 3
        assert result.transaction.transaction_date.day == 31

    def test_parses_without_utr(self):
        html = """
        <html><body>
        <p>INR 2500.00 has been credited to your Kotak Bank a/c XX9912
        on 15-JAN-26 via NEFT transaction from Test Sender.</p>
        </body></html>
        """
        result = parse_email("kotak", html)
        assert result.email_type == "kotak_neft_credit"
        assert result.transaction.amount.amount == Decimal("2500.00")
        assert result.transaction.counterparty == "Test Sender"
        assert result.transaction.reference_number is None


class TestKotakNachDebitParser:
    """Test KotakNachDebitParser with NACH/ECS debit email."""

    SAMPLE_HTML = """
    <html><body>
    <p>Dear Customer,<br><br>
    Your account XXXXXXXX5678 has been debited towards NACH/ECS transaction as per details below.<br><br>
    Beneficiary: IDFC FIRST BANK<br>
    UMRN Number: KKBK0000000000123456<br>
    Amount: Rs.5,000.00<br>
    Transaction date : 03/04/2026<br><br>
    Thank you for banking with us.<br>
    Regards,<br>Kotak Mahindra Bank Ltd.<br><br>
    This message was sent by the System :03/04/26 10:20</p>
    </body></html>
    """

    def test_parses_nach_debit(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.email_type == "kotak_nach_debit"
        assert result.bank == "kotak"
        assert result.transaction.direction == "debit"
        assert result.transaction.amount.amount == Decimal("5000.00")
        assert result.transaction.account_mask == "XXXXXXXX5678"
        assert result.transaction.counterparty == "IDFC FIRST BANK"
        assert result.transaction.reference_number == "KKBK0000000000123456"
        assert result.transaction.channel == "nach"

    def test_parses_date(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.transaction.transaction_date is not None
        assert result.transaction.transaction_date.year == 2026
        assert result.transaction.transaction_date.month == 4
        assert result.transaction.transaction_date.day == 3

    def test_parses_without_beneficiary(self):
        html = """
        <html><body>
        <p>Your account XX9988 has been debited towards NACH/ECS transaction as per details below.<br>
        UMRN Number: KKBK1234567890<br>
        Amount: Rs.1,500.00<br>
        Transaction date : 15/01/2026</p>
        </body></html>
        """
        result = parse_email("kotak", html)
        assert result.email_type == "kotak_nach_debit"
        assert result.transaction.amount.amount == Decimal("1500.00")
        assert result.transaction.counterparty is None
        assert result.transaction.reference_number == "KKBK1234567890"


class TestIciciCcReversalStub:
    """Test that the ICICI CC Reversal parser raises NotImplementedError."""

    def test_raises_not_implemented(self):
        """The stub should raise ParseError (wrapping NotImplementedError)
        when no other parser matches and reversal format is encountered."""
        html = "<html><body>Reversal processed on your ICICI Bank Credit Card</body></html>"
        with pytest.raises(ParseError):
            parse_email("icici", html)


class TestAxisNeftStub:
    """Test that the Axis NEFT parser raises NotImplementedError."""

    def test_raises_not_implemented(self):
        """The stub should raise ParseError (wrapping NotImplementedError)
        when no other parser matches."""
        html = "<html><body>NEFT is initiated from your Axis Bank account</body></html>"
        with pytest.raises(ParseError):
            parse_email("axis", html)


class TestBomUpiDebitAlertParser:
    """Test Bank of Maharashtra UPI debit alert parser with synthetic HTML."""

    SAMPLE_HTML = """
    <html><body>
    <p>Dear Customer,</p>
    <p>Your A/c No xx 4521 debited by INR 2,500.00 on 15-JAN-2026
    with UPI RRN :412356789012. A/c Bal is INR 12.50 CR and AVL Bal is INR 12.50 CR</p>
    </body></html>
    """

    def test_parses_bom_upi_debit(self):
        result = parse_email("bom", self.SAMPLE_HTML)
        assert result.email_type == "bom_upi_debit_alert"
        assert result.bank == "bom"
        assert result.transaction.direction == "debit"
        assert result.transaction.amount.amount == Decimal("2500.00")
        assert result.transaction.amount.currency == "INR"
        assert result.transaction.account_mask == "xx 4521"
        assert result.transaction.channel == "upi"
        assert result.transaction.reference_number == "412356789012"

    def test_parses_date(self):
        result = parse_email("bom", self.SAMPLE_HTML)
        assert result.transaction.transaction_date is not None
        assert result.transaction.transaction_date.year == 2026
        assert result.transaction.transaction_date.month == 1
        assert result.transaction.transaction_date.day == 15

    def test_parses_balance(self):
        result = parse_email("bom", self.SAMPLE_HTML)
        assert result.transaction.balance is not None
        assert result.transaction.balance.amount == Decimal("12.50")

    def test_parses_without_balance(self):
        html = """
        <html><body>
        <p>Your A/c No XX7890 debited by INR 500.00 on 03-FEB-2026
        with UPI RRN :998877665544.</p>
        </body></html>
        """
        result = parse_email("bom", html)
        assert result.email_type == "bom_upi_debit_alert"
        assert result.transaction.amount.amount == Decimal("500.00")
        assert result.transaction.balance is None
        assert result.transaction.account_mask == "XX7890"

    def test_parses_large_amount(self):
        html = """
        <html><body>
        <p>Your A/c No xx 3456 debited by INR 1,00,000.00 on 28-MAR-2026
        with UPI RRN :123456789012. A/c Bal is INR 0.13 CR and AVL Bal is INR 0.13 CR</p>
        </body></html>
        """
        result = parse_email("bom", html)
        assert result.transaction.amount.amount == Decimal("100000.00")
        assert result.transaction.balance.amount == Decimal("0.13")

    def test_rejects_non_bom_email(self):
        html = "<html><body>Some random email</body></html>"
        with pytest.raises(ParseError):
            parse_email("bom", html)


class TestKotakImpsCreditParser:
    """Test Kotak IMPS credit alert parser with synthetic HTML."""

    SAMPLE_HTML = """
    <html><body>
    <p>Dear Sample Customer,</p>
    <p>We wish to inform you that your account xx4521 is credited by Rs. 25000.00
    on 12-Apr-2026 for IMPS transaction.</p>
    <p>Please find the details as below:<br>
    Sender Name: Test Sender<br>
    Sender Mobile No: 9190XX1234<br>
    IMPS Reference No: 610202772071<br>
    Remarks : Test Sender</p>
    </body></html>
    """

    def test_parses_kotak_imps_credit(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.email_type == "kotak_imps_credit"
        assert result.bank == "kotak"
        assert result.transaction.direction == "credit"
        assert result.transaction.amount.amount == Decimal("25000.00")
        assert result.transaction.amount.currency == "INR"
        assert result.transaction.account_mask == "xx4521"
        assert result.transaction.channel == "imps"
        assert result.transaction.reference_number == "610202772071"
        assert result.transaction.counterparty == "Test Sender"

    def test_parses_date(self):
        result = parse_email("kotak", self.SAMPLE_HTML)
        assert result.transaction.transaction_date is not None
        assert result.transaction.transaction_date.year == 2026
        assert result.transaction.transaction_date.month == 4
        assert result.transaction.transaction_date.day == 12

    def test_parses_with_inr_prefix(self):
        html = """
        <html><body>
        <p>your account XX7890 is credited by INR 1500.00 on 05-Mar-2026 for IMPS transaction.</p>
        </body></html>
        """
        result = parse_email("kotak", html)
        assert result.email_type == "kotak_imps_credit"
        assert result.transaction.amount.amount == Decimal("1500.00")
        assert result.transaction.account_mask == "XX7890"

    def test_parses_without_optional_fields(self):
        html = """
        <html><body>
        <p>your account xx3456 is credited by Rs. 500.00 on 01-Jan-2026 for IMPS transaction.</p>
        </body></html>
        """
        result = parse_email("kotak", html)
        assert result.email_type == "kotak_imps_credit"
        assert result.transaction.amount.amount == Decimal("500.00")
        assert result.transaction.counterparty is None
        assert result.transaction.reference_number is None

    def test_parses_large_amount_with_commas(self):
        html = """
        <html><body>
        <p>your account xx5678 is credited by Rs. 1,00,000.00 on 28-Feb-2026 for IMPS transaction.</p>
        </body></html>
        """
        result = parse_email("kotak", html)
        assert result.transaction.amount.amount == Decimal("100000.00")


class TestHdfcRupayUpiDebitParser:
    """Test HDFC RuPay credit card UPI debit alerts."""

    SAMPLE_HTML = """
    <html><body>
    <table width="600" align="center">
      <tr><td>Dear Customer,</td></tr>
      <tr>
        <td>
          Rs.44.00 has been debited from your HDFC Bank RuPay Credit Card XX4242
          to merchant123@ptys Sample Merchant on 25-03-26.
          Your UPI transaction reference number is 123456789012.
        </td>
      </tr>
      <tr><td>Warm Regards,<br>HDFC Bank</td></tr>
    </table>
    </body></html>
    """

    def test_parses_rupay_upi_debit(self):
        result = parse_email("hdfc", self.SAMPLE_HTML)
        assert result.email_type == "hdfc_rupay_upi_debit"
        assert result.bank == "hdfc"
        assert result.transaction.direction == "debit"
        assert result.transaction.amount.amount == Decimal("44.00")
        assert result.transaction.transaction_date is not None
        assert result.transaction.transaction_date.year == 2026
        assert result.transaction.transaction_date.month == 3
        assert result.transaction.transaction_date.day == 25
        assert result.transaction.card_mask == "XX4242"
        assert result.transaction.counterparty == "Sample Merchant"
        assert result.transaction.reference_number == "123456789012"
        assert result.transaction.channel == "upi"

    def test_parses_variant_without_merchant_name(self):
        html = """
        <html><body>
        Rs.500.00 has been debited from your HDFC Bank RuPay Credit Card ending 1234
        to VPA merchant@upi on 15-01-26. Your UPI transaction reference number is 123456789012.
        </body></html>
        """
        result = parse_email("hdfc", html)
        assert result.email_type == "hdfc_rupay_upi_debit"
        assert result.transaction.card_mask == "1234"
        assert result.transaction.counterparty == "merchant@upi"
        assert result.transaction.reference_number == "123456789012"
