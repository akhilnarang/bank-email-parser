"""Axis Bank email parsers.

Supported email types:
- axis_cc_reversal: Credit card transaction reversal (refund back to the card)
- axis_cc_debit_alert: Credit card debit (spend) alert, parsed from label/value div layout
- axis_neft_alert: NEFT transfer alert (stub -- awaiting sample email)

Spend and reversal emails share one HTML card layout and differ only in the
'Transaction Status' label/value pair, which is present and reads 'REVERSED'
on a reversal and absent on a spend. Selection therefore keys on that field:
structure alone cannot tell the two apart, and the subject line (which says
'txn. reversed') is not passed to parsers.

Because absence of that field is what marks a spend, failing to *see* the field
is indistinguishable from it not being there, and produces a debit either way.
The two questions are therefore asked separately: the style-based label walk
reads values, while presence is decided by looking for a node whose text is
exactly the label. A label seen but not read is refused, never defaulted.

``card_mask`` carries a downstream inference too — an empty mask instructs
account linking to fall back to bank-only matching, so an unreadable mask can
land a transaction on the wrong account. It is deliberately not gated the way
status is: every Axis CC email carries a mask, so gating it would spool all
Axis transactions over a cosmetic markup change, whereas the status gate only
ever affects the reversal path. The trade is stated here rather than silently
assumed.
"""

import re
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal

from bs4 import BeautifulSoup, Tag

from bank_email_parser.exceptions import ParseError, ParserStubError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BankParser, BaseEmailParser
from bank_email_parser.utils import normalize_whitespace, parse_date, parse_datetime

# CSS style fragments used to identify label vs value divs in the card layout.
# Compared against a whitespace-stripped copy of the style attribute, so
# 'color: #777777' and 'color:#777777' both match.
_LABEL_MARKER = "color:#777777"
_VALUE_MARKER = "color:#333333"

# Field key normalization: strip trailing colons, dots, asterisks, and whitespace
_KEY_CLEANUP = re.compile(r"[\s:.*]+$")

_STYLE_WHITESPACE = re.compile(r"\s+")

# Map normalized label text to internal field names
_FIELD_MAP = {
    "transaction amount": "amount",
    "merchant name": "merchant",
    "axis bank credit card no": "card_mask",
    "date & time": "date_time",
    "date &amp; time": "date_time",
    "available limit": "balance",
    "total credit limit": "total_limit",
    "transaction status": "status",
}

# The only transaction status observed so far. Any other value is treated as
# unrecognized and fails loudly rather than defaulting to a direction: an
# unparsed email is visible, whereas a wrongly signed one silently corrupts
# the ledger.
_STATUS_REVERSED = "reversed"

# Normalized label text used to detect the status field from card text alone,
# independently of the style-based label walk.
_STATUS_LABEL_TEXT = "transaction status"

# Amount pattern: optional currency prefix, then digits (no commas in observed emails,
# but handle them defensively)
_AMOUNT_RE = re.compile(r"([A-Z]{3})\s+([\d,]+(?:\.\d+)?)")


def _parse_money(raw: str) -> Money:
    """Parse 'INR 5830' or 'INR&nbsp;5830' into a Money object."""
    cleaned = normalize_whitespace(raw)
    if m := _AMOUNT_RE.search(cleaned):
        return Money(
            amount=Decimal(m.group(2).replace(",", "")),
            currency=m.group(1),
        )
    raise ParseError(f"Could not parse money from: {raw!r}")


def _tag_text(tag: Tag) -> str:
    """Read a tag's text with descendants joined by a space.

    The separator matters: without it, bs4 concatenates descendant strings
    directly, so a label split across inline markup
    ('Transaction <span>Status:</span>') collapses to 'TransactionStatus:'
    and stops matching its own name.
    """
    return normalize_whitespace(tag.get_text(separator=" ", strip=True))


def _normalize_label(raw: str) -> str:
    """Normalize a label div's text for lookup in _FIELD_MAP.

    Collapses non-breaking spaces and runs of whitespace before stripping
    trailing punctuation, so 'Transaction&nbsp;Status:' and
    'Transaction Status:' normalize alike.
    """
    return _KEY_CLEANUP.sub("", normalize_whitespace(raw)).lower()


def _style_has(tag: Tag, marker: str) -> bool:
    """Whether a tag's style attribute contains a marker, ignoring whitespace."""
    style = tag.get("style", "")
    if not isinstance(style, str):
        return False
    return marker in _STYLE_WHITESPACE.sub("", style)


def _find_value_text(label_div: Tag) -> str | None:
    """Find the value text belonging to a label div, or None if unreadable.

    The value normally sits in the label's immediate next sibling div, but the
    layout sometimes wraps it in an intervening container, so a value-styled
    descendant of that sibling counts too.
    """
    next_el = label_div.find_next_sibling()
    if not isinstance(next_el, Tag) or next_el.name != "div":
        return None

    value_div = next_el if _style_has(next_el, _VALUE_MARKER) else None
    if value_div is None:
        value_div = next(
            (
                descendant
                for descendant in next_el.find_all("div")
                if _style_has(descendant, _VALUE_MARKER)
            ),
            None,
        )
    if value_div is None:
        return None

    return _tag_text(value_div) or None


def _has_status_label_node(soup: BeautifulSoup) -> bool:
    """Whether any node opens with the status label.

    Presence is asked here, not by the style-and-sibling walk that reads
    values. That walk has missed this label four separate ways (unmapped key,
    blank value, styling it did not expect, text split across inline markup),
    and every miss was indistinguishable from the field being absent — the one
    reading that books a debit. So presence does not depend on it succeeding.

    A node *opening* with the label carries it, whether or not its value was
    split into a node of its own: 'Transaction Status:' and
    'Transaction Status: REVERSED' are both the field, and a rendering that
    puts them in one node is still a status a reader can see. Requiring the
    node to be *only* the label would make the field's visibility depend on
    where the markup happens to break, which is the same mistake as depending
    on the walk, one step further out.

    Prose still excludes itself, which is what makes this safe to ask of the
    whole document without inferring a card boundary: a sentence mentioning
    the field ('To check Transaction Status, visit the app') does not begin
    with it. A sentence that *did* begin with it would refuse the parse, which
    is the affordable direction — a refusal is visible in the spool, while
    mistaking a printed REVERSED for silence books its opposite.
    """
    return any(
        _normalize_label(_tag_text(tag)).startswith(_STATUS_LABEL_TEXT)
        for tag in soup.find_all(True)
    )


@dataclass(slots=True)
class _CardFields:
    """Fields recovered from the Axis CC card layout.

    ``values`` holds successfully extracted text. ``labels_seen`` records every
    field whose label is present in the card, whether or not its value could be
    read. The two are tracked separately on purpose: a key missing from
    ``values`` would otherwise mean both 'the bank did not send this field' and
    'we failed to read the field the bank did send'. Those demand opposite
    responses, and collapsing them is what let a reversal be booked as a spend.

    ``status`` is the field this protects. Its absence is read as evidence of a
    spend, so any failure to see it fabricates a direction; it therefore gets a
    presence probe that does not depend on the extraction pipeline succeeding.

    The other fields are not equally inert, and one deserves naming: an
    unreadable ``card_mask`` becomes ``None``, which downstream linking treats
    as a positive instruction to fall back to bank-only account matching, so a
    missing mask can route a transaction to the wrong account. It is not gated
    today — see the module notes — but it does not 'claim nothing'. ``merchant``,
    ``date_time`` and ``balance`` genuinely claim nothing when absent, and
    ``amount`` refuses outright when it cannot be read.
    """

    values: dict[str, str] = field(default_factory=dict)
    labels_seen: set[str] = field(default_factory=set)

    def unreadable(self, name: str) -> bool:
        """Whether a field's label was present but its value could not be read."""
        return name in self.labels_seen and name not in self.values


def _extract_label_value_pairs(soup: BeautifulSoup) -> _CardFields:
    """Extract label/value pairs from Axis card-layout divs.

    Labels have style containing color:#777777, values have color:#333333.
    """
    fields = _CardFields()

    for label_div in soup.find_all("div"):
        if not isinstance(label_div, Tag) or not _style_has(label_div, _LABEL_MARKER):
            continue

        normalized = _normalize_label(_tag_text(label_div))
        if (name := _FIELD_MAP.get(normalized)) is None:
            continue

        fields.labels_seen.add(name)
        if (value := _find_value_text(label_div)) is not None:
            fields.values[name] = value

    # Presence of the status label is decided independently of the walk above,
    # so a label the walk cannot see is still recorded as present-and-unread
    # rather than letting its silence read as absence.
    if _has_status_label_node(soup):
        fields.labels_seen.add("status")

    return fields


class _AxisCcCardLayoutParser(BaseEmailParser):
    """Shared extraction for the Axis CC label/value card layout.

    Subclasses declare the direction they represent and gate themselves on
    the 'Transaction Status' field via ``_accepts_status``.
    """

    def _accepts_status(self, status: str | None) -> bool:
        """Return whether this parser handles the given normalized status."""
        raise NotImplementedError

    def _build_transaction(self, fields: dict[str, str]) -> TransactionAlert:
        raise NotImplementedError

    def parse(self, html: str) -> ParsedEmail:
        soup, _ = self.prepare_html(html)
        fields = _extract_label_value_pairs(soup)

        # A status label we can see but cannot read is the strongest available
        # signal that this body is not understood. Both parsers refuse it rather
        # than let it reach the no-status branch, which books a debit: guessing
        # 'spend' about an unreadable status is exactly how a reversal doubles.
        if fields.unreadable("status"):
            raise ParseError(
                "Axis CC email carries a Transaction Status label whose value "
                "could not be extracted; refusing to infer a direction."
            )

        # A status the layout carries but leaves blank is not the same as one it
        # never carried. Testing truthiness collapses the two, and the collapse
        # is unsafe in one direction only: the missing-status branch books a
        # debit, so a blank status on a reversal would silently invert its sign.
        # Presence is the question here, so presence is what is asked.
        status = None
        if (status_raw := fields.values.get("status")) is not None:
            status = normalize_whitespace(status_raw).strip().lower()

        if not self._accepts_status(status):
            raise ParseError(
                f"Axis CC {self.email_type} does not handle "
                f"transaction status {status!r}."
            )

        if not fields.values.get("amount"):
            raise ParseError(
                f"Could not find Transaction Amount in Axis CC {self.email_type}."
            )

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=self._build_transaction(fields.values),
        )


def _extract_datetime(fields: dict[str, str]) -> tuple[date | None, time | None]:
    """Pull transaction date/time out of the 'Date & Time' field.

    Observed formats use both 4-digit and 2-digit years
    ('04-07-2026, 14:31:00 IST' and '04-07-26, 19:38:34 IST').
    """
    if not (date_raw := fields.get("date_time")):
        return None, None
    if dt := parse_datetime(date_raw):
        return dt.date(), dt.time()
    # If the time portion is malformed, keep the date.
    return parse_date(date_raw.split(",", 1)[0]), None


class AxisCcReversalParser(_AxisCcCardLayoutParser):
    """Axis Bank credit card transaction reversal.

    Subject: "INR <amount> txn. reversed at <merchant>"

    Structurally identical to the spend alert, so it is identified by the
    'Transaction Status: REVERSED' field. The reversal credits the amount
    back to the card and carries no available/total limit fields.
    """

    bank = "axis"
    email_type = "axis_cc_reversal"

    def _accepts_status(self, status: str | None) -> bool:
        return status == _STATUS_REVERSED

    def _build_transaction(self, fields: dict[str, str]) -> TransactionAlert:
        amount_raw = fields["amount"]
        amount = _parse_money(amount_raw)
        transaction_date, transaction_time = _extract_datetime(fields)

        return TransactionAlert(
            direction="credit",
            amount=amount,
            transaction_date=transaction_date,
            transaction_time=transaction_time,
            counterparty=fields.get("merchant"),
            card_mask=fields.get("card_mask"),
            channel="card",
            raw_description=(
                f"Axis CC reversal: {amount_raw} at {fields.get('merchant', 'unknown')}"
            ),
        )


class AxisCcDebitAlertParser(_AxisCcCardLayoutParser):
    """Axis Bank credit card debit (spend) alert.

    Parses the structured HTML card layout with label/value div pairs
    used in Axis CC transaction notification emails.

    This parser hardcodes ``direction="debit"``, so it must refuse any body
    carrying a transaction status: the only observed status marks a reversal,
    which is a credit, and an unrecognized status has no established sign.
    Refusing here means correctness does not depend on parser ordering.

    Known limit: absence of a status is treated as evidence of a spend, which
    holds only for the formats seen so far. A credit format that carries no
    status field at all would be booked as a debit, and nothing in the body
    would reveal the error. The subject line distinguishes these, but parsers
    receive only the body, so this cannot be detected here.
    """

    bank = "axis"
    email_type = "axis_cc_debit_alert"

    def _accepts_status(self, status: str | None) -> bool:
        return status is None

    def _build_transaction(self, fields: dict[str, str]) -> TransactionAlert:
        amount_raw = fields["amount"]
        amount = _parse_money(amount_raw)
        transaction_date, transaction_time = _extract_datetime(fields)

        balance = None
        if balance_raw := fields.get("balance"):
            balance = _parse_money(balance_raw)

        return TransactionAlert(
            direction="debit",
            amount=amount,
            transaction_date=transaction_date,
            transaction_time=transaction_time,
            counterparty=fields.get("merchant"),
            balance=balance,
            card_mask=fields.get("card_mask"),
            channel="card",
            raw_description=(
                f"Axis CC debit: {amount_raw} at {fields.get('merchant', 'unknown')}"
            ),
        )


class AxisNeftAlertParser(BaseEmailParser):
    """Axis Bank NEFT transfer alert.

    Subject: "NEFT is initiated from your account"

    TODO: No sample email available yet. Implement once a sample is obtained.
    Expected fields: amount, account_mask, counterparty, reference_number,
    transaction_date.
    """

    bank = "axis"
    email_type = "axis_neft_alert"

    def parse(self, html: str) -> ParsedEmail:
        raise ParserStubError(
            "Axis NEFT alert parser not yet implemented -- "
            "need a sample email to determine the exact format."
        )


_PARSERS = (
    AxisCcReversalParser(),
    AxisCcDebitAlertParser(),
    AxisNeftAlertParser(),
)


def parse(html: str) -> ParsedEmail:
    return AxisParser().parse(html)


class AxisParser(BankParser):
    bank = "axis"
    parsers = _PARSERS
