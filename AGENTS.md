# AGENTS.md — bank-email-parser

## Quick reference

- **Run setup:** `uv sync`
- **Run tests:** `uv run pytest -q`
- **Run lint:** `uv run ruff check`
- **Run types:** `uv run ty check`
- **Python:** 3.14+ · **Package manager:** uv
- **PEP 758 is valid here.** Do not “fix” parenthesis-free multi-except syntax for 3.14.

## Project layout

- Flat package layout: `bank_email_parser/`
- Public API stays in `bank_email_parser/__init__.py` and `bank_email_parser/api.py`
- Parsing helpers live in `bank_email_parser/parsing/`
  - `dates.py` → `parse_date`, `parse_datetime` (`dateutil`, `dayfirst=True`)
  - `amounts.py` → `parse_amount`, `parse_money`
  - `html.py` → `normalize_whitespace`, `extract_table_pairs`
  - `keys.py` → `normalize_key`
- `bank_email_parser/utils.py` is a compatibility shim; prefer new imports from `parsing/`
- Bank parsers live in `bank_email_parser/parsers/`
  - Single-file banks can stay as `parsers/{bank}.py`
  - Large / multi-email-type banks can use `parsers/{bank}/` subpackages
  - `parsers/__init__.py` contains the explicit `PARSERS` registry

## Parser architecture

- `api.parse_email(bank, html)` uses the explicit bank registry in `bank_email_parser.parsers`
- Registry entries are **bank dispatcher classes** (`AxisParser`, `KotakParser`, etc.), not individual email-type parsers
- Each bank module/package owns:
  - one or more `BaseEmailParser` subclasses with stable `email_type` strings
  - `_PARSERS` ordered tuple (first match wins)
  - a bank dispatcher class (`{Bank}Parser`) inheriting `BankParser`
  - module/package-level `parse(html)` convenience wrapper
- Preserve external imports like `from bank_email_parser.parsers.kotak import KotakParser`

## Adding a new bank or email type

> Use `.agents/skills/add-bank-parser/SKILL.md`.

Checklist:

1. Prefer `bank_email_parser/parsers/{bank}/` when the bank has multiple distinct email types; otherwise `parsers/{bank}.py` is fine.
2. Add one `BaseEmailParser` subclass per email format.
3. Keep `email_type` values stable and bank-prefixed.
4. Add parser instances to `_PARSERS` in specificity order; stubs go last.
5. Expose a bank dispatcher class (`{Bank}Parser`) and keep `parse(html)` delegating through it.
6. Register the dispatcher in `bank_email_parser/parsers/__init__.py`.
7. Reuse helpers from `bank_email_parser.parsing/` before adding ad-hoc regex helpers.
8. Add synthetic tests in `tests/`.

## Critical rules

- **Never rename `email_type` values.** `bank-email-fetcher` stores them.
- **Preserve public API compatibility:** `parse_email`, `SUPPORTED_BANKS`, `ParsedEmail`, exception types, and bank-level dispatcher imports.
- **Never use real personal data** in tests, docs, comments, or fixtures.
- `raw_description` is debug-only and excluded from dumps/repr by default.
- `direction` can be `"debit"`, `"credit"`, or `"declined"`.
- HTML matching should use normalized text from `prepare_html()`.
- Prefer `parse_date` / `parse_datetime`; do not reintroduce custom `strptime` lists unless unavoidable.

## Known stubs

- `axis_neft_alert` — intentional stub pending a sample email
