"""SBI (State Bank of India) email parsers — credit card and debit card.

Supported email types:
- sbi_cc_transaction_alert: Credit card spend alert in INR
- sbi_cc_fx_transaction_alert: Credit card spend alert in a foreign currency (USD, EUR, etc.)
- sbi_cc_emandate_debit: Recurring e-mandate (Standing Instruction) debit success
- sbi_cc_transaction_declined: Standing Instruction transaction declined (no funds moved)
- sbi_dc_transaction_alert: Debit card POS/ECOM purchase alert
- sbi_payment_ack: Credit card payment acknowledgment from BillDesk
"""

import re

from bs4 import BeautifulSoup

from bank_email_parser.exceptions import ParseError
from bank_email_parser.models import Money, ParsedEmail, TransactionAlert
from bank_email_parser.parsers.base import BankParser, BaseEmailParser
from bank_email_parser.utils import (
    extract_table_pairs,
    normalize_whitespace,
    parse_amount,
    parse_date,
    parse_datetime,
)

# ISO 4217 currency codes that may appear in SBI CC foreign-currency alerts.
# Extend this list as new currencies are encountered.
_KNOWN_CURRENCIES = (
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "AUD",
    "CAD",
    "CHF",
    "SGD",
    "AED",
    "HKD",
    "NZD",
    "SEK",
    "NOK",
    "DKK",
    "MYR",
    "THB",
    "ZAR",
)
_CURRENCY_RE = "|".join(_KNOWN_CURRENCIES)


class SbiCcTransactionAlertParser(BaseEmailParser):
    """SBI Credit Card transaction alert (debit/spend) in INR.

    Matches both SBI Card and CASHBACK SBI Card variants:
      'Rs.1,500.00 spent on your SBI Credit Card ending 1234
       at SAMPLE MERCHANT on 15/01/26.'
    CASHBACK variant may have prefix: 'This is to inform you that, '
    """

    bank = "sbi"
    email_type = "sbi_cc_transaction_alert"

    _pattern = re.compile(
        r"Rs\.([\d,]+\.\d{2})\s+"
        r"spent on your SBI Credit Card ending (\d{4})\s+"
        r"at (.+?) on (\d{2}/\d{2}/\d{2})",
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse SBI CC transaction alert.")

        if (amount := parse_amount(match.group(1))) is None:
            raise ParseError(f"Could not parse amount: {match.group(1)!r}")

        txn_date = parse_date(match.group(4))

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                counterparty=match.group(3).strip(),
                card_mask=match.group(2),
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class SbiCcFxTransactionAlertParser(BaseEmailParser):
    """SBI Credit Card transaction alert for foreign-currency (non-INR) spends.

    Matches emails like:
      'This is to inform you that, USD10.00 spent on your SBI Credit Card
       ending 5678 at SAMPLE MERCHANT on 15/01/26.'

    The amount is prefixed by a known ISO 4217 currency code (e.g. USD, EUR)
    rather than the Rs. prefix used in INR alerts.
    """

    bank = "sbi"
    email_type = "sbi_cc_fx_transaction_alert"

    _pattern = re.compile(
        rf"({_CURRENCY_RE})"  # group 1: currency code
        r"([\d,]+\.\d{2})\s+"  # group 2: amount digits
        r"spent on your SBI Credit Card ending (\d{4})\s+"  # group 3: card mask
        r"at (.+?) on (\d{2}/\d{2}/\d{2})",  # groups 4,5: merchant, date
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse SBI CC FX transaction alert.")

        currency = match.group(1)
        if (amount := parse_amount(match.group(2))) is None:
            raise ParseError(f"Could not parse amount: {match.group(2)!r}")

        txn_date = parse_date(match.group(5))

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount, currency=currency),
                transaction_date=txn_date,
                counterparty=match.group(4).strip(),
                card_mask=match.group(3),
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class SbiCcEMandateParser(BaseEmailParser):
    """SBI Credit Card recurring e-mandate debit success notification.

    Matches emails like:
      'Transaction of Rs.200.00 at SAMPLE MERCHANT against E-mandate
       (SiHub ID - ABC123DEF4) registered by you at merchant has been
       debited to your SBI Credit Card ending 5678 on 15-01-26.'
    """

    bank = "sbi"
    email_type = "sbi_cc_emandate_debit"

    _pattern = re.compile(
        r"Transaction of Rs\.([\d,]+\.\d{2})\s+"  # group 1: amount
        r"at (.+?)\s+against E-mandate\s+"  # group 2: merchant
        r"\(SiHub ID\s*-\s*(\S+)\)",  # group 3: SiHub ID
    )
    # Date pattern: 'debited to your SBI Credit Card ending 5678 on 15-01-26'
    _card_date_pattern = re.compile(
        r"debited to your SBI Credit Card ending (\d{4})\s+on (\d{2}-\d{2}-\d{2})"
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse SBI CC e-mandate debit.")

        if (amount := parse_amount(match.group(1))) is None:
            raise ParseError(f"Could not parse amount: {match.group(1)!r}")

        sihub_id = match.group(3)
        card_mask = None
        txn_date = None
        if cd_match := self._card_date_pattern.search(text):
            card_mask = cd_match.group(1)
            txn_date = parse_date(cd_match.group(2))

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                counterparty=match.group(2).strip(),
                card_mask=card_mask,
                reference_number=sihub_id,
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class SbiCcDeclinedParser(BaseEmailParser):
    """SBI Credit Card transaction declined notification.

    Matches emails like:
      'Standing Instruction (SI) transaction of USD10.00 on your SBI
       Credit Card ending 5678 at merchant SAMPLE MERCHANT on date 15-01-26
       has been declined basis RBI guidelines.'

    These are informational -- no funds actually moved.  Recorded as
    direction='declined' so downstream consumers can distinguish them
    from actual debits/credits.
    """

    bank = "sbi"
    email_type = "sbi_cc_transaction_declined"

    # Matches both INR (Rs.) and foreign currency (USD, EUR, …) amounts.
    _pattern = re.compile(
        r"(?:Standing Instruction \(SI\)|SI)\s+transaction of\s+"
        rf"(?:Rs\.([\d,]+\.\d{{2}})|({_CURRENCY_RE})([\d,]+\.\d{{2}}))\s+"
        r"on your SBI Credit Card ending (\d{4})\s+"  # group 4: card mask
        r"at merchant (.+?) on date (\d{2}-\d{2}-\d{2})",  # groups 5,6: merchant, date
    )

    def parse(self, html: str) -> ParsedEmail:
        _, text = self.prepare_html(html)

        if not (match := self._pattern.search(text)):
            raise ParseError("Could not parse SBI CC transaction declined.")

        # Groups: 1=INR digits, 2=FX currency code, 3=FX digits
        if match.group(1) is not None:
            # INR amount
            currency = "INR"
            raw_amount = match.group(1)
        else:
            currency = match.group(2)
            raw_amount = match.group(3)

        if (amount := parse_amount(raw_amount)) is None:
            raise ParseError(f"Could not parse amount: {raw_amount!r}")

        card_mask = match.group(4)
        txn_date = parse_date(match.group(6))

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="declined",
                amount=Money(amount=amount, currency=currency),
                transaction_date=txn_date,
                counterparty=match.group(5).strip(),
                card_mask=card_mask,
                channel="card",
                raw_description=match.group(0).strip(),
            ),
        )


class SbiDcTransactionAlertParser(BaseEmailParser):
    """SBI debit card POS/ECOM purchase alert.

    A label/value table inside the bank's "Transaction Alert" shell:

      Terminal Owner Name  SAMPLE MERCHANT
      Terminal Id          ABC00000
      Date & Time          Jan 15, 2026, 15:58
      Transaction Number   000000000000
      Amount (INR)         1234.00
      Last 4 Digit of Card X0000
      Transaction Type     PURCHASE
      Channel              POS / ECOM
      City                 Mumbai
      Location             SAMPLE MERCHANT

    Only ``PURCHASE`` rows are accepted (a debit from the linked savings
    account); an unfamiliar Transaction Type raises ``ParseError`` so a
    new shape surfaces as a failure instead of a silently mislabelled
    debit. The terminal owner is the counterparty and the transaction
    number is the reference.
    """

    bank = "sbi"
    email_type = "sbi_dc_transaction_alert"

    _ANCHOR = "using your sbi debit card"

    _EXPECTED_KEYS = {
        "terminal owner name",
        "date time",
        "transaction number",
        "amount inr",
        "last 4 digit of card",
        "transaction type",
    }

    def parse(self, html: str) -> ParsedEmail:
        soup, text = self.prepare_html(html)

        if self._ANCHOR not in text.lower():
            raise ParseError("Not an SBI debit card transaction alert.")

        pairs = extract_table_pairs(soup)
        if missing := self._EXPECTED_KEYS - pairs.keys():
            raise ParseError(
                f"SBI debit card alert is missing fields: {sorted(missing)}"
            )

        if pairs["transaction type"].strip().upper() != "PURCHASE":
            raise ParseError(
                f"Unhandled SBI debit card transaction type: "
                f"{pairs['transaction type']!r}"
            )

        if (amount := parse_amount(pairs["amount inr"])) is None:
            raise ParseError(f"Could not parse amount: {pairs['amount inr']!r}")

        # "Date & Time" is a required table field; an unparseable value is a
        # format change that must fail loudly, not a silently dateless debit.
        if (txn_dt := parse_datetime(pairs["date time"])) is None:
            raise ParseError(f"Could not parse date/time: {pairs['date time']!r}")

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="debit",
                amount=Money(amount=amount),
                transaction_date=txn_dt.date(),
                transaction_time=txn_dt.time(),
                counterparty=pairs["terminal owner name"].strip(),
                card_mask=pairs["last 4 digit of card"].strip(),
                reference_number=pairs["transaction number"].strip(),
                channel="card",
            ),
        )


class SbiPaymentAckParser(BaseEmailParser):
    """SBI Card payment acknowledgment from BillDesk.

    Parses semi-structured HTML with separate <p> tags containing:
      Card No, Payment Amount, Payment Date, Transaction Identification Number.
    """

    bank = "sbi"
    email_type = "sbi_payment_ack"

    _card_pattern = re.compile(r"Card\s+No\s*:\s*xxxx\s+xxxx\s+xxxx\s+(\d{4})")
    _amount_pattern = re.compile(
        r"Payment\s+Amount\s*\(Rs\s*Ps\)\s*:\s*([\d,]+(?:\.\d+)?)"
    )
    _date_pattern = re.compile(r"Payment\s+Date\s*:\s*(\d{1,2}\w*\s+\w+\s+\d{4})")
    _ref_pattern = re.compile(r"Transaction\s+Identification\s+Number\s*:\s*(\S+)")

    _ordinal_suffix = re.compile(r"(\d+)(?:st|nd|rd|th)\b")

    def parse(self, html: str) -> ParsedEmail:
        # Remove <sup> tags (and their contents) using BeautifulSoup's
        # decompose() so '18<sup>th</sup>' becomes '18' in plain text.
        soup = BeautifulSoup(html, "html.parser")
        for sup in soup.find_all("sup"):
            sup.decompose()
        text = normalize_whitespace(soup.get_text(separator=" ", strip=True))

        if not (card_match := self._card_pattern.search(text)):
            raise ParseError(
                "Could not parse SBI payment acknowledgment (no card number)."
            )

        if not (amount_match := self._amount_pattern.search(text)):
            raise ParseError("Could not parse SBI payment acknowledgment (no amount).")

        if (amount := parse_amount(amount_match.group(1))) is None:
            raise ParseError(f"Could not parse amount: {amount_match.group(1)!r}")

        # Intentional graceful degradation (v0.1): if the date is missing or
        # its format changes, we proceed with transaction_date=None rather than
        # raising, so the rest of the fields are still surfaced.
        txn_date = None
        if date_match := self._date_pattern.search(text):
            raw_date = date_match.group(1).strip()
            # Safety net: strip ordinal suffixes ('18th' -> '18') for cases
            # where the ordinal text appears outside <sup> tags.  When the
            # ordinal IS inside <sup> tags, _sup_tag already removed it above,
            # so this is a no-op -- but we keep it for robustness.
            stripped_date = self._ordinal_suffix.sub(r"\1", raw_date)
            txn_date = parse_date(stripped_date)

        reference_number = None
        if ref_match := self._ref_pattern.search(text):
            reference_number = ref_match.group(1)

        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(
                direction="credit",
                amount=Money(amount=amount),
                transaction_date=txn_date,
                counterparty="Payment received",
                card_mask=card_match.group(1),
                reference_number=reference_number,
                channel="card",
                raw_description=None,
            ),
        )


_PARSERS = (
    SbiCcTransactionAlertParser(),
    SbiCcFxTransactionAlertParser(),
    SbiCcEMandateParser(),
    SbiCcDeclinedParser(),
    # Debit card purchase: gated on the "using your SBI debit card" anchor
    # plus the label/value table, so it cannot shadow the CC shapes.
    SbiDcTransactionAlertParser(),
    SbiPaymentAckParser(),
)


def parse(html: str) -> ParsedEmail:
    return SbiParser().parse(html)


class SbiParser(BankParser):
    bank = "sbi"
    parsers = _PARSERS
