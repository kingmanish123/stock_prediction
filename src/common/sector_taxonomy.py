"""Sector taxonomy — maps NSE industry classifications to canonical theme tags.

Used by the LLM theme extractor + news-to-stocks fanout logic. Keep this as a
Python module (not DB) so it's version-controlled + inspectable.
"""
from __future__ import annotations

# Canonical sector keys (snake_case). These are the tags the LLM will output
# for "affected sectors" given a news theme.
CANONICAL_SECTORS = {
    "energy": "Oil & Gas, Power, Coal, Renewables",
    "it": "IT Services, Tech",
    "banking_financial": "Banks, NBFCs, Insurance, Asset Mgmt",
    "consumer": "FMCG, Consumer Durables, Retail",
    "auto": "Auto OEMs, Auto Ancillaries",
    "pharma_healthcare": "Pharma, Hospitals, Diagnostics",
    "metals_mining": "Steel, Aluminium, Base Metals",
    "cement_construction": "Cement, Construction Materials, Real Estate",
    "telecom": "Telecom, Digital",
    "capital_goods": "Capital Goods, Industrial Machinery",
    "infrastructure": "Ports, Roads, Power Transmission",
    "chemicals": "Specialty Chemicals, Agrochemicals",
    "defense": "Defense, Aerospace",
    "textiles": "Textiles, Apparel",
    "services": "Logistics, Diversified Services",
}


# NSE publishes industry classifications on each index CSV. Map them to our
# canonical sectors. Unknown industries default to "other".
NSE_INDUSTRY_TO_SECTOR: dict[str, str] = {
    # Energy
    "Oil Gas & Consumable Fuels": "energy",
    "Power": "energy",
    # IT
    "Information Technology": "it",
    # Financial
    "Financial Services": "banking_financial",
    # Consumer
    "Fast Moving Consumer Goods": "consumer",
    "Consumer Durables": "consumer",
    "Consumer Services": "consumer",
    # Auto
    "Automobile and Auto Components": "auto",
    # Pharma / Healthcare
    "Healthcare": "pharma_healthcare",
    # Metals
    "Metals & Mining": "metals_mining",
    # Cement / Construction / Realty
    "Construction Materials": "cement_construction",
    "Construction": "cement_construction",
    "Realty": "cement_construction",
    # Telecom
    "Telecommunication": "telecom",
    # Capital goods
    "Capital Goods": "capital_goods",
    # Services / infra
    "Services": "infrastructure",
    # Chemicals
    "Chemicals": "chemicals",
    # Textiles
    "Textiles": "textiles",
}


def industry_to_sector(industry: str | None) -> str:
    """Map an NSE industry string to our canonical sector key."""
    if not industry:
        return "other"
    return NSE_INDUSTRY_TO_SECTOR.get(industry.strip(), "other")


# Commonly traded thematic baskets — these are narrative clusters the LLM
# frequently surfaces. Stocks tagged via canonical sector + keyword.
THEMES_TO_SECTORS: dict[str, list[str]] = {
    "crude_oil_supply": ["energy"],
    "crude_oil_demand": ["energy", "auto"],
    "us_fed_dovish": ["banking_financial", "it", "auto", "consumer"],
    "us_fed_hawkish": ["banking_financial", "it"],
    "india_rate_cut": ["banking_financial", "auto", "cement_construction"],
    "monsoon_good": ["consumer", "auto"],
    "rupee_weakens": ["it", "pharma_healthcare"],
    "rupee_strengthens": ["banking_financial", "consumer"],
    "china_slowdown": ["metals_mining"],
    "global_risk_off": ["it", "consumer"],  # defensive
    "global_risk_on": ["metals_mining", "auto", "banking_financial"],
    "defense_spending_rise": ["defense", "capital_goods"],
    "ev_push": ["auto"],
    "infra_capex_rise": ["cement_construction", "capital_goods", "infrastructure"],
    "pharma_usfda_positive": ["pharma_healthcare"],
    "it_hiring_slowdown": ["it"],
    "telecom_arpu_rise": ["telecom"],
}
