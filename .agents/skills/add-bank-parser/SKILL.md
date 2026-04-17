---
name: add-bank-parser
description: Add a new bank email parser or a new email type to an existing bank.
---

# Add or Update a Bank Email Parser

Arguments: `$ARGUMENTS` — bank slug and sample email (`.eml` path or HTML body).

## Read first

- `AGENTS.md`
- `bank_email_parser/models.py`
- `bank_email_parser/parsers/base.py`
- `bank_email_parser/api.py`
- `bank_email_parser/parsers/__init__.py`
- One existing parser module or subpackage for the target shape

## Inspect the HTML first — MANDATORY

Do not write parser code before examining the real email. Skipping this step produces parsers that match imagined structure and silently drop fields.

From a `.eml`, extract the HTML body (`email.message_from_bytes`, walk parts, decode the `text/html` payload). From the HTML, identify:

- which fields are present (amount, direction, date/time, counterparty, account/card mask, reference, channel, balance)
- how they are encoded (2-column `<table>`, label/value `<div>` pairs, `<li>` list, prose regex)
- unique markers that distinguish this email type from the bank's other emails
- for statement emails: the password hint text

## Implementation checklist

1. Use `bank_email_parser/parsing/` helpers first (`parse_date`, `parse_datetime`, `parse_amount`, `parse_money`, `normalize_whitespace`, `extract_table_pairs`, `normalize_key`). Existing parsers still import from `bank_email_parser.utils`, which re-exports the same helpers; either import path is valid, but new code should prefer `parsing/`.
2. For banks with multiple distinct email types, prefer `bank_email_parser/parsers/{bank}/`:
   - `__init__.py` exports `{Bank}Parser`
   - one parser class per email type
   - `_PARSERS` keeps ordering
3. For simple banks, `parsers/{bank}.py` is still fine.
4. Keep `email_type` stable and bank-prefixed — `bank-email-fetcher` stores these values.
5. Expose a bank dispatcher class (`{Bank}Parser`) and module-level `parse(html)`.
6. Register the dispatcher in `bank_email_parser/parsers/__init__.py`. The CLI reads `SUPPORTED_BANKS` automatically.
7. Add synthetic pytest coverage.

## `_PARSERS` ordering

First match wins. Order matters:

1. **Specific parsers first.** A parser whose markers uniquely identify one email type.
2. **Broad parsers next.** A parser that matches several shapes but is reliable.
3. **Statement parsers last** (see below).
4. **`ParserStubError` stubs at the very end**, so they never shadow a real parser.

## Statement email parsers

Statement parsers are inherently broad — they match on keywords like `"statement"` and `"password"` that can appear in transaction-alert footers. Under-guarded, a statement parser will eat unrelated emails.

Guard strictly: require a password/attachment marker (`"password"`, `"attached"`, `"password-protected"`, `"statement is password protected"`, or similar) **AND** a bank brand anchor (bank name in the disclaimer/footer, product name, co-brand like `"edge csb"`). The brand anchor prevents a foreign email that happens to quote the same generic phrase from matching. Place the parser last in `_PARSERS`.

Return `ParsedEmail(transaction=None, password_hint="...")` with a hardcoded hint describing the bank's scheme (e.g. `"Date of birth in DDMMYYYY format"`, `"First 4 letters of name (lowercase) + DDMM of birth"`, `"Customer ID as the password"`).

## Rules

- Raise `ParseError` (or `ParserStubError` for known-but-unimplemented types). Never return `None` — the dispatcher needs the exception to try the next parser.
- Keep public compatibility: `parse_email`, `SUPPORTED_BANKS`, exceptions, and bank-level imports (`from bank_email_parser.parsers.{bank} import {Bank}Parser`).
- Never commit real personal or financial data.
