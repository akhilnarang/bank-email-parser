"""Explicit bank parser registry."""

from bank_email_parser.parsers.axis import AxisParser
from bank_email_parser.parsers.bom import BomParser
from bank_email_parser.parsers.equitas import EquitasParser
from bank_email_parser.parsers.hdfc import HdfcParser
from bank_email_parser.parsers.hsbc import HsbcParser
from bank_email_parser.parsers.icici import IciciParser
from bank_email_parser.parsers.idfc import IdfcParser
from bank_email_parser.parsers.indusind import IndusindParser
from bank_email_parser.parsers.jupiter import JupiterParser
from bank_email_parser.parsers.kotak import KotakParser
from bank_email_parser.parsers.onecard import OnecardParser
from bank_email_parser.parsers.sbi import SbiParser
from bank_email_parser.parsers.slice import SliceParser
from bank_email_parser.parsers.uboi import UboiParser
from bank_email_parser.parsers.yesbank import YesbankParser

PARSERS = {
    "axis": AxisParser,
    "bom": BomParser,
    "equitas": EquitasParser,
    "hdfc": HdfcParser,
    "hsbc": HsbcParser,
    "icici": IciciParser,
    "idfc": IdfcParser,
    "indusind": IndusindParser,
    "jupiter": JupiterParser,
    "kotak": KotakParser,
    "onecard": OnecardParser,
    "sbi": SbiParser,
    "slice": SliceParser,
    "uboi": UboiParser,
    "yesbank": YesbankParser,
}

__all__ = ["PARSERS"]
