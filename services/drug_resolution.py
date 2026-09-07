"""
Re-export from app.services.drug_resolution for root-level import convenience.
"""
from app.services.drug_resolution import (
    DRAP_BASE_URL,
    DRAPClient,
    NOT_PRESENT_IN_LABEL,
    OPENFDA_LABEL_URL,
    RXNORM_BASE_URL,
    fetch_fda_label,
    fetch_fda_label_async,
    get_drap_product_details,
    get_product_details,
    get_product_details_async,
    parse_composition,
    rxnorm_normalize,
    rxnorm_normalize_async,
    search,
    search_async,
    search_drap,
    resolve_drug,
    resolve_and_persist_product,
)

__all__ = [
    "DRAP_BASE_URL",
    "DRAPClient",
    "NOT_PRESENT_IN_LABEL",
    "OPENFDA_LABEL_URL",
    "RXNORM_BASE_URL",
    "fetch_fda_label",
    "fetch_fda_label_async",
    "get_drap_product_details",
    "get_product_details",
    "get_product_details_async",
    "parse_composition",
    "rxnorm_normalize",
    "rxnorm_normalize_async",
    "search",
    "search_async",
    "search_drap",
    "resolve_drug",
    "resolve_and_persist_product",
]

