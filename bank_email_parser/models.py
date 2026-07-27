"""Pydantic models for parsed email output: Money, TransactionAlert, ParsedEmail."""

from datetime import date, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class Money(BaseModel):
    amount: Decimal = Field(ge=0)
    currency: str = "INR"


class TransactionAlert(BaseModel):
    direction: Literal["debit", "credit", "declined"]
    amount: Money
    transaction_date: date | None = None
    transaction_time: time | None = None
    counterparty: str | None = None
    balance: Money | None = None
    reference_number: str | None = None
    account_mask: str | None = None
    card_mask: str | None = None
    channel: str | None = None  # upi, neft, imps, card, atm, netbanking, etc.
    raw_description: str | None = Field(
        default=None,
        exclude=True,
        repr=False,
        description="Debug-only raw parser context; excluded from serialized output by default.",
    )


class StatementSummary(BaseModel):
    total_amount_due: Money | None = None
    minimum_amount_due: Money | None = None
    due_date: date | None = None
    card_mask: str | None = None
    statement_period_start: date | None = None
    statement_period_end: date | None = None
    raw_description: str | None = Field(
        default=None,
        exclude=True,
        repr=False,
        description="Debug-only raw parser context; excluded from serialized output by default.",
    )


class ParsedEmail(BaseModel):
    """One parsed bank email.

    ``event_time_source`` tells the consumer where the time of the event
    comes from. It states a fact. It does not give a policy.

    ``body``
        The bank writes the time in the message, or the message has no time
        that you can use. This is the default. Almost every parser uses it.

    ``message_arrival``
        The body has no time, and this bank sends the message at the moment
        of the transaction. The consumer can thus use the time of arrival in
        place of the time of the event.

    The consumer decides what to do with ``message_arrival``. It can supply
    the time from the time of arrival. It must also trust that time less than
    a time that the bank writes. Set this value on the parser class. The
    dispatcher copies the value to each result.

    ``identifies_by`` tells the consumer which field shows which event this
    message reports, when the counterparty cannot show it.

    ``counterparty``
        The message names a merchant or a payer. That name shows the event.
        This is the default.

    ``card_mask``
        The message reports a payment of your own card bill. The payer is
        you, so there is no merchant to name. The card mask shows which
        event this is.

    ``none``
        The bank sends no field that shows the event. Two payments of the
        same amount on the same day are thus alike in every field. The
        consumer must ask a person, or keep both rows.
    """

    email_type: str
    bank: str
    transaction: TransactionAlert | None = None
    statement: StatementSummary | None = None
    password_hint: str | None = None

    event_time_source: Literal["body", "message_arrival"] = "body"
    identifies_by: Literal["counterparty", "card_mask", "none"] = "counterparty"
