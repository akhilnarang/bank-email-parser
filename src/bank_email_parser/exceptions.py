"""Exception types raised during email parsing."""
class ParseError(Exception):
    """Raised when an email cannot be parsed despite matching the expected type."""


class ParserStubError(NotImplementedError):
    """Raised by intentional parser stubs that are waiting for a sample email."""


class UnsupportedEmailTypeError(Exception):
    """Raised when the given bank identifier has no registered parser."""
