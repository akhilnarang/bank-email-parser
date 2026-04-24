"""CLI entrypoint for parsing bank email HTML into JSON."""

import email
from pathlib import Path

import click
import typer

from bank_email_parser.api import SUPPORTED_BANKS, parse_email
from bank_email_parser.exceptions import ParseError, UnsupportedEmailTypeError

app = typer.Typer(help="Parse a bank email HTML body and print normalized JSON.")


def _extract_body_from_eml(raw: bytes) -> str | None:
    """Walk a raw RFC822 message and return its body, preferring HTML.

    Falls back to ``text/plain`` when no HTML part is present — some banks
    (and debugging scenarios) ship text-only emails, and the parser chain
    can still operate on plain text via ``BaseEmailParser.prepare_html``.
    Mirrors the fetcher's extraction strategy in
    ``bank_email_fetcher.integrations.email.body``.
    """
    msg = email.message_from_bytes(raw)
    html_body: str | None = None
    text_body: str | None = None
    for part in msg.walk():
        ct = part.get_content_type()
        if ct not in ("text/html", "text/plain"):
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        charset = part.get_content_charset() or "utf-8"
        decoded = payload.decode(charset, errors="replace")
        if ct == "text/html" and html_body is None:
            html_body = decoded
        elif ct == "text/plain" and text_body is None:
            text_body = decoded
    return html_body or text_body


def _looks_like_eml(raw: bytes) -> bool:
    head = raw[:4096].lower()
    return b"content-type:" in head and (
        b"from:" in head or b"message-id:" in head or b"mime-version:" in head
    )


@app.callback(invoke_without_command=True)
def main(
    html_file: Path | None = typer.Argument(
        None,
        help="Path to an HTML or .eml file. Reads stdin when omitted.",
    ),
    bank: str = typer.Option(
        ...,
        "--bank",
        help="Bank identifier.",
        click_type=click.Choice(SUPPORTED_BANKS),
    ),
) -> None:
    """Parse an email body from a file or stdin.

    Accepts either a plain HTML file/stream or a raw RFC822 ``.eml``. When the
    input looks like an .eml (by extension or by header signature), the HTML
    part is extracted and decoded before parsing.
    """
    if html_file is None:
        raw_bytes = typer.get_text_stream("stdin").buffer.read()
        is_eml = _looks_like_eml(raw_bytes)
    else:
        if not html_file.exists():
            raise typer.BadParameter(f"File not found: {html_file}")
        raw_bytes = html_file.read_bytes()
        is_eml = html_file.suffix.lower() == ".eml" or _looks_like_eml(raw_bytes)

    if is_eml:
        html = _extract_body_from_eml(raw_bytes)
        if html is None:
            typer.echo("No text/html or text/plain part found in .eml input.", err=True)
            raise typer.Exit(1)
    else:
        html = raw_bytes.decode("utf-8", errors="replace")

    try:
        result = parse_email(bank, html)
    except (UnsupportedEmailTypeError, ParseError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(result.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
