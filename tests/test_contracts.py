"""Contract-level tests for privacy defaults and parsed transaction fields."""

from decimal import Decimal
from datetime import date, time

from bank_email_parser.api import parse_email


def test_equitas_parser_populates_transaction_time() -> None:
    html = """
    <html><body>
      <p>
        We inform you that INR 1,500.00 was spent on your Equitas Credit Card
        ending with 1234 at SAMPLE STORE on 15-01-2026 at 02:23:51 pm.
        Your available balance is INR 50,000.00.
      </p>
    </body></html>
    """

    result = parse_email("equitas", html)

    assert result.transaction.amount.amount == Decimal("1500.00")
    assert result.transaction.transaction_time == time(14, 23, 51)


def test_indusind_cc_parser_populates_transaction_time() -> None:
    html = """
    <html><body>
      <p>
        The transaction on your IndusInd Bank Credit Card ending 1234
        for INR 1,000.00 on 15-01-2026 12:00:01 am at SAMPLE MERCHANT
        is Approved. Available Limit: INR 50,000.00.
      </p>
    </body></html>
    """

    result = parse_email("indusind", html)

    assert result.email_type == "indusind_cc_transaction_alert"
    assert result.transaction.transaction_time == time(0, 0, 1)


def test_indusind_dc_parser_populates_transaction_time() -> None:
    html = """
    <html><body>
      <p>
        transaction initiated via your IndusInd Bank Debit Card ending 5678 is successful
      </p>
      <table>
        <tr><td>Merchant Name</td><td>SAMPLE MERCHANT</td></tr>
        <tr><td>Amount*</td><td>INR 1,300.00</td></tr>
        <tr><td>Date</td><td>15-01-2026</td></tr>
        <tr><td>Time</td><td>11:22:33 pm</td></tr>
      </table>
      <p>The balance available in your account is INR 9,999.00</p>
    </body></html>
    """

    result = parse_email("indusind", html)

    assert result.email_type == "indusind_dc_transaction_alert"
    assert result.transaction.transaction_time == time(23, 22, 33)


def test_raw_description_is_excluded_from_serialized_output_by_default() -> None:
    html = """
    <html><body>
      <p>
        We inform you that INR 1,500.00 was spent on your Equitas Credit Card
        ending with 1234 at SAMPLE STORE on 15-01-2026 at 02:23:51 pm.
        Your available balance is INR 50,000.00.
      </p>
    </body></html>
    """

    result = parse_email("equitas", html)

    assert result.transaction.raw_description is not None
    assert "raw_description" not in result.model_dump()["transaction"]


def test_hsbc_invalid_time_does_not_degrade_to_midnight() -> None:
    html = """
    <html><body>
      <p>
        your Credit card no ending with 1234,has been used for INR 1500.00
        for payment to SAMPLE MERCHANT on 15 Jan 2026 at 99:99.
      </p>
    </body></html>
    """

    result = parse_email("hsbc", html)

    assert result.transaction.transaction_date is not None
    assert result.transaction.transaction_time is None


def test_indusind_cc_payment_parser_still_sets_transaction_date() -> None:
    html = """
    <html><body>
      <p>
        Thank you for your Payment of INR 1,500.00 towards your IndusInd Bank Credit Card.
        Your payment is credited to your Credit Card account on 15/01/2026.
      </p>
    </body></html>
    """

    result = parse_email("indusind", html)

    assert result.email_type == "indusind_cc_payment_alert"
    assert result.transaction.transaction_date == date(2026, 1, 15)
