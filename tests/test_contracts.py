"""Contract-level tests for privacy defaults and parsed transaction fields."""

from datetime import date, time
from decimal import Decimal

from bank_email_parser.api import parse_email
from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser, parse_with_parsers


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

    assert result.transaction is not None
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
    assert result.transaction is not None
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
    assert result.transaction is not None
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

    assert result.transaction is not None
    assert result.transaction.raw_description is not None
    assert "raw_description" not in result.model_dump()["transaction"]


def test_raw_description_is_excluded_from_model_repr_by_default() -> None:
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

    assert result.transaction is not None
    assert result.transaction.raw_description is not None
    assert "raw_description" not in repr(result)
    assert "raw_description" not in repr(result.transaction)
    assert "We inform you that" not in repr(result.transaction)


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

    assert result.transaction is not None
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
    assert result.transaction is not None
    assert result.transaction.transaction_date == date(2026, 1, 15)


def test_parse_with_parsers_reuses_prepared_html_across_fallbacks(monkeypatch) -> None:
    calls = 0
    original = BaseEmailParser._build_prepared_email

    def counted_build(html: str):
        nonlocal calls
        calls += 1
        return original(html)

    monkeypatch.setattr(
        BaseEmailParser,
        "_build_prepared_email",
        staticmethod(counted_build),
    )

    class FirstParser(BaseEmailParser):
        bank = "test"
        email_type = "first"

        def parse(self, html: str) -> ParsedEmail:
            self.prepare_html(html)
            raise ParseError("not this one")

    class SecondParser(BaseEmailParser):
        bank = "test"
        email_type = "second"

        def parse(self, html: str) -> ParsedEmail:
            self.prepare_html(html)
            return ParsedEmail(
                email_type=self.email_type,
                bank=self.bank,
                transaction=TransactionAlert(
                    direction="debit",
                    amount=Money(amount=Decimal("1.00")),
                ),
            )

    result = parse_with_parsers(
        "test",
        "<html><body><p>sample</p></body></html>",
        (FirstParser(), SecondParser()),
    )

    assert result.email_type == "second"
    assert calls == 1


def test_a_parser_declares_the_default_time_source() -> None:
    """A parser that says nothing declares that the body states the time."""

    class _QuietParser(BaseEmailParser):
        bank = "samplebank"
        email_type = "samplebank_debit_alert"

        def parse(self, html: str) -> ParsedEmail:
            return ParsedEmail(
                email_type=self.email_type,
                bank=self.bank,
                transaction=TransactionAlert(
                    direction="debit", amount=Money(amount=Decimal("1.00"))
                ),
            )

    assert _QuietParser.event_time_source == "body"
    result = parse_with_parsers("samplebank", "<p>x</p>", (_QuietParser(),))
    assert result.event_time_source == "body"


def test_the_dispatcher_copies_the_time_source_to_the_result() -> None:
    """The caller receives a model and not the class. Thus the dispatcher must
    copy the declaration to each result."""

    class _ArrivalParser(BaseEmailParser):
        bank = "samplebank"
        email_type = "samplebank_transfer_debit_alert"
        event_time_source = "message_arrival"

        def parse(self, html: str) -> ParsedEmail:
            return ParsedEmail(
                email_type=self.email_type,
                bank=self.bank,
                transaction=TransactionAlert(
                    direction="debit", amount=Money(amount=Decimal("1.00"))
                ),
            )

    result = parse_with_parsers("samplebank", "<p>x</p>", (_ArrivalParser(),))
    assert result.event_time_source == "message_arrival"


def test_a_parser_cannot_declare_an_unknown_time_source() -> None:
    """The base class checks the value when you define the class. A wrong
    value thus fails at import and not at run time."""
    import pytest

    with pytest.raises(TypeError, match="event_time_source"):

        class _BadParser(BaseEmailParser):
            bank = "samplebank"
            email_type = "samplebank_typo_alert"
            event_time_source = "arrival"

            def parse(self, html: str) -> ParsedEmail:  # pragma: no cover
                raise NotImplementedError


def test_the_hdfc_neft_debit_parser_declares_message_arrival() -> None:
    """This email has no time in the body, and HDFC sends it at the moment of
    the transaction. The consumer needs this fact to supply the time."""
    from bank_email_parser.parsers.hdfc import HdfcAccountNeftDebitParser

    assert HdfcAccountNeftDebitParser.event_time_source == "message_arrival"


def test_a_subclass_cannot_escape_the_time_source_check() -> None:
    """A subclass can inherit bank and email_type and declare only
    event_time_source. The base class must still check that value. If it does
    not, a wrong value reaches the consumer, which reads it as "body" and
    gives the row the wide window."""
    import pytest

    class _Parent(BaseEmailParser):
        bank = "samplebank"
        email_type = "samplebank_parent_alert"

        def parse(self, html: str) -> ParsedEmail:  # pragma: no cover
            raise NotImplementedError

    with pytest.raises(TypeError, match="event_time_source"):

        class _Child(_Parent):
            event_time_source = "arrival"
