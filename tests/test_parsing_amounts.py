"""Unit tests for amount/currency parsing helpers."""

from decimal import Decimal

import pytest
from bank_email_parser.parsing.amounts import parse_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("₹5,000.00", Decimal("5000.00")),
        ("Rs. 5,000.00", Decimal("5000.00")),
        ("Rs 5,000.00", Decimal("5000.00")),
        ("INR 5,000.00", Decimal("5000.00")),
        ("inr 5,000.00", Decimal("5000.00")),
        ("INR5000", Decimal("5000")),
        ("12,345.00", Decimal("12345.00")),
    ],
)
def test_parse_amount_strips_currency(raw, expected):
    assert parse_amount(raw) == expected


def test_parse_amount_returns_none_on_garbage():
    assert parse_amount("not a number") is None
