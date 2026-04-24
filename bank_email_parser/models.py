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
    email_type: str
    bank: str
    transaction: TransactionAlert | None = None
    statement: StatementSummary | None = None
    password_hint: str | None = None
