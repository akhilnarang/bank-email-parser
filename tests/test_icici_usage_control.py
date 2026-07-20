import pytest
from bank_email_parser import parse_email
from bank_email_parser.exceptions import ParseError

_USAGE_CONTROL_HTML = """
<html><body>
  <p>We have applied the Usage Settings on your ICICI Bank Credit Card XX1234.</p>
  <p>Open Manage Your Cards, then Manage Credit Card Usage.</p>
</body></html>
"""


def test_icici_usage_control_is_a_non_transaction_notice():
    parsed = parse_email("icici", _USAGE_CONTROL_HTML)

    assert parsed.bank == "icici"
    assert parsed.email_type == "icici_cc_usage_control_notice"
    assert parsed.transaction is None
    assert parsed.statement is None


def test_icici_usage_control_wins_over_generic_statement_footer_copy():
    parsed = parse_email(
        "icici",
        _USAGE_CONTROL_HTML
        + "<p>Download the app to view your statement and attachments.</p>",
    )

    assert parsed.email_type == "icici_cc_usage_control_notice"


def test_icici_statement_wins_when_its_footer_mentions_usage_controls():
    parsed = parse_email(
        "icici",
        """
        <p>Your ICICI account statement is attached.</p>
        <p>Use your password to open the attachment.</p>
        <p>Review Usage Settings for your ICICI Bank Credit Card under
        Manage Credit Card Usage.</p>
        """,
    )

    assert parsed.email_type == "icici_account_statement"


def test_icici_usage_control_requires_the_specific_management_copy():
    with pytest.raises(ParseError):
        parse_email(
            "icici",
            "<p>Your ICICI Bank Credit Card usage was processed successfully.</p>",
        )
