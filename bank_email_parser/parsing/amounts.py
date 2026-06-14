"""Amount and currency parsing helpers."""

import re
from decimal import Decimal, InvalidOperation

from bank_email_parser.models import Money

# Currency prefixes/symbols stripped before parsing. ``INR``/``Rs``/``Rs.`` are
# matched case-insensitively with an optional trailing separator.
_CURRENCY_RE = re.compile(r"(?:₹|INR|Rs\.?)\s*", re.IGNORECASE)


def parse_amount(raw: str) -> Decimal | None:
    """Parse an amount string like '₹57,055.44' or 'INR 5,000.00' into Decimal."""
    cleaned = _CURRENCY_RE.sub("", raw)
    cleaned = cleaned.replace(",", "").replace("\xa0", "").replace("\u200c", "")
    cleaned = cleaned.strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_money(raw: str, currency: str = "INR") -> Money | None:
    """Parse a raw amount string into a Money object. Returns None on failure."""
    amount = parse_amount(raw)
    if amount is None:
        return None
    return Money(amount=amount, currency=currency)
