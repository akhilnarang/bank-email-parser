# AGENTS.md — bank-email-parser

## Quick reference

- **Run tests:** `uv run pytest`
- **Run a single test class:** `uv run pytest tests/test_new_parsers.py::TestYesbankCcDebitAlertParser -v`
- **Python:** 3.14+ · **Package manager:** uv · **Deps:** pydantic>=2.0, beautifulsoup4>=4.12, python-dateutil>=2.9
- **No CI, no linter, no formatter configured** — just pytest

## Architecture

Single Python package at `src/bank_email_parser/`. Entry point: `api.parse_email(bank, html)` which dynamically imports `parsers.<bank>` and calls its `parse(html)`.

Each parser module has:
- One or more `BaseEmailParser` subclasses with `bank`, `email_type`, and `parse()` 
- A `_PARSERS` tuple (order matters — first match wins)
- A module-level `parse(html)` delegating to `parse_with_parsers(bank, html, _PARSERS)`

## Adding a new bank or email type

> **Use the `add-bank-parser` skill** (`.agents/skills/add-bank-parser/SKILL.md`) — it walks through extracting HTML from a `.eml`, writing the parser, and testing it end-to-end.

Manual outline:

1. Create `src/bank_email_parser/parsers/{bank}.py` — follow any existing parser (e.g. `yesbank.py` is minimal)
2. Add bank ID to `SUPPORTED_BANKS` tuple in `api.py`
3. Add tests in `tests/test_new_parsers.py` using **synthetic HTML** (never real email data)
4. If you have a real `.eml`, put it anonymised in `data/` (gitignored)

For a new email type on an existing bank, add a new `BaseEmailParser` subclass to that bank's module. Place it **before broader parsers** in `_PARSERS` — the dispatcher uses first-match semantics. Stubs go last.

## Critical rules

- **Never rename `email_type` values.** `bank-email-fetcher` stores them in its DB. Renaming is a breaking change.
- **Never use real personal details anywhere in this project** — tests, docstrings, code comments, commit messages, AGENTS.md, everywhere. When a user provides a real email, anonymize all specifics before writing any code: replace real amounts, card numbers, account numbers, merchant names, dates, phone numbers, and email addresses with synthetic values (e.g. `INR 1,234.56`, card `1234`, merchant `SAMPLE MERCHANT`). This applies to all file types including tests, parser modules, and documentation.
- **`raw_description` is excluded from model dumps and repr by default** (Pydantic `exclude=True, repr=False`). It's debug-only.
- **`direction` accepts `"declined"`** as a third option beyond `"debit"`/`"credit"` — used when a transaction was attempted but no funds moved (e.g. SBI declined SI).
- **HTML input is flattened to text** via `normalize_whitespace(soup.get_text(...))` before regex matching. This collapses `\xa0`, `\u200c`, and all whitespace runs to single spaces.
- **`parse_with_parsers` reuses parsed HTML** across fallback parsers via thread-local context. Don't re-parse HTML inside `parse()`.
- **Always use `utils.parse_date` / `utils.parse_datetime`** for any date/time string. They wrap `dateutil.parser.parse(..., dayfirst=True)` — don't reintroduce `datetime.strptime` with per-parser format lists.

## Known stubs (raise `ParserStubError`)

- `axis_neft_alert` — no sample email

These exist in `_PARSERS` so their `email_type` appears in error messages.

## Cross-project

When adding a new bank, also add fetch rules in `bank-email-fetcher/seed.py` (FROM address, SUBJECT pattern).