---
name: add-bank-parser
description: Use when adding a new bank to bank-email-parser, extending an existing bank with a new email type, or implementing a stubbed parser awaiting a sample email.
---

# Add or Update a Bank Email Parser

Arguments: `$ARGUMENTS` — bank slug and sample email (`.eml` path or HTML body).

## Read first

- `AGENTS.md`
- `bank_email_parser/models.py`
- `bank_email_parser/exceptions.py`
- `bank_email_parser/parsers/base.py`
- `bank_email_parser/api.py`
- `bank_email_parser/parsers/__init__.py`
- `bank_email_parser/parsing/__init__.py` and the modules it re-exports
- One existing parser of the same shape as the target — `parsers/equitas.py` for a single-file bank, `parsers/kotak/` for a multi-type subpackage
- `tests/test_registry.py` and `tests/test_repository_hygiene.py` — these enforce contracts you must satisfy

## Inspect the HTML first — MANDATORY

Do not write parser code before examining the real email. Skipping this step produces parsers that match imagined structure and silently drop fields.

From a `.eml`, extract the HTML body (`email.message_from_bytes`, walk parts, decode the `text/html` payload). **Do not commit the `.eml`** — `tests/test_repository_hygiene.py` rejects tracked `.eml`, `.msg`, `.mbox`, `.pst` files. Keep samples outside the repo or under a gitignored path.

From the HTML, identify:

- which fields are present (amount, direction, date/time, counterparty, account/card mask, reference, channel, balance)
- how they are encoded (2-column `<table>`, label/value `<div>` pairs, `<li>` list, prose regex)
- unique markers that distinguish this email type from the bank's other emails
- for statement emails: password hint text *or* summary fields (total/minimum due, due date)

## Required parser contracts

Every email-format parser subclasses `BaseEmailParser` and must define both class attributes — `BaseEmailParser.__init_subclass__` raises `TypeError` if either is missing or non-string:

```python
class FooUpiDebitParser(BaseEmailParser):
    bank = "foo"
    email_type = "foo_upi_debit"

    def parse(self, html: str) -> ParsedEmail:
        soup, text = self.prepare_html(html)
        ...
        return ParsedEmail(
            email_type=self.email_type,
            bank=self.bank,
            transaction=TransactionAlert(direction="debit", amount=...),
        )
```

Every successful return must set `email_type=self.email_type` and `bank=self.bank` — both are required `ParsedEmail` fields.

`TransactionAlert.direction` is `Literal["debit", "credit", "declined"]` — exact strings only. Refunds, reversals, and payments map to `"credit"` or `"debit"` plus an appropriate `channel`/`counterparty`. `Money.amount` is a non-negative `Decimal`; never encode debits as negative amounts.

Each bank exposes one dispatcher class subclassing `BankParser`:

```python
_PARSERS = (
    FooSpecificParser(),
    FooBroadParser(),
)


class FooParser(BankParser):
    bank = "foo"
    parsers = _PARSERS


def parse(html: str) -> ParsedEmail:
    return FooParser().parse(html)
```

`_PARSERS` is the repo convention name; `parsers = _PARSERS` is the runtime contract that `BankParser.__init_subclass__` checks. The top-level dict in `parsers/__init__.py` is `PARSERS` (no underscore) and stores **dispatcher classes**, not parser instances.

## Implementation checklist

1. Use `bank_email_parser/parsing/` helpers first — `parse_date`, `parse_datetime`, `parse_amount`, `parse_money`, `normalize_whitespace`, `extract_table_pairs`, `normalize_key`. `parse_amount` / `parse_money` / `parse_date` / `parse_datetime` return `None` on failure; check the result and raise `ParseError` rather than letting `None` flow into Pydantic. `extract_table_pairs` returns keys already passed through `normalize_key` (lowercase, alphanumeric + space, collapsed whitespace), so any `expected_keys` set must use the same normalization. Older code may import from `bank_email_parser.utils`; new code should prefer `parsing/`.
2. Inside `parse()`, call `soup, text = self.prepare_html(html)`. The dispatcher caches the parsed soup and normalized text per dispatch via thread-local state, so every fallback parser can call `prepare_html` cheaply. Match against the normalized `text` rather than re-parsing the raw HTML.
3. For banks with multiple distinct email types, prefer `bank_email_parser/parsers/{bank}/`:
   - `__init__.py` exports `{Bank}Parser` plus a module-level `parse`
   - one parser class per email type in its own submodule
   - `_PARSERS` keeps ordering
4. For simple banks, `parsers/{bank}.py` is fine.
5. Keep `email_type` stable and bank-prefixed — `bank-email-fetcher` stores these values, and renaming breaks downstream data.
6. Expose a bank dispatcher class (`{Bank}Parser`) **and** a module-level `parse(html)` function. `tests/test_registry.py` asserts both are importable from `bank_email_parser.parsers.{bank}` and that `parse` is callable.
7. Register the dispatcher class (not an instance, not individual email-type parsers) in `bank_email_parser/parsers/__init__.py` under `PARSERS`. `SUPPORTED_BANKS = tuple(PARSERS)` is derived automatically. The filesystem layout under `parsers/` and the `PARSERS` keys must agree — `tests/test_registry.py` cross-checks them.
8. Add synthetic pytest coverage (see Tests section).

## `_PARSERS` ordering

First match wins. Order matters:

1. **Specific parsers first.** A parser whose markers uniquely identify one email type.
2. **Broad parsers next.** A parser that matches several shapes but is reliable.
3. **Statement parsers** — see below; usually last, but a tightly-marked statement-summary parser may be ordered by normal specificity.
4. **`ParserStubError` stubs at the very end**, so they never shadow a real parser.

## Statement email parsers

There are two statement shapes:

1. **Password-protected attachment notifications.** Return `ParsedEmail(email_type=..., bank=..., password_hint="...")` with `transaction=None`. Hardcode a hint describing the bank's scheme (e.g. `"Date of birth in DDMMYYYY format"`, `"First 4 letters of name (lowercase) + DDMM of birth"`, `"Customer ID as the password"`).
2. **Statement-summary emails** exposing due amount / date in the body. Return `ParsedEmail(..., statement=StatementSummary(total_amount_due=..., minimum_amount_due=..., due_date=..., card_mask=...))`. Use `password_hint` only when an encrypted attachment is being announced. See `parsers/onecard.py` for a working example.

Password-attachment statement parsers are inherently broad — they match on words like `"statement"` and `"password"` that can appear in transaction-alert footers. Under-guarded, they will eat unrelated emails. Guard strictly:

- Require a password/attachment marker (`"password"`, `"attached"`, `"password-protected"`, `"statement is password protected"`, or similar).
- AND require a bank brand anchor (bank name in the disclaimer/footer, product name, co-brand like `"edge csb"`).
- Place these parsers last in `_PARSERS`.

A statement-summary parser whose markers are specific to one bank (exact phrasing of "Total Amount Due" inside the bank's branded shell) may be placed earlier if it cannot match transaction alerts.

## Errors and the fallback chain

Every "this email isn't mine" or "I cannot parse a required field" path must raise `ParseError`. Never return `None`. Do not let `KeyError`, `AttributeError`, `ValueError`, or Pydantic `ValidationError` escape — those are treated as *unexpected*: `parse_with_parsers` collects them, keeps trying the chain, attaches them as `__cause__` on the final failure, and emits a `warnings.warn` if a later parser succeeds anyway. The dispatch still works, but you've added noise that masks bugs.

Use `ParserStubError` only for known-but-unimplemented email types (sample not yet available). Stubs go at the end of `_PARSERS`.

## Tests and verification

Add synthetic tests under `tests/` in any `test_*.py` file — recent additions tend to land in `tests/test_new_parsers.py`. Cover:

- `email_type` and `bank`
- `transaction` vs `statement` vs `password_hint` shape
- `direction`, `amount.amount` as `Decimal`, `currency`
- date/time fields (assert exact `date` / `time` values)
- account/card masks, reference number, channel, counterparty
- a rejection test for any broad/statement parser proving it does not shadow an unrelated email shape

Never commit `.eml`, `.msg`, `.mbox`, `.pst`, or any real personal or financial data. Use synthetic samples in tests.

Run before declaring done:

- `uv run pytest -q`
- `uv run ruff check`
- `uv run ty check`

## Rules

- Raise `ParseError` (or `ParserStubError` for known-but-unimplemented types). Never return `None`.
- Preserve public API: `parse_email`, `SUPPORTED_BANKS`, exception types, and bank-level imports (`from bank_email_parser.parsers.{bank} import {Bank}Parser`).
- Never commit real personal or financial data, and never commit raw email exports of any kind.
