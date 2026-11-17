import pytest
from bank_email_parser import parse_email
from bank_email_parser.exceptions import ParseError

_REMITTANCE_CONFIRMATION_HTML = """
<html><body>
  <h2>Foreign Remittance Confirmation</h2>
  <p>Dear Customer, Your foreign remittance AU00000000000000 has been booked
  successfully as per your instruction.</p>
  <table>
    <tr><td>Currency and Amount</td><td>USD 100</td></tr>
    <tr><td>INR Amount</td><td>&#8377;9000.00</td></tr>
  </table>
</body></html>
"""

_REMITTANCE_REQUEST_HTML = """
<html><body>
  <p>Dear Customer, Your request AU00000000000000 to remit USD 100 has been
  received &amp; is currently under process.</p>
</body></html>
"""


@pytest.mark.parametrize(
    ("html", "email_type"),
    [
        (_REMITTANCE_CONFIRMATION_HTML, "au_foreign_remittance_notice"),
        (_REMITTANCE_REQUEST_HTML, "au_remittance_request_notice"),
    ],
)
def test_au_remittance_emails_are_non_transaction_notices(html, email_type):
    parsed = parse_email("au", html)

    assert parsed.email_type == email_type
    assert parsed.transaction is None
    assert parsed.statement is None


def test_au_welcome_kit_email_is_not_a_notice():
    with pytest.raises(ParseError):
        parse_email(
            "au",
            "<p>Your AU Small Finance Bank Welcome Kit for account number: "
            "XX0000, has been delivered.</p>",
        )
