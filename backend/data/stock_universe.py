"""
Stock Universe — curated list of ~260 liquid US equities + ETFs across 14 sectors.
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
        "ADBE", "NOW", "WDAY", "ZM", "OKTA", "CRWD", "PANW", "S",
        "NET", "FSLY", "CFLT",
    ],
    "Semiconductors": [
        "TSM", "ASML", "ARM", "MRVL", "MPWR", "ENTG", "WOLF",
        "OLED", "ACLS", "COHR", "FORM", "AMBA", "DIOD",
    ],
    "Healthcare": [
        "JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "BMY", "AMGN",
        "GILD", "BIIB", "REGN", "VRTX", "MRNA", "BNTX",
        "CVS", "HUM", "CI", "ELV", "MCK", "COR",
    ],
    "Biotech": [
        "SRPT", "EXAS", "INCY", "ALNY", "IONS", "SGEN", "BLUE",
        "BEAM", "EDIT", "CRSP", "NTLA", "ACAD", "RARE",
        "RCKT", "ARWR", "FATE", "PRGO",
    ],
    "Finance": [
        "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "AXP",
        "V", "MA", "PYPL", "COF", "USB", "SCHW",
        "CB", "PGR", "ALL", "MET", "PRU",
        "ICE", "CME", "SPGI", "MCO", "FIS", "FISV",
    ],
    "Fintech_Crypto": [
        "COIN", "MSTR", "MARA", "RIOT", "HOOD", "SQ", "AFRM",
        "SOFI", "UPST", "LC", "OPFI",
    ],
    "Energy": [
        "XOM", "CVX", "COP", "EOG", "SLB", "HAL", "MPC",
        "PSX", "VLO", "OXY", "DVN", "FANG", "WMB",
        "KMI", "ET", "LNG", "AR",
    ],
    "Consumer_Discretionary": [
        "TSLA", "HD", "MCD", "NKE", "SBUX", "TGT", "LOW",
        "AMZN", "BKNG", "MAR", "HLT", "RCL", "CCL",
        "GM", "F", "RIVN", "LCID",
        "ETSY", "W", "CHWY", "DASH", "ABNB",
    ],
    "Consumer_Staples": [
        "WMT", "COST", "PG", "KO", "PEP", "MDLZ", "CL",
        "GIS", "CPB", "SYY", "KHC",
        "EL", "CHD", "CLX", "MKC",
    ],
    "Industrial": [
        "GE", "HON", "CAT", "DE", "RTX", "LMT", "NOC", "BA",
        "UPS", "FDX", "CSX", "NSC", "UNP",
        "EMR", "ETN", "PH", "ROK",
        "CARR", "OTIS", "ALLE", "XYL", "GNRC",
    ],
    "Communication": [
        "T", "VZ", "TMUS", "CHTR", "CMCSA",
        "DIS", "FOXA", "WBD", "SNAP", "PINS",
        "SPOT", "TTWO", "EA", "ATVI",
    ],
    "Materials": [
        "LIN", "APD", "SHW", "FCX", "NEM", "GOLD",
        "NUE", "CLF", "CF", "MOS",
        "ALB", "LTHM", "MP", "LAC",       # Lithium/rare earth
        "AA", "CENX",                       # Aluminum
    ],
    "Utilities": [
        "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE",
        "PCG", "XEL", "ETR", "AWK", "ATO", "NI",
    ],
    "Real_Estate": [
        "AMT", "PLD", "EQIX", "CCI", "SPG", "PSA",
        "O", "WY", "VTR", "DLR", "VICI", "WELL",
        "ARE", "SBA", "EXR",
    ],
    "International_ADR": [
        "NVO", "ASML", "TSM", "TM", "SONY", "SAP",
        "BABA", "JD", "PDD", "SE", "GRAB",
        "VALE", "RIO", "BHP",
    ],
    "ETF_Sectors": [
        "SPY", "QQQ", "IWM", "DIA", "MDY", "IJR",    # Broad market (added mid/small)
        "XLK", "XLF", "XLE", "XLV", "XLI", "XLY",
        "XLC", "XLB", "XLP", "XLU", "XLRE",           # Added XLU (Utilities), XLRE (Real Estate)
        "ARKK", "SOXX", "SMH",
        "GLD", "SLV", "USO", "GDX", "GDXJ", "COPX",  # Commodities
        "TLT", "HYG", "LQD",                           # Bonds (macro context)
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
