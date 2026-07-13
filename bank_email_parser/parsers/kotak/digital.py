"""Kotak811 and digital transaction email parsers."""

import re

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BaseEmailParser
from bank_email_parser.utils import parse_amount


def _extract_labeled_grid_value(soup, label: str) -> str | None:
    """Read a value from Kotak's labeled detail grid.

    The grid is a header row of ``<th>`` labels (``Transaction ID``,
    ``Amount in ₹``, ``Status``) followed by a row of ``<td>`` values, aligned
    by column. Match the header cell whose text *equals* ``label`` (case-
    insensitive), then return the value in the same column of the next row.

    Equality — not substring — is deliberate: the template wraps the whole
    body in nested tables, so a substring scan matches the outer wrapper row
    and returns boilerplate ("If you are unable to view ... click here")
    instead of the real value.
    """
    target = label.strip().lower()
    rows = soup.find_all("tr")
    for i, row in enumerate(rows):
        # Direct-child cells only: a recursive scan makes an outer wrapper
        # row absorb the nested grid's cells, so the label would be found in
        # the wrapper row at the wrong column and the "next row" lookup would
        # read a sibling label instead of the value.
        cells = row.find_all(["td", "th"], recursive=False)
        col = next(
            (
                j
                for j, c in enumerate(cells)
                if c.get_text(strip=True).lower() == target
            ),
            None,
        )
        if col is None:
            continue
        for next_row in rows[i + 1 :]:
            value_cells = next_row.find_all(["td", "th"], recursive=False)
            if col < len(value_cells):
                value = value_cells[col].get_text(strip=True)
                return value or None
            # A shorter following row (e.g. a rowspan'd Status-only row)
            # doesn't reach this column — keep looking.
        return None
    return None


class KotakDigitalTransactionParser(BaseEmailParser):
    """Kotak811 digital transaction (minimal data).

    The "Transaction Successful" template carries no direction, account
    mask, or counterparty — only amount, transaction ID, and status.
    Every observed instance (Feb/May/Jun/Jul 2026) was the add-money /
    self-transfer flow moving money INTO the Kotak account, and Kotak's
    outgoing debits arrive under dedicated templates ("Card transaction -
    successful", "Credit Card bill paid successfully!"), so this parses
    as a credit. The monthly bank statement reconciles on
    (date, amount, direction) and acts as the safety net.
    """

    bank = "kotak"
    email_type = "kotak_digital_transaction"

    _amount_pattern = re.compile(
        r"Your\s+transaction\s+of\s+(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"has\s+been\s+processed\s+successfully",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        soup, text = self.prepare_html(html)
        if not (match := self._amount_pattern.search(text)):
            raise ParseError("Could not parse Kotak digital transaction.")
        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        reference_number = _extract_labeled_grid_value(soup, "transaction id")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount),
                reference_number=reference_number,
                raw_description=match.group(0).strip(),
            ),
        )


class Kotak811TransactionParser(BaseEmailParser):
    """Kotak811 app transaction (from no-reply@kotak.com)."""

    bank = "kotak"
    email_type = "kotak811_transaction"

    _amount_pattern = re.compile(
        r"Your\s+transaction\s+for\s+(?:Rs\.?|₹|INR)\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"has\s+been\s+processed\s+successfully",
        re.IGNORECASE,
    )
    # Constrain the token to an alphanumeric run so glued punctuation or
    # boilerplate after "Transaction ID:" cannot leak into the reference.
    _txn_id_pattern = re.compile(
        r"Transaction\s+ID\s*:\s*(?P<txn_id>[A-Za-z0-9]+)",
        re.IGNORECASE,
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)
        if not (match := self._amount_pattern.search(text)):
            raise ParseError("Could not parse Kotak811 transaction.")
        if (amount := parse_amount(match.group("amount"))) is None:
            raise ParseError(f"Could not parse amount: {match.group('amount')!r}")

        reference_number = None
        if txn_match := self._txn_id_pattern.search(text):
            reference_number = txn_match.group("txn_id")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                reference_number=reference_number,
                raw_description=match.group(0).strip(),
            ),
        )
