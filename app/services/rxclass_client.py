"""
services/rxclass_client.py
NIH RxClass REST API client for drug-class membership lookups.

Per PROJECT_SPEC.md & Diet/Allergy Architecture:
- Queries https://rxnav.nlm.nih.gov/REST/rxclass/class/byRxcui.json?rxcui={rxcui}&relaSource=ATC
- Queries https://rxnav.nlm.nih.gov/REST/rxclass/class/byRxcui.json?rxcui={rxcui}&relaSource=MEDRT
- Returns normalized list of class IDs, class names, types, and sources.
- Provides thread-safe in-memory caching to avoid redundant HTTP calls during multi-drug checks.
"""

import logging
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

RXCLASS_BASE_URL = "https://rxnav.nlm.nih.gov/REST/rxclass/class/byRxcui.json"
DEFAULT_RELA_SOURCES = ["ATC", "MEDRT"]

# In-memory LRU-like cache: (rxcui, rela_source) -> list of drug classes
_RXCLASS_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def fetch_classes_for_source(
    rxcui: str,
    rela_source: str = "ATC",
    client: Optional[httpx.Client] = None,
    timeout: float = 10.0,
) -> List[Dict[str, Any]]:
    """
    Queries RxClass REST API for a specific relaSource (ATC or MEDRT).
    Returns list of parsed class objects:
    [{"class_id": str, "class_name": str, "class_type": str, "source": str}]
    """
    clean_rxcui = str(rxcui).strip()
    if not clean_rxcui:
        return []

    cache_key = f"{clean_rxcui}:{rela_source.upper()}"
    if cache_key in _RXCLASS_CACHE:
        return _RXCLASS_CACHE[cache_key]

    params = {
        "rxcui": clean_rxcui,
        "relaSource": rela_source,
    }

    try:
        if client:
            resp = client.get(RXCLASS_BASE_URL, params=params, timeout=timeout)
        else:
            with httpx.Client(timeout=timeout) as c:
                resp = c.get(RXCLASS_BASE_URL, params=params)

        if resp.status_code != 200:
            logger.warning(
                f"[rxclass_client] RxClass lookup failed for RxCUI={clean_rxcui}, "
                f"relaSource={rela_source}: HTTP {resp.status_code}"
            )
            return []

        data = resp.json()
        drug_info_list = (
            data.get("rxclassDrugInfoList", {})
            .get("rxclassDrugInfo", [])
        )

        classes: List[Dict[str, Any]] = []
        seen_class_ids = set()

        for entry in drug_info_list:
            concept_item = entry.get("rxclassMinConceptItem", {})
            class_id = concept_item.get("classId")
            class_name = concept_item.get("className")
            class_type = concept_item.get("classType")
            source = entry.get("relaSource", rela_source)

            if class_id and class_id not in seen_class_ids:
                seen_class_ids.add(class_id)
                classes.append({
                    "class_id": class_id,
                    "class_name": class_name or "",
                    "class_type": class_type or "",
                    "source": source,
                })

        _RXCLASS_CACHE[cache_key] = classes
        return classes

    except Exception as exc:
        logger.warning(
            f"[rxclass_client] Network or parsing error for RxCUI={clean_rxcui}, "
            f"relaSource={rela_source}: {exc}"
        )
        return []


def get_drug_classes(
    rxcui: str,
    rela_sources: Optional[List[str]] = None,
    client: Optional[httpx.Client] = None,
) -> List[Dict[str, Any]]:
    """
    Fetches all drug classes for a given RxCUI across specified relaSources
    (defaults to ATC and MEDRT per spec).

    Deduplicates across sources by (class_id, source).
    """
    clean_rxcui = str(rxcui).strip()
    if not clean_rxcui:
        return []

    sources = rela_sources or DEFAULT_RELA_SOURCES
    all_classes: List[Dict[str, Any]] = []
    seen = set()

    for src in sources:
        classes = fetch_classes_for_source(clean_rxcui, rela_source=src, client=client)
        for cls_obj in classes:
            key = (cls_obj["class_id"], cls_obj["source"])
            if key not in seen:
                seen.add(key)
                all_classes.append(cls_obj)

    logger.debug(
        f"[rxclass_client] RxCUI {clean_rxcui} resolved to {len(all_classes)} "
        f"classes across {sources}."
    )
    return all_classes


def clear_cache() -> None:
    """Clears the in-memory RxClass lookup cache."""
    _RXCLASS_CACHE.clear()
