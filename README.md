# bank-email-parser

Parse Indian bank transaction alert emails into structured data. Feed it the HTML body of an email, get back a Pydantic model with the transaction amount, direction, date, counterparty, and other details.

## Supported Banks

| Bank | ID | Email Types |
|------|----|-------------|
| Axis Bank | `axis` | Credit card debit alert; NEFT alert (stub) |
| Equitas SFB | `equitas` | Credit card transaction alert |
| HDFC Bank | `hdfc` | UPI debit/credit, card debit (CC & DC), reversal, cheque clearing, RuPay UPI debit, IMPS alert |
| HSBC | `hsbc` | Credit card debit, credit card payment received |
| ICICI Bank | `icici` | CC transaction, CC payment, bank transfer (IMPS/NEFT/RTGS), net banking, CC reversal (stub) |
| IDFC FIRST | `idfc` | Account credit/debit (RTGS/NEFT/IMPS), credit card debit |
| IndusInd Bank | `indusind` | CC transaction, CC payment, debit card transaction, account alert (UPI) |
| Kotak Bank | `kotak` | Debit card POS, UPI payment, digital transaction, Kotak811 transaction, CC bill payment |
| OneCard | `onecard` | Credit card debit alert |
| SBI Card | `sbi` | CC transaction (INR), CC transaction (foreign currency), e-mandate debit, transaction declined, payment acknowledgment |
| Slice | `slice` | UPI/IMPS/NEFT credit/debit, IMPS/RTGS/NEFT transfer, CC bill repayment |
| Union Bank | `uboi` | Debit alert (IMPS/NEFT/RTGS) |

### Full email type list

| Bank | `email_type` | Description |
|------|-------------|-------------|
| `axis` | `axis_cc_debit_alert` | CC spend alert (label/value div layout) |
| `axis` | `axis_neft_alert` | NEFT transfer (stub) |
| `equitas` | `equitas_cc_alert` | CC spend alert |
| `hdfc` | `hdfc_upi_alert` | UPI debit or credit |
| `hdfc` | `hdfc_card_debit_alert` | CC or DC POS/online debit |
| `hdfc` | `hdfc_reversal_alert` | Card transaction reversal/refund |
| `hdfc` | `hdfc_cheque_clearing` | Cheque clearing notification |
| `hdfc` | `hdfc_rupay_upi_debit` | RuPay credit card UPI debit |
| `hdfc` | `hdfc_imps_alert` | Account IMPS transfer alert |
| `hsbc` | `hsbc_cc_debit_alert` | CC purchase |
| `hsbc` | `hsbc_cc_credit_alert` | CC payment received |
| `icici` | `icici_cc_transaction_alert` | CC purchase (supports INR + foreign currency) |
| `icici` | `icici_cc_payment_alert` | CC payment received |
| `icici` | `icici_bank_transfer_alert` | Bank account IMPS/NEFT/RTGS debit |
| `icici` | `icici_net_banking_alert` | Net banking payment |
| `icici` | `icici_cc_reversal` | CC reversal (stub) |
| `idfc` | `idfc_account_alert` | Savings account RTGS/NEFT/IMPS credit or debit |
| `idfc` | `idfc_cc_debit_alert` | CC spend alert |
| `indusind` | `indusind_cc_transaction_alert` | CC spend alert (inline prose) |
| `indusind` | `indusind_dc_transaction_alert` | DC transaction alert (intro + HTML table) |
| `indusind` | `indusind_account_alert` | Account credit/debit alert (UPI) |
| `indusind` | `indusind_cc_payment_alert` | CC payment confirmation |
| `kotak` | `kotak_card_transaction` | Debit card POS transaction |
| `kotak` | `kotak_upi_payment` | Kotak811 UPI payment |
| `kotak` | `kotak_digital_transaction` | Kotak811 digital transaction (minimal data) |
| `kotak` | `kotak811_transaction` | Kotak811 app transaction (from no-reply@kotak.com) |
| `kotak` | `kotak_cc_bill_paid` | CC bill payment confirmation (paying another bank's CC) |
| `onecard` | `onecard_debit_alert` | CC spend alert (structured HTML) |
| `sbi` | `sbi_cc_transaction_alert` | CC spend alert in INR |
| `sbi` | `sbi_cc_fx_transaction_alert` | CC spend in a foreign currency (USD, EUR, etc.) |
| `sbi` | `sbi_cc_emandate_debit` | Recurring e-mandate (Standing Instruction) debit |
| `sbi` | `sbi_cc_transaction_declined` | SI transaction declined (no funds moved; amount still recorded) |
| `sbi` | `sbi_payment_ack` | CC payment acknowledgment from BillDesk |
| `slice` | `slice_transaction_alert` | UPI/IMPS/NEFT credit or debit ('received/sent via' pattern) |
| `slice` | `slice_transfer_alert` | IMPS/RTGS/NEFT debit ('transaction of ₹X from' pattern) |
| `slice` | `slice_cc_payment_alert` | Slice CC bill repayment received |
| `uboi` | `uboi_debit_alert` | Account debit alert (IMPS/NEFT/RTGS) |

## Installation

```
uv sync
```

## Usage

```python
from bank_email_parser import parse_email

result = parse_email("icici", html)

print(result.transaction.direction)       # "debit"
print(result.transaction.amount.amount)   # Decimal('1500.00')
print(result.transaction.amount.currency) # "INR"
print(result.transaction.counterparty)    # "Amazon"
print(result.transaction.channel)         # "card"
```

`parse_email(bank, html)` returns a `ParsedEmail`:

```python
class ParsedEmail(BaseModel):
    email_type: str       # e.g. "icici_cc_transaction_alert"
    bank: str             # e.g. "icici"
    transaction: TransactionAlert

class TransactionAlert(BaseModel):
    direction: Literal["debit", "credit"]
    amount: Money
    transaction_date: date | None
    transaction_time: time | None
    counterparty: str | None
    balance: Money | None
    reference_number: str | None
    account_mask: str | None
    card_mask: str | None
    channel: str | None       # upi, neft, imps, rtgs, card, atm, netbanking, cheque, etc.
    raw_description: str | None  # debug-only; excluded from model_dump()/model_dump_json() by default

class Money(BaseModel):
    amount: Decimal
    currency: str = "INR"
```

Raises `UnsupportedEmailTypeError` if the bank ID is not recognized, or `ParseError` if no parser can handle the email.

## Adding a New Bank Parser

1. Create `src/bank_email_parser/parsers/{bank}.py`.
2. Add a module docstring listing the supported email types.
3. Subclass `BaseEmailParser` for each email format the bank uses. Implement `parse(self, html: str) -> ParsedEmail`.
4. Define a module-level `_PARSERS` tuple with one instance of each parser class.
5. Define a module-level `parse(html: str) -> ParsedEmail` function that calls `parse_with_parsers("bank", html, _PARSERS)`.
6. Add the bank ID to `SUPPORTED_BANKS` in `src/bank_email_parser/api.py`.

See any existing parser (e.g. `parsers/sbi.py`) for a complete example.

## Related Projects

- **bank-email-fetcher** — Web app that uses this library to fetch bank emails, store transactions, and provide a dashboard.
- **cc-parser** — Sibling library for parsing CC statement PDFs (9 Indian banks).
