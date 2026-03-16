"""
Stock Universe — curated list of ~160 liquid US equities across 10 sectors.
Used by the ScannerAgent as the candidate pool for opportunity discovery.
"""
from typing import Dict, List

# Sector → list of symbols
UNIVERSE: Dict[str, List[str]] = {
    "Technology": [
        "AAPL", "MSFT", "NVDA", "AMD", "INTC", "QCOM", "AVGO", "MU",
        "AMAT", "KLAC", "LRCX", "TXN", "ADI", "MCHP", "ON",
        "CRM", "ORCL", "SAP", "SNOW", "PLTR", "DDOG", "MDB",
        "META", "GOOGL", "AMZN", "NFLX", "UBER", "LYFT", "RBLX",
    ],
    "Healthcare": [
        "JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "BMY", "AMGN",
        "GILD", "BIIB", "REGN", "VRTX", "MRNA", "BNTX",
        "CVS", "HUM", "CI", "ELV", "MCK", "COR",
    ],
    "Finance": [
        "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "AXP",
        "V", "MA", "PYPL", "XYZ", "COF", "USB", "SCHW",
        "CB", "PGR", "ALL", "MET", "PRU",
    ],
    "Energy": [
        "XOM", "CVX", "COP", "EOG", "SLB", "HAL", "MPC",
        "PSX", "VLO", "OXY", "DVN", "FANG", "WMB",
    ],
    "Consumer_Discretionary": [
        "TSLA", "HD", "MCD", "NKE", "SBUX", "TGT", "LOW",
        "AMZN", "BKNG", "MAR", "HLT", "RCL", "CCL",
        "GM", "F", "RIVN", "LCID",
    ],
    "Consumer_Staples": [
        "WMT", "COST", "PG", "KO", "PEP", "MDLZ", "CL",
        "GIS", "CPB", "SYY", "KHC",
    ],
    "Industrial": [
        "GE", "HON", "CAT", "DE", "RTX", "LMT", "NOC", "BA",
        "UPS", "FDX", "CSX", "NSC", "UNP",
        "EMR", "ETN", "PH", "ROK",
    ],
    "Communication": [
        "T", "VZ", "TMUS", "CHTR", "CMCSA",
        "DIS", "FOXA", "WBD", "SNAP", "PINS",
    ],
    "Materials": [
        "LIN", "APD", "SHW", "FCX", "NEM", "GOLD",
        "NUE", "CLF", "CF", "MOS",
    ],
    "ETF_Sectors": [
        "SPY", "QQQ", "IWM", "DIA",
        "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLC",
        "ARKK", "SOXX", "SMH",
    ],
}

# Flat list for batch operations
ALL_SYMBOLS: List[str] = sorted({sym for syms in UNIVERSE.values() for sym in syms})


def get_sector(symbol: str) -> str:
    """Return the sector name for a given symbol."""
    for sector, syms in UNIVERSE.items():
        if symbol in syms:
            return sector
    return "Unknown"


def get_sector_symbols(sector: str) -> List[str]:
    """Return all symbols in a sector (case-insensitive partial match)."""
    sector_lower = sector.lower()
    for name, syms in UNIVERSE.items():
        if sector_lower in name.lower():
            return syms
    return []
