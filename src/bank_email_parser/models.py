"""Pydantic models for parsed email output: Money, TransactionAlert, ParsedEmail."""
from datetime import date, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class Money(BaseModel):
    amount: Decimal
    currency: str = "INR"


class TransactionAlert(BaseModel):
    direction: Literal["debit", "credit"]
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
        description="Debug-only raw parser context; excluded from serialized output by default.",
    )


class ParsedEmail(BaseModel):
    email_type: str
    bank: str
    transaction: TransactionAlert
