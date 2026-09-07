"""
INTERNAL ONLY — DO NOT IMPORT IN USER-FACING MODULES OR API RESPONSES.

This module provides an internal client for resolving Pakistani drug brand names
and registrations via the Drug Regulatory Authority of Pakistan (DRAP) undocumented
endpoints.

CRITICAL ARCHITECTURAL CONSTRAINTS (per PROJECT_SPEC.md & safety design):
1. DRAP's public data is provisional and NOT intended for research, citation,
   or clinical safety claims.
2. This client is strictly internal for brand -> active generic entity resolution.
3. This client and its data MUST NEVER be imported, referenced, or surfaced
   by any service, route, or helper that constructs user-facing API responses,
   UI components, or citations.
4. User-facing clinical safety data must be strictly grounded in verified authorities
   (RxNorm, openFDA labels, RxClass).
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DRAP_BASE_URL = "https://eapp.dra.gov.pk/productView.php"

# Dotted-leader regex: e.g. "Guaifenesin ...... 100 mg", "Amoxicillin ...... 400 mg"
DOT_LEADER_RE = re.compile(r"^(?P<name>.*?)\s*\.{2,}\s*(?P<amount>.*)$")

# Trailing dose format regex:
# Matches standard pharmaceutical dose amounts and units e.g. "500 mg", "500mg", "250mg/5ml", "1 g", "100 IU/ml", "0.9% w/v"
UNIT_PATTERN = r"(?:mg|gm?|mcg|µg|ug|ng|kg|ml|l|ltr|iu|ui|units?|meq|mmol|%|w\/v|w\/w|v\/v)(?:[\s\/]+[a-zA-Z0-9%]+)*"
TRAILING_DOSE_RE = re.compile(
    rf"^(?P<name>.*?)\s+(?P<amount>(?:\d+(?:\.\d+)?|\d+\/\d+)\s*{UNIT_PATTERN})$",
    re.IGNORECASE,
)


def parse_composition(raw_composition: Optional[str]) -> List[Dict[str, Optional[str]]]:
    """
    Parses raw drug composition strings into a list of structured active ingredients
    with their respective dose amounts: [{'name': '...', 'amount': '...'}, ...].

    Handles:
    - Dotted-leader formats: 'Guaifenesin ...... 100 mg'
    - Plain trailing-dose formats: 'PARACETAMOL 500 mg', 'PARACETAMOL 500mg'
    - Multi-line / HTML break formats: 'Ingredient 1 ...... 10mg<br>Ingredient 2 ...... 20mg'
    - Comma / plus separated multi-ingredients: 'PARACETAMOL 500mg, CAFFEINE 65mg'
    """
    if not raw_composition or not raw_composition.strip():
        return []

    # Normalize HTML line breaks and carriage returns to standard newlines
    normalized_text = re.sub(r"(?i)<br\s*/?>", "\n", raw_composition)
    lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]

    ingredients: List[Dict[str, Optional[str]]] = []

    for line in lines:
        # Check dotted-leader format first
        dot_match = DOT_LEADER_RE.match(line)
        if dot_match:
            name = dot_match.group("name").strip()
            amount = dot_match.group("amount").strip()
            ingredients.append({"name": name, "amount": amount if amount else None})
            continue

        # If no dotted leader, check for multiple ingredients on the same line
        # separated by commas, semicolons, or ' + '
        sub_parts = [
            part.strip()
            for part in re.split(r"[,;]|\s\+\s", line)
            if part.strip()
        ]

        for part in sub_parts:
            # Check if sub-part matches dotted leader
            sub_dot = DOT_LEADER_RE.match(part)
            if sub_dot:
                name = sub_dot.group("name").strip()
                amount = sub_dot.group("amount").strip()
                ingredients.append({"name": name, "amount": amount if amount else None})
                continue

            # Check trailing-dose format
            dose_match = TRAILING_DOSE_RE.match(part)
            if dose_match:
                name = dose_match.group("name").strip()
                amount = dose_match.group("amount").strip()
                ingredients.append({"name": name, "amount": amount})
            else:
                # Fallback: ingredient name without detectable trailing dose unit
                ingredients.append({"name": part, "amount": None})

    return ingredients


def search(
    query: str,
    timeout: float = 15.0,
    client: Optional[httpx.Client] = None,
) -> List[Dict[str, str]]:
    """
    Searches DRAP product database by brand name query.
    GET https://eapp.dra.gov.pk/productView.php?search={query}&_type=brand%20name

    Strips the UTF-8 Byte Order Mark (BOM) before json.loads and returns
    the list of matching products: [{'id': reg_no, 'text': display_name}, ...]
    """
    if not query or not query.strip():
        return []

    params = {"search": query.strip(), "_type": "brand name"}

    def _execute(c: httpx.Client) -> List[Dict[str, str]]:
        response = c.get(DRAP_BASE_URL, params=params, timeout=timeout)
        response.raise_for_status()

        # DRAP endpoint returns UTF-8 BOM (\xef\xbb\xbf) which causes json.loads
        # to fail unless decoded with utf-8-sig or lstripped.
        decoded_content = response.content.decode("utf-8-sig").strip()
        if not decoded_content:
            return []

        data = json.loads(decoded_content)
        if isinstance(data, dict):
            return data.get("results", [])
        if isinstance(data, list):
            return data
        return []

    if client is not None:
        return _execute(client)
    with httpx.Client() as default_client:
        return _execute(default_client)


def _parse_details_html(html: str, reg_no: str) -> Dict[str, Any]:
    """
    Internal helper to parse the HTML fragment returned by DRAP productView.php.
    """
    soup = BeautifulSoup(html, "html.parser")
    fields: Dict[str, str] = {}

    # Extract all label-value pairs from the bootstrap grid elements
    for div in soup.find_all("div"):
        label_span = div.find("span", class_=lambda c: c and "d-block" in c)
        val_span = div.find("span", class_=lambda c: c and "fw-semibold" in c)

        if not label_span or not val_span:
            # Fallback: check if the div contains at least two span children
            spans = div.find_all("span")
            if len(spans) >= 2:
                label_span = spans[0]
                val_span = spans[-1]

        if label_span and val_span:
            label = label_span.get_text(strip=True).lower()
            # Preserve line breaks for composition (e.g. from <br> tags)
            value = val_span.get_text(separator="\n", strip=True)
            if label and label not in fields:
                fields[label] = value

    raw_comp = fields.get("composition", "")
    parsed_comp = parse_composition(raw_comp)
    company = fields.get("company name", "")
    reg_status = fields.get("registration status", "")

    return {
        "registration_no": fields.get("registration no", reg_no),
        "product_name": fields.get("product name", ""),
        "company": company,
        "company_name": company,
        "registration_status": reg_status,
        "registration_date": fields.get("registration date", ""),
        "dosage_form": fields.get("dosage form", ""),
        "composition": parsed_comp,
        "composition_raw": raw_comp,
        "raw_composition": raw_comp,
        "route_of_admin": fields.get("route of admin", ""),
        "used_for": fields.get("used for", ""),
        "pack_size": fields.get("pack size(s)", ""),
        "raw_fields": fields,
    }


def get_product_details(
    reg_no: str,
    timeout: float = 15.0,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """
    Retrieves and parses product details from DRAP for a given registration number.
    POST https://eapp.dra.gov.pk/productView.php with form body webRegNo={reg_no}

    Parses the HTML fragment with BeautifulSoup and extracts:
    - composition (structured list of active ingredients via parse_composition)
    - composition_raw / raw_composition (unparsed text)
    - company / company_name
    - registration_status
    - product_name
    - dosage_form
    - registration_date
    - registration_no
    """
    if not reg_no or not reg_no.strip():
        raise ValueError("Registration number (reg_no) must not be empty.")

    payload = {"webRegNo": reg_no.strip()}

    def _execute(c: httpx.Client) -> Dict[str, Any]:
        response = c.post(DRAP_BASE_URL, data=payload, timeout=timeout)
        response.raise_for_status()
        html = response.content.decode("utf-8-sig")
        return _parse_details_html(html, reg_no.strip())

    if client is not None:
        return _execute(client)
    with httpx.Client() as default_client:
        return _execute(default_client)


async def search_async(
    query: str,
    timeout: float = 15.0,
    client: Optional[httpx.AsyncClient] = None,
) -> List[Dict[str, str]]:
    """
    Asynchronous version of search().
    """
    if not query or not query.strip():
        return []

    params = {"search": query.strip(), "_type": "brand name"}

    async def _execute(c: httpx.AsyncClient) -> List[Dict[str, str]]:
        response = await c.get(DRAP_BASE_URL, params=params, timeout=timeout)
        response.raise_for_status()
        decoded_content = response.content.decode("utf-8-sig").strip()
        if not decoded_content:
            return []
        data = json.loads(decoded_content)
        if isinstance(data, dict):
            return data.get("results", [])
        if isinstance(data, list):
            return data
        return []

    if client is not None:
        return await _execute(client)
    async with httpx.AsyncClient() as default_client:
        return await _execute(default_client)


async def get_product_details_async(
    reg_no: str,
    timeout: float = 15.0,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """
    Asynchronous version of get_product_details().
    """
    if not reg_no or not reg_no.strip():
        raise ValueError("Registration number (reg_no) must not be empty.")

    payload = {"webRegNo": reg_no.strip()}

    async def _execute(c: httpx.AsyncClient) -> Dict[str, Any]:
        response = await c.post(DRAP_BASE_URL, data=payload, timeout=timeout)
        response.raise_for_status()
        html = response.content.decode("utf-8-sig")
        return _parse_details_html(html, reg_no.strip())

    if client is not None:
        return await _execute(client)
    async with httpx.AsyncClient() as default_client:
        return await _execute(default_client)


class DRAPClient:
    """
    Internal client wrapper for DRAP operations supporting connection pooling.
    Must never be used in user-facing routes or responses.
    """

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None

    def __enter__(self) -> "DRAPClient":
        self._client = httpx.Client(timeout=self.timeout)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._client is not None:
            self._client.close()
            self._client = None

    def search(self, query: str) -> List[Dict[str, str]]:
        return search(query, timeout=self.timeout, client=self._client)

    def get_product_details(self, reg_no: str) -> Dict[str, Any]:
        return get_product_details(reg_no, timeout=self.timeout, client=self._client)


# Convenient module-level aliases
search_drap = search
get_drap_product_details = get_product_details

# ==============================================================================
# RxNorm Normalizer & openFDA Label Retriever
# ==============================================================================

RXNORM_BASE_URL = "https://rxnav.nlm.nih.gov"
OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
NOT_PRESENT_IN_LABEL = "(not present in this label)"


def rxnorm_normalize(
    generic_name: str,
    timeout: float = 15.0,
    client: Optional[httpx.Client] = None,
    fallback_to_original: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Normalizes a generic/INN drug name to its canonical standardized name and RxCUI
    via NIH RxNorm's two-step lookup:
    1. GET https://rxnav.nlm.nih.gov/REST/rxcui.json?name={name}&search=2
       Resolves name -> RxCUI concept ID (normalized/fuzzy matching).
    2. GET https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/property.json?propName=RxNorm%20Name
       Resolves RxCUI -> canonical standardized name (e.g., 'Paracetamol' -> 'acetaminophen').

    Returns:
        (rxcui, canonical_name) on success, or (None, None) if no match.
        If fallback_to_original=True and no match was found, returns (None, generic_name).
    """
    if not generic_name or not generic_name.strip():
        return (None, generic_name if fallback_to_original else None)

    cleaned_name = generic_name.strip()

    def _execute(c: httpx.Client) -> Tuple[Optional[str], Optional[str]]:
        # Step 1: Query RxCUI concept ID
        step1_url = f"{RXNORM_BASE_URL}/REST/rxcui.json"
        resp1 = c.get(step1_url, params={"name": cleaned_name, "search": 2}, timeout=timeout)
        if resp1.status_code != 200:
            return (None, cleaned_name if fallback_to_original else None)

        data1 = resp1.json()
        rxnorm_ids = data1.get("idGroup", {}).get("rxnormId", [])
        if not rxnorm_ids:
            return (None, cleaned_name if fallback_to_original else None)

        rxcui = str(rxnorm_ids[0])

        # Step 2: Query canonical RxNorm Name property
        step2_url = f"{RXNORM_BASE_URL}/REST/rxcui/{rxcui}/property.json"
        resp2 = c.get(step2_url, params={"propName": "RxNorm Name"}, timeout=timeout)
        if resp2.status_code != 200:
            # Fall back to original name if property lookup fails
            return (rxcui, cleaned_name)

        data2 = resp2.json()
        prop_concepts = (
            data2.get("propConceptGroup", {})
            .get("propConcept", [])
        )
        canonical_name = None
        for prop in prop_concepts:
            if prop.get("propName") == "RxNorm Name":
                canonical_name = prop.get("propValue")
                break

        if not canonical_name:
            canonical_name = cleaned_name

        return (rxcui, canonical_name)

    if client is not None:
        return _execute(client)
    with httpx.Client() as default_client:
        return _execute(default_client)


async def rxnorm_normalize_async(
    generic_name: str,
    timeout: float = 15.0,
    client: Optional[httpx.AsyncClient] = None,
    fallback_to_original: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Asynchronous version of rxnorm_normalize().
    """
    if not generic_name or not generic_name.strip():
        return (None, generic_name if fallback_to_original else None)

    cleaned_name = generic_name.strip()

    async def _execute(c: httpx.AsyncClient) -> Tuple[Optional[str], Optional[str]]:
        step1_url = f"{RXNORM_BASE_URL}/REST/rxcui.json"
        resp1 = await c.get(step1_url, params={"name": cleaned_name, "search": 2}, timeout=timeout)
        if resp1.status_code != 200:
            return (None, cleaned_name if fallback_to_original else None)

        data1 = resp1.json()
        rxnorm_ids = data1.get("idGroup", {}).get("rxnormId", [])
        if not rxnorm_ids:
            return (None, cleaned_name if fallback_to_original else None)

        rxcui = str(rxnorm_ids[0])

        step2_url = f"{RXNORM_BASE_URL}/REST/rxcui/{rxcui}/property.json"
        resp2 = await c.get(step2_url, params={"propName": "RxNorm Name"}, timeout=timeout)
        if resp2.status_code != 200:
            return (rxcui, cleaned_name)

        data2 = resp2.json()
        prop_concepts = (
            data2.get("propConceptGroup", {})
            .get("propConcept", [])
        )
        canonical_name = None
        for prop in prop_concepts:
            if prop.get("propName") == "RxNorm Name":
                canonical_name = prop.get("propValue")
                break

        if not canonical_name:
            canonical_name = cleaned_name

        return (rxcui, canonical_name)

    if client is not None:
        return await _execute(client)
    async with httpx.AsyncClient() as default_client:
        return await _execute(default_client)


def _extract_fda_field(item: Dict[str, Any], field_name: str) -> str:
    """
    Helper to safely extract FDA label text fields.
    If the field is missing or empty, returns '(not present in this label)'.
    """
    val = item.get(field_name)
    if not val:
        return NOT_PRESENT_IN_LABEL
    if isinstance(val, list):
        joined = "\n\n".join(str(v).strip() for v in val if v).strip()
        return joined or NOT_PRESENT_IN_LABEL
    return str(val).strip() or NOT_PRESENT_IN_LABEL


def fetch_fda_label(
    rxnorm_name: str,
    timeout: float = 15.0,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """
    Fetches the manufacturer drug label from openFDA API for a given canonical generic name.
    GET https://api.fda.gov/drug/label.json?search=openfda.generic_name:"{rxnorm_name}"&limit=1

    Extracts:
    - drug_interactions
    - warnings
    - boxed_warning

    Missing or empty fields are set to "(not present in this label)" rather than raising an error.
    """
    if not rxnorm_name or not rxnorm_name.strip():
        return {
            "generic_name": rxnorm_name,
            "drug_interactions": NOT_PRESENT_IN_LABEL,
            "warnings": NOT_PRESENT_IN_LABEL,
            "boxed_warning": NOT_PRESENT_IN_LABEL,
            "raw_response": None,
            "found": False,
        }

    cleaned_name = rxnorm_name.strip()
    search_query = f'openfda.generic_name:"{cleaned_name}"'

    def _execute(c: httpx.Client) -> Dict[str, Any]:
        resp = c.get(
            OPENFDA_LABEL_URL,
            params={"search": search_query, "limit": 1},
            timeout=timeout,
        )
        if resp.status_code == 404:
            # openFDA returns 404 when no label matches the query
            return {
                "generic_name": cleaned_name,
                "drug_interactions": NOT_PRESENT_IN_LABEL,
                "warnings": NOT_PRESENT_IN_LABEL,
                "boxed_warning": NOT_PRESENT_IN_LABEL,
                "raw_response": None,
                "found": False,
            }
        resp.raise_for_status()

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return {
                "generic_name": cleaned_name,
                "drug_interactions": NOT_PRESENT_IN_LABEL,
                "warnings": NOT_PRESENT_IN_LABEL,
                "boxed_warning": NOT_PRESENT_IN_LABEL,
                "raw_response": None,
                "found": False,
            }

        item = results[0]
        return {
            "generic_name": cleaned_name,
            "drug_interactions": _extract_fda_field(item, "drug_interactions"),
            "warnings": _extract_fda_field(item, "warnings"),
            "boxed_warning": _extract_fda_field(item, "boxed_warning"),
            "raw_response": item,
            "found": True,
        }

    if client is not None:
        return _execute(client)
    with httpx.Client() as default_client:
        return _execute(default_client)


async def fetch_fda_label_async(
    rxnorm_name: str,
    timeout: float = 15.0,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """
    Asynchronous version of fetch_fda_label().
    """
    if not rxnorm_name or not rxnorm_name.strip():
        return {
            "generic_name": rxnorm_name,
            "drug_interactions": NOT_PRESENT_IN_LABEL,
            "warnings": NOT_PRESENT_IN_LABEL,
            "boxed_warning": NOT_PRESENT_IN_LABEL,
            "raw_response": None,
            "found": False,
        }

    cleaned_name = rxnorm_name.strip()
    search_query = f'openfda.generic_name:"{cleaned_name}"'

    async def _execute(c: httpx.AsyncClient) -> Dict[str, Any]:
        resp = await c.get(
            OPENFDA_LABEL_URL,
            params={"search": search_query, "limit": 1},
            timeout=timeout,
        )
        if resp.status_code == 404:
            return {
                "generic_name": cleaned_name,
                "drug_interactions": NOT_PRESENT_IN_LABEL,
                "warnings": NOT_PRESENT_IN_LABEL,
                "boxed_warning": NOT_PRESENT_IN_LABEL,
                "raw_response": None,
                "found": False,
            }
        resp.raise_for_status()

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return {
                "generic_name": cleaned_name,
                "drug_interactions": NOT_PRESENT_IN_LABEL,
                "warnings": NOT_PRESENT_IN_LABEL,
                "boxed_warning": NOT_PRESENT_IN_LABEL,
                "raw_response": None,
                "found": False,
            }

        item = results[0]
        return {
            "generic_name": cleaned_name,
            "drug_interactions": _extract_fda_field(item, "drug_interactions"),
            "warnings": _extract_fda_field(item, "warnings"),
            "boxed_warning": _extract_fda_field(item, "boxed_warning"),
            "raw_response": item,
            "found": True,
        }

    if client is not None:
        return await _execute(client)
    async with httpx.AsyncClient() as default_client:
        return await _execute(default_client)


def resolve_and_persist_product(
    reg_no: str,
    brand_display_name: str,
    db: Any,
) -> Optional[Any]:
    """
    Synchronously resolves a single drug product from DRAP details -> RxNorm -> openFDA,
    persists it into PostgreSQL (drugs, drug_ingredients, fda_labels), and returns the Drug instance.

    INTERNAL ONLY: Never expose reg_no or DRAP fields in external API returns.
    """
    from datetime import datetime, timezone
    from app.db.models import Drug, DrugIngredient, FDALabel

    try:
        details = get_product_details(reg_no)
        resolved_brand_name = details.get("product_name") or brand_display_name
        dosage_form = details.get("dosage_form")
        company_name = details.get("company_name") or details.get("company")
        raw_comp = details.get("composition_raw", "")
        ingredients_list = details.get("composition", [])

        if not ingredients_list and raw_comp:
            ingredients_list = parse_composition(raw_comp)

        resolved_ingredients = []
        for ing in ingredients_list:
            raw_ing_name = ing.get("name", "").strip()
            dose = ing.get("amount")
            if not raw_ing_name:
                continue

            rxcui, rxnorm_name = rxnorm_normalize(raw_ing_name, fallback_to_original=True)
            canonical_name = rxnorm_name or raw_ing_name

            # Cache openFDA label if RxCUI is present
            if rxcui and canonical_name:
                existing_label = db.query(FDALabel).filter(FDALabel.rxcui == rxcui).first()
                if not existing_label:
                    fda_data = fetch_fda_label(canonical_name)
                    new_label = FDALabel(
                        rxcui=rxcui,
                        rxnorm_name=canonical_name,
                        drug_interactions=fda_data.get("drug_interactions"),
                        warnings=fda_data.get("warnings"),
                        boxed_warning=fda_data.get("boxed_warning"),
                        raw_response=fda_data.get("raw_response"),
                        fetched_at=datetime.now(timezone.utc),
                    )
                    db.add(new_label)
                    db.flush()

            resolved_ingredients.append({
                "generic_name": raw_ing_name,
                "dose": dose,
                "rxcui": rxcui,
                "rxnorm_name": rxnorm_name,
            })

        # Save or update drug in drugs table
        existing_drug = db.query(Drug).filter(
            (Drug.drap_reg_no == reg_no) | (Drug.brand_name == resolved_brand_name)
        ).first()

        now = datetime.now(timezone.utc)
        if existing_drug:
            drug = existing_drug
            drug.brand_name = resolved_brand_name
            drug.drap_reg_no = reg_no
            drug.dosage_form = dosage_form
            drug.company_name = company_name
            drug.resolved_at = now
            db.query(DrugIngredient).filter(DrugIngredient.drug_id == drug.id).delete()
        else:
            drug = Drug(
                brand_name=resolved_brand_name,
                drap_reg_no=reg_no,
                dosage_form=dosage_form,
                company_name=company_name,
                resolved_at=now,
                created_at=now,
            )
            db.add(drug)

        db.flush()

        for ing_data in resolved_ingredients:
            db_ing = DrugIngredient(
                drug_id=drug.id,
                generic_name=ing_data["generic_name"],
                dose=ing_data["dose"],
                rxcui=ing_data["rxcui"],
                rxnorm_name=ing_data["rxnorm_name"],
            )
            db.add(db_ing)

        db.commit()
        db.refresh(drug)
        return drug

    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to resolve and persist product {reg_no}: {exc}", exc_info=True)
        return None


def resolve_drug(
    query: str,
    db: Any,
) -> Tuple[str, Optional[Any], Optional[List[Dict[str, Any]]]]:
    """
    Resolves a drug name query per PROJECT_SPEC.md lines 227-243:
    1. Dataset lookup first in PostgreSQL 'drugs' table.
    2. DRAP search fallback if not found in dataset.
    3. Synchronous execution.

    Returns:
        (status, resolved_drug, candidates)
        where status is "resolved" | "ambiguous" | "not_found"
    """
    from sqlalchemy import func
    from app.db.models import Drug

    q = query.strip()
    if not q:
        return "not_found", None, None

    # 1. Dataset lookup first: Exact match (case-insensitive)
    exact_matches = db.query(Drug).filter(func.lower(Drug.brand_name) == q.lower()).all()
    if len(exact_matches) == 1:
        return "resolved", exact_matches[0], None
    elif len(exact_matches) > 1:
        candidates = [
            {"drug_id": d.id, "display_name": d.brand_name, "dosage_form": d.dosage_form}
            for d in exact_matches
        ]
        return "ambiguous", None, candidates

    # Substring / ILIKE match in dataset
    substring_matches = db.query(Drug).filter(Drug.brand_name.ilike(f"%{q}%")).all()
    if len(substring_matches) == 1:
        return "resolved", substring_matches[0], None
    elif len(substring_matches) > 1:
        candidates = [
            {"drug_id": d.id, "display_name": d.brand_name, "dosage_form": d.dosage_form}
            for d in substring_matches
        ]
        return "ambiguous", None, candidates

    # 2. DRAP fallback if not found in dataset
    try:
        drap_results = search(q)
    except Exception as exc:
        logger.error(f"DRAP fallback search failed for query '{q}': {exc}")
        return "not_found", None, None

    if not drap_results:
        return "not_found", None, None

    if len(drap_results) == 1:
        reg_no = drap_results[0].get("id")
        display_name = drap_results[0].get("text", q).rstrip(".")
        drug = resolve_and_persist_product(reg_no, display_name, db)
        if drug:
            return "resolved", drug, None
        return "not_found", None, None

    # Check if any single DRAP result is an exact case-insensitive match for the query
    exact_drap = [
        item for item in drap_results
        if item.get("text", "").rstrip(".").strip().lower() == q.lower()
    ]
    if len(exact_drap) == 1:
        reg_no = exact_drap[0].get("id")
        display_name = exact_drap[0].get("text", q).rstrip(".")
        drug = resolve_and_persist_product(reg_no, display_name, db)
        if drug:
            return "resolved", drug, None

    # Multiple candidates -> ambiguous.
    # Disambiguation picker: product display names only.
    seen_names = set()
    candidates = []
    for item in drap_results:
        display_name = item.get("text", "").rstrip(".").strip()
        if not display_name or display_name in seen_names:
            continue
        seen_names.add(display_name)

        existing = db.query(Drug).filter(
            (Drug.drap_reg_no == item.get("id")) | (Drug.brand_name == display_name)
        ).first()

        candidates.append({
            "drug_id": existing.id if existing else None,
            "display_name": display_name,
            "dosage_form": existing.dosage_form if existing else None,
        })

    return "ambiguous", None, candidates


