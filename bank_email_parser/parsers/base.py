"""Base parser class and fallback-chain dispatcher for bank email parsers."""

import threading
import warnings
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Literal

from bs4 import BeautifulSoup

from bank_email_parser.exceptions import ParseError, ParserStubError
from bank_email_parser.models import ParsedEmail
from bank_email_parser.parsing.html import normalize_whitespace


@dataclass(slots=True)
class ParserContext:
    """Shared per-dispatch parser context."""

    html: str
    prepared_email: tuple[BeautifulSoup, str] | None = None


# Thread-local storage for parser context, so concurrent calls to
# parse_with_parsers() do not corrupt each other's state.
_thread_local = threading.local()


class BaseEmailParser(ABC):
    """The base class for one email shape from one bank.

    A subclass must define ``bank`` and ``email_type``. It can also define
    ``event_time_source``. ``__init_subclass__`` checks all three values when
    you define the class, so a wrong value stops the import.

    Set ``event_time_source`` to ``message_arrival`` only when both of these
    are true: the body has no time, and the bank sends the message at the
    moment of the transaction. Examine real messages before you change it.

    Set ``identifies_by`` to ``card_mask`` when the message reports a payment
    of the card bill and gives the card mask. Set it to ``none`` when the
    bank sends no field that shows which event the message reports. See
    ``ParsedEmail`` for what the consumer does with each value.
    """

    bank: str
    email_type: str
    event_time_source: Literal["body", "message_arrival"] = "body"
    identifies_by: Literal["counterparty", "card_mask", "none"] = "counterparty"

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Skip a class that defines none of these. Such a class is an
        # abstract intermediate. A class that defines only event_time_source
        # must still get a check. Without it, a wrong value goes to the
        # consumer, and the consumer reads that value as "body".
        if not (cls.__dict__.keys()
            & {"bank", "email_type", "event_time_source", "identifies_by"}):
            return
        # A class can inherit bank or email_type from a parent. Both values
        # must still resolve to a string.
        bank = getattr(cls, "bank", None)
        email_type = getattr(cls, "email_type", None)
        if not isinstance(bank, str):
            raise TypeError(f"{cls.__name__} must define a 'bank: str' class attribute")
        if not isinstance(email_type, str):
            raise TypeError(
                f"{cls.__name__} must define an 'email_type: str' class attribute"
            )
        if getattr(cls, "event_time_source", None) not in ("body", "message_arrival"):
            raise TypeError(
                f"{cls.__name__} must define 'event_time_source' as "
                "'body' or 'message_arrival'"
            )
        if getattr(cls, "identifies_by", None) not in (
            "counterparty",
            "card_mask",
            "none",
        ):
            raise TypeError(
                f"{cls.__name__} must define 'identifies_by' as "
                "'counterparty', 'card_mask' or 'none'"
            )

    @staticmethod
    def _build_prepared_email(html: str) -> tuple[BeautifulSoup, str]:
        """Build parsed HTML and normalized plain text."""
        soup = BeautifulSoup(html, "html.parser")
        text = normalize_whitespace(soup.get_text(separator=" ", strip=True))
        return soup, text

    def prepare_html(self, html: str) -> tuple[BeautifulSoup, str]:
        """Parse HTML once per dispatch and reuse it across fallback parsers.

        Uses thread-local storage so that concurrent calls to
        ``parse_with_parsers`` do not interfere with each other.

        The returned soup is the shared cached instance: callers must treat
        it as read-only and must not mutate the tree (no ``decompose``,
        ``extract``, ``insert``, etc.). A parser that needs to mutate the DOM
        should build its own soup with ``BeautifulSoup(html, ...)``.
        """
        context: ParserContext | None = getattr(_thread_local, "parser_context", None)
        if context is not None and (context.html is html or context.html == html):
            if context.prepared_email is None:
                context.prepared_email = self._build_prepared_email(html)
            return context.prepared_email
        return self._build_prepared_email(html)

    @abstractmethod
    def parse(self, html: str) -> ParsedEmail:
        """Parse an HTML email body into a structured ParsedEmail."""
        ...


class BankParser:
    """Bank-level dispatcher that preserves per-bank parser ordering."""

    bank: ClassVar[str]
    parsers: ClassVar[Sequence[BaseEmailParser]]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "bank" not in cls.__dict__ and "parsers" not in cls.__dict__:
            return
        bank = getattr(cls, "bank", None)
        bank_parsers = getattr(cls, "parsers", None)
        if not isinstance(bank, str):
            raise TypeError(f"{cls.__name__} must define a 'bank: str' class attribute")
        if not isinstance(bank_parsers, Sequence):
            raise TypeError(
                f"{cls.__name__} must define a 'parsers' sequence of parser instances"
            )

    def parse(self, html: str) -> ParsedEmail:
        """Dispatch to the bank's parser chain."""
        return parse_with_parsers(self.bank, html, self.parsers)


def parse_with_parsers(
    bank: str,
    html: str,
    parsers: Sequence[BaseEmailParser],
) -> ParsedEmail:
    """Try each parser in order until one succeeds.

    Unexpected (non-ParseError/ParserStubError) exceptions do not
    short-circuit the fallback chain.  They are collected and included
    in the final ``ParseError`` if no parser succeeds, so bugs in a
    single parser are still surfaced.
    """
    errors: list[str] = []
    unexpected_errors: list[Exception] = []
    context = ParserContext(html=html)
    old_context = getattr(_thread_local, "parser_context", None)
    _thread_local.parser_context = context
    try:
        for parser in parsers:
            try:
                result = parser.parse(html)
                # The class states this fact, but the caller receives only the
                # model. Copy it across so the caller does not need to know
                # which class matched.
                result.event_time_source = parser.event_time_source
                result.identifies_by = parser.identifies_by
                # Success — but warn about any unexpected errors from earlier parsers
                if unexpected_errors:
                    warning = (
                        f"Parser {parser.email_type} succeeded but earlier parsers "
                        "raised unexpected errors: "
                        + "; ".join(
                            f"{type(error).__name__}: {error}"
                            for error in unexpected_errors
                        )
                    )
                    warnings.warn(
                        warning,
                        stacklevel=2,
                    )
                return result
            except (ParseError, ParserStubError) as exc:
                errors.append(f"{parser.email_type}: {type(exc).__name__}")
            except Exception as exc:
                # Unexpected error -- collect it but continue the chain so
                # a bug in one parser does not prevent others from matching.
                errors.append(f"{parser.email_type}: {type(exc).__name__}: {exc}")
                unexpected_errors.append(exc)
    finally:
        _thread_local.parser_context = old_context

    msg = (
        f"No parser for bank {bank!r} could handle this email. "
        f"Tried: {', '.join(p.email_type for p in parsers)}. "
        f"Errors: {'; '.join(errors)}"
    )
    exc = ParseError(msg)
    if unexpected_errors:
        exc.__cause__ = (
            unexpected_errors[0]
            if len(unexpected_errors) == 1
            else ExceptionGroup("Unexpected parser errors", unexpected_errors)
        )
    raise exc
