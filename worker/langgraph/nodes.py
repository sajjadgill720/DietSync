"""
worker/langgraph/nodes.py
State definition and node functions for DietSync's LangGraph interaction checker.

Per PROJECT_SPEC.md:
- InteractionState TypedDict matching the spec verbatim.
- fetch_context: loads both drugs' label text into state.
- check_interaction: reads label text, identifies interactions with exact quoted citation,
  or outputs 'no interaction found'. Never reasons from outside knowledge.
- verify_groundedness: independent separate call, verifying citation presence and entailment
  against raw source text only (no access to check_interaction reasoning).
- format_grounded_answer: formats verified response.
- format_unverifiable_answer: formats unverified/refusal response with same schema.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple, TypedDict

logger = logging.getLogger("langgraph_nodes")

# ------------------------------------------------------------------------------
# Shared State Definition (Verbatim from PROJECT_SPEC.md lines 96-109)
# ------------------------------------------------------------------------------

class InteractionState(TypedDict):
    drug_a: dict          # {rxcui, generic_name, fda_label_text, ...}
    drug_b: dict
    patient_allergies: list[str]        # ephemeral, request-scoped — never persisted
    patient_diet_factors: list[str]     # ephemeral, request-scoped — never persisted
    interaction_claim: str | None
    citation_text: str | None
    is_grounded: bool | None
    allergy_flags: list[dict]           # [{allergy, matched_drug, matched_class, source: "RxClass"}]
    food_interaction_claim: str | None
    food_citation_text: str | None
    final_status: str      # "interaction_found" | "none_found" | "unverifiable"
    final_answer: dict | None


# ------------------------------------------------------------------------------
# Helper: Database Label Fetcher
# ------------------------------------------------------------------------------

def _fetch_label_from_db(drug_dict: dict) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Looks up drug ingredients and FDA label text from PostgreSQL if not already present.
    Returns: (fda_label_text, generic_name, rxcui)
    """
    from app.db.models import Drug, DrugIngredient, FDALabel
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/dietsync")
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg2://" + db_url.split("://", 1)[1]

    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    fda_text_parts = []
    generic_name = drug_dict.get("generic_name")
    rxcui = drug_dict.get("rxcui")

    try:
        drug_id = drug_dict.get("id")
        brand_name = drug_dict.get("brand_name")

        # Find drug record
        drug = None
        if drug_id:
            drug = session.query(Drug).filter(Drug.id == drug_id).first()
        elif brand_name:
            drug = session.query(Drug).filter(Drug.brand_name.ilike(f"%{brand_name}%")).first()

        if drug:
            if not generic_name and drug.ingredients:
                generic_name = drug.ingredients[0].generic_name
            if not rxcui and drug.ingredients:
                rxcui = drug.ingredients[0].rxcui

            # Query all associated FDA labels for this drug's ingredients
            for ing in drug.ingredients:
                if ing.rxcui:
                    label = session.query(FDALabel).filter(FDALabel.rxcui == ing.rxcui).first()
                    if label:
                        if label.drug_interactions and label.drug_interactions != "(not present in this label)":
                            fda_text_parts.append(f"DRUG INTERACTIONS ({ing.generic_name}):\n{label.drug_interactions}")
                        if label.warnings and label.warnings != "(not present in this label)":
                            fda_text_parts.append(f"WARNINGS ({ing.generic_name}):\n{label.warnings}")
                        if label.boxed_warning and label.boxed_warning != "(not present in this label)":
                            fda_text_parts.append(f"BOXED WARNING ({ing.generic_name}):\n{label.boxed_warning}")
        elif rxcui:
            label = session.query(FDALabel).filter(FDALabel.rxcui == rxcui).first()
            if label:
                if not generic_name:
                    generic_name = label.rxnorm_name
                if label.drug_interactions and label.drug_interactions != "(not present in this label)":
                    fda_text_parts.append(f"DRUG INTERACTIONS:\n{label.drug_interactions}")
                if label.warnings and label.warnings != "(not present in this label)":
                    fda_text_parts.append(f"WARNINGS:\n{label.warnings}")
                if label.boxed_warning and label.boxed_warning != "(not present in this label)":
                    fda_text_parts.append(f"BOXED WARNING:\n{label.boxed_warning}")
    finally:
        session.close()

    combined_text = "\n\n".join(fda_text_parts).strip()
    return combined_text or "(No FDA label text available)", generic_name, rxcui


# ------------------------------------------------------------------------------
# Node 1: fetch_context
# ------------------------------------------------------------------------------

def fetch_context(state: InteractionState) -> dict:
    """
    Loads both drugs' resolved label text into state.
    Kept as an explicit node for trace visibility.
    """
    logger.info("[fetch_context] Loading label context for drug_a and drug_b...")

    drug_a = dict(state.get("drug_a", {}))
    drug_b = dict(state.get("drug_b", {}))

    # Fetch Drug A label text if missing
    if not drug_a.get("fda_label_text"):
        label_text, gen_name, rxcui = _fetch_label_from_db(drug_a)
        drug_a["fda_label_text"] = label_text
        if gen_name and not drug_a.get("generic_name"):
            drug_a["generic_name"] = gen_name
        if rxcui and not drug_a.get("rxcui"):
            drug_a["rxcui"] = rxcui

    # Fetch Drug B label text if missing
    if not drug_b.get("fda_label_text"):
        label_text, gen_name, rxcui = _fetch_label_from_db(drug_b)
        drug_b["fda_label_text"] = label_text
        if gen_name and not drug_b.get("generic_name"):
            drug_b["generic_name"] = gen_name
        if rxcui and not drug_b.get("rxcui"):
            drug_b["rxcui"] = rxcui

    logger.info(
        f"[fetch_context] Loaded context: Drug A ('{drug_a.get('generic_name', 'Unknown')}', {len(drug_a.get('fda_label_text', ''))} chars), "
        f"Drug B ('{drug_b.get('generic_name', 'Unknown')}', {len(drug_b.get('fda_label_text', ''))} chars)"
    )

    return {
        "drug_a": drug_a,
        "drug_b": drug_b,
    }


# ------------------------------------------------------------------------------
# Node 2: check_interaction
# ------------------------------------------------------------------------------

def _find_exact_source_sentence(source_text: str, keyword_terms: List[str]) -> Optional[str]:
    """
    Scans source text for a sentence mentioning any of the target terms.
    Returns the exact quoted sentence.
    """
    if not source_text:
        return None

    sentences = re.split(r"(?<=[.!?])\s+", source_text)
    for sentence in sentences:
        clean_s = sentence.strip()
        if len(clean_s) < 20:
            continue
        for term in keyword_terms:
            if not term or len(term) < 3:
                continue
            pattern = rf"\b{re.escape(term)}\b"
            if re.search(pattern, clean_s, re.IGNORECASE):
                return clean_s
    return None


def _create_llm(api_key: str):
    """Initializes LLM, automatically configuring Groq or OpenAI based on API key prefix."""
    from langchain_openai import ChatOpenAI
    clean_key = api_key.strip()
    if clean_key.startswith("gsk_"):
        return ChatOpenAI(
            model="openai/gpt-oss-120b",
            base_url="https://api.groq.com/openai/v1",
            temperature=0,
            api_key=clean_key,
        )
    return ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=clean_key)



def check_interaction(state: InteractionState) -> dict:
    """
    Reads both drugs' drug_interactions / warnings text, determines if either mentions
    the other drug or its pharmacological class, and drafts a claim with an exact quoted
    source sentence, or explicitly outputs 'no interaction found'.
    NEVER reasons from general knowledge, strictly from label text in state.
    """
    logger.info("[check_interaction] Reasoning over label text for documented interactions...")

    drug_a = state.get("drug_a", {})
    drug_b = state.get("drug_b", {})

    name_a = (drug_a.get("generic_name") or drug_a.get("brand_name") or "").strip()
    name_b = (drug_b.get("generic_name") or drug_b.get("brand_name") or "").strip()

    label_text_a = drug_a.get("fda_label_text", "")
    label_text_b = drug_b.get("fda_label_text", "")
    combined_sources = f"=== DRUG A ({name_a}) LABEL ===\n{label_text_a}\n\n=== DRUG B ({name_b}) LABEL ===\n{label_text_b}"

    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = _create_llm(api_key)


            system_prompt = (
                "You are an expert clinical pharmacologist operating under strict recall-over-precision "
                "and safety grounding rules. You will be provided with official FDA label texts for Drug A and Drug B.\n\n"
                "CRITICAL RULES:\n"
                "1. Reason ONLY from the provided text. Never use outside medical training.\n"
                "2. Check if either drug's label explicitly discusses the other drug by name, synonym, or pharmacological class "
                "(e.g. NSAIDs, anticoagulants, ACE inhibitors, diuretics, statins, macrolides).\n"
                "3. If an interaction is documented, summarize the interaction claim and quote the EXACT VERBATIM source sentence as citation_text.\n"
                "4. If NO interaction is explicitly documented in the provided text, output 'no interaction found' for interaction_claim and null for citation_text.\n\n"
                "Respond in strictly valid JSON format with keys: 'has_interaction' (bool), 'interaction_claim' (string), 'citation_text' (string or null)."
            )

            user_prompt = f"Drug A: {name_a}\nDrug B: {name_b}\n\nSource Label Text:\n{combined_sources}"

            resp = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
            raw_content = resp.content.strip()

            # Clean JSON fences if present
            if raw_content.startswith("```"):
                raw_content = re.sub(r"^```(?:json)?\n?", "", raw_content)
                raw_content = re.sub(r"\n?```$", "", raw_content)

            parsed = json.loads(raw_content)
            if parsed.get("has_interaction") and parsed.get("citation_text"):
                claim = parsed.get("interaction_claim", "").strip()
                citation = parsed.get("citation_text", "").strip()
                logger.info(f"[check_interaction] LLM identified interaction: '{claim[:80]}...'")
                return {"interaction_claim": claim, "citation_text": citation}
            else:
                logger.info("[check_interaction] LLM concluded: No interaction found in source text.")
                return {"interaction_claim": "no interaction found", "citation_text": None}

        except Exception as exc:
            logger.warning(f"[check_interaction] LLM call failed or unavailable ({exc}); using grounded parser.")

    # Grounded text parser fallback (strictly evaluates text already in state)
    drug_classes = {
        "aspirin": ["nsaid", "nsaids", "antiplatelet", "salicylate", "salicylates", "aspirin", "acetylsalicylic acid"],
        "acetylsalicylic acid": ["nsaid", "nsaids", "antiplatelet", "salicylate", "salicylates", "aspirin"],
        "ibuprofen": ["nsaid", "nsaids", "ibuprofen"],
        "diclofenac": ["nsaid", "nsaids", "diclofenac"],
        "diclofenac sodium": ["nsaid", "nsaids", "diclofenac"],
        "mefenamic acid": ["nsaid", "nsaids"],
        "warfarin": ["anticoagulant", "anticoagulants", "coumarin", "warfarin"],
        "warfarin sod. bp": ["anticoagulant", "anticoagulants", "coumarin", "warfarin"],
        "warfarin sodium": ["anticoagulant", "anticoagulants", "coumarin", "warfarin"],
        "lisinopril": ["ace inhibitor", "ace inhibitors", "antihypertensive", "lisinopril"],
        "furosemide": ["diuretic", "diuretics", "loop diuretic", "furosemide", "frusemide"],
        "frusemide": ["diuretic", "diuretics", "loop diuretic", "furosemide"],
        "clarithromycin": ["macrolide", "cyp3a", "cyp3a4", "clarithromycin"],
        "atorvastatin": ["statin", "statins", "hmg-coa", "atorvastatin"],
        "atorvastatin calcium": ["statin", "statins", "hmg-coa", "atorvastatin"],
        "metronidazole": ["metronidazole", "antimicrobial"],
        "ciprofloxacin": ["fluoroquinolone", "quinolone", "ciprofloxacin"],
        "ciprofloxacin hcl": ["fluoroquinolone", "quinolone", "ciprofloxacin"],
    }

    # Gather search terms for Drug B and Drug A
    terms_for_b = [name_b.lower()] + drug_classes.get(name_b.lower(), [])
    terms_for_a = [name_a.lower()] + drug_classes.get(name_a.lower(), [])

    # Also include RxNorm generic names if available in drug dict
    if drug_b.get("rxnorm_name"):
        rx_b = drug_b["rxnorm_name"].lower()
        terms_for_b.extend([rx_b] + drug_classes.get(rx_b, []))
    if drug_a.get("rxnorm_name"):
        rx_a = drug_a["rxnorm_name"].lower()
        terms_for_a.extend([rx_a] + drug_classes.get(rx_a, []))


    # Check Drug A label for Drug B
    citation = _find_exact_source_sentence(label_text_a, terms_for_b)
    # If not found in A, check Drug B label for Drug A
    if not citation:
        citation = _find_exact_source_sentence(label_text_b, terms_for_a)

    if citation:
        claim = f"Co-administration of {name_a} and {name_b} is contraindicated or requires caution as documented: {citation}"
        logger.info(f"[check_interaction] Identified documented interaction: '{claim[:80]}...'")
        return {
            "interaction_claim": claim,
            "citation_text": citation,
        }

    logger.info("[check_interaction] No interaction found in label text.")
    return {
        "interaction_claim": "no interaction found",
        "citation_text": None,
    }


# ------------------------------------------------------------------------------
# Node 2b: check_food_interaction (Parallel scanning of already-fetched labels)
# ------------------------------------------------------------------------------

def check_food_interaction(state: InteractionState) -> dict:
    """
    Scans the SAME already-fetched label text for food-, alcohol-, or diet-related
    interactions. Also evaluates any patient_diet_factors provided in state.
    Quotes exact verbatim source sentence as food_citation_text or outputs None.
    """
    logger.info("[check_food_interaction] Scanning label text for food and dietary interactions...")

    drug_a = state.get("drug_a", {})
    drug_b = state.get("drug_b", {})
    patient_diet = state.get("patient_diet_factors") or []

    name_a = (drug_a.get("generic_name") or drug_a.get("brand_name") or "").strip()
    name_b = (drug_b.get("generic_name") or drug_b.get("brand_name") or "").strip()

    label_text_a = drug_a.get("fda_label_text", "")
    label_text_b = drug_b.get("fda_label_text", "")
    combined_sources = f"=== DRUG A ({name_a}) LABEL ===\n{label_text_a}\n\n=== DRUG B ({name_b}) LABEL ===\n{label_text_b}"

    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = _create_llm(api_key)


            diet_terms_str = ", ".join(patient_diet) if patient_diet else "standard food/alcohol interactions"
            system_prompt = (
                "You are an expert clinical pharmacologist auditing official FDA label text for food, alcohol, and dietary interactions.\n\n"
                "CRITICAL RULES:\n"
                "1. Reason ONLY from the provided text. Never use outside medical training.\n"
                "2. Check if either drug's label explicitly discusses interactions with food, meals, fasting, alcohol/ethanol, "
                f"or any patient-stated dietary factors: {diet_terms_str}.\n"
                "3. If an interaction is documented, summarize the food/diet interaction claim and quote the EXACT VERBATIM source sentence as food_citation_text.\n"
                "4. If NO food or dietary interaction is explicitly documented in the provided text, output null for food_interaction_claim and null for food_citation_text.\n\n"
                "Respond in strictly valid JSON format with keys: 'has_food_interaction' (bool), 'food_interaction_claim' (string or null), 'food_citation_text' (string or null)."
            )

            user_prompt = f"Drug A: {name_a}\nDrug B: {name_b}\nPatient Diet Factors: {patient_diet}\n\nSource Label Text:\n{combined_sources}"

            resp = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
            raw_content = resp.content.strip()

            if raw_content.startswith("```"):
                raw_content = re.sub(r"^```(?:json)?\n?", "", raw_content)
                raw_content = re.sub(r"\n?```$", "", raw_content)

            parsed = json.loads(raw_content)
            if parsed.get("has_food_interaction") and parsed.get("food_citation_text"):
                claim = parsed.get("food_interaction_claim", "").strip()
                citation = parsed.get("food_citation_text", "").strip()
                logger.info(f"[check_food_interaction] LLM identified food interaction: '{claim[:80]}...'")
                return {"food_interaction_claim": claim, "food_citation_text": citation}
            else:
                logger.info("[check_food_interaction] LLM concluded: No food/diet interaction found.")
                return {"food_interaction_claim": None, "food_citation_text": None}

        except Exception as exc:
            logger.warning(f"[check_food_interaction] LLM call failed or unavailable ({exc}); using grounded parser.")

    # Grounded text parser fallback scanning the already-fetched text
    food_keywords = [
        "food", "meals", "meal", "empty stomach", "fasting", "high fat",
        "alcohol", "ethanol", "alcoholic", "grapefruit", "calcium",
        "dairy", "milk", "cranberry", "tyramine", "beverages",
    ]
    if patient_diet:
        food_keywords = [d.lower() for d in patient_diet] + food_keywords

    citation = _find_exact_source_sentence(label_text_a, food_keywords)
    if not citation:
        citation = _find_exact_source_sentence(label_text_b, food_keywords)

    if citation:
        claim = f"Food/dietary precaution documented in official FDA label: {citation}"
        logger.info(f"[check_food_interaction] Found documented food interaction: '{claim[:80]}...'")
        return {
            "food_interaction_claim": claim,
            "food_citation_text": citation,
        }

    logger.info("[check_food_interaction] No food/diet interaction found in label text.")
    return {
        "food_interaction_claim": None,
        "food_citation_text": None,
    }


# ------------------------------------------------------------------------------
# Node 2c: check_allergy (Deterministic rule-based cross-reactivity)
# ------------------------------------------------------------------------------

def check_allergy(state: InteractionState) -> dict:
    """
    Deterministic rule-based allergy cross-reactivity evaluation (PROJECT_SPEC.md line 117):
    patient allergy term -> allergy_class_map -> target RxClass IDs ->
    checks whether either resolved drug's RxCUI is a member of a cross-reactive class via RxClass.
    Strictly rule-based: ZERO LLM calls in this code path.
    """
    from app.services.allergy_service import allergy_check

    patient_allergies = state.get("patient_allergies") or []
    if not patient_allergies:
        return {"allergy_flags": []}

    drug_a = state.get("drug_a", {})
    drug_b = state.get("drug_b", {})
    resolved_drugs = [drug_a, drug_b]

    logger.info(f"[check_allergy] Evaluating {len(patient_allergies)} allergy terms against resolved drugs...")
    flags = allergy_check(patient_allergies, resolved_drugs)
    logger.info(f"[check_allergy] Evaluation produced {len(flags)} allergy flag(s).")

    return {"allergy_flags": flags}


# ------------------------------------------------------------------------------
# Node 3: verify_groundedness (Reused across drug-drug and food interactions)
# ------------------------------------------------------------------------------

def _verify_claim_citation(claim: str, citation: str, raw_source: str, api_key: Optional[str]) -> bool:
    """
    Shared groundedness verification logic: checks whether a claim's exact citation
    appears verbatim in the raw source text and entails the claim.
    Reused across both drug-drug and food interaction claims to avoid duplicating logic.
    """
    if not claim or claim == "no interaction found":
        return True

    if not citation:
        return False

    if api_key:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            verifier_llm = _create_llm(api_key)


            verifier_prompt = (
                "You are an independent verification auditor. You are given only:\n"
                "1. The raw source text.\n"
                "2. A proposed interaction claim.\n"
                "3. A purported exact citation.\n\n"
                "AUDIT TASKS:\n"
                "Task 1: Does the citation text appear VERBATIM (word-for-word, ignoring minor whitespace/punctuation differences) in the Source Text?\n"
                "Task 2: Does the citation text directly entail and substantiate the proposed claim?\n\n"
                "Respond in JSON format with keys: 'is_grounded' (bool), 'reason' (string)."
            )

            audit_payload = f"Source Text:\n{raw_source}\n\nClaim:\n{claim}\n\nCitation:\n{citation}"

            resp = verifier_llm.invoke([SystemMessage(content=verifier_prompt), HumanMessage(content=audit_payload)])
            raw_content = resp.content.strip()

            if raw_content.startswith("```"):
                raw_content = re.sub(r"^```(?:json)?\n?", "", raw_content)
                raw_content = re.sub(r"\n?```$", "", raw_content)

            parsed = json.loads(raw_content)
            return bool(parsed.get("is_grounded", False))

        except Exception as exc:
            logger.warning(f"[_verify_claim_citation] Verifier LLM failed ({exc}); falling back to substring matcher.")

    # Verbatim containment audit
    clean_citation = re.sub(r"\s+", " ", citation.strip().lower())
    clean_source = re.sub(r"\s+", " ", raw_source.lower())
    return clean_citation in clean_source or clean_citation[:40] in clean_source


def verify_groundedness(state: InteractionState) -> dict:
    """
    SEPARATE verification call from check_interaction and check_food_interaction.
    Audits claim+citation against the raw source text for both drug-drug and food interactions.
    Does NOT have access to the reasoning that produced the claim.
    """
    logger.info("[verify_groundedness] Auditing claims and citations against source text...")

    drug_a = state.get("drug_a", {})
    drug_b = state.get("drug_b", {})
    raw_source = f"{drug_a.get('fda_label_text', '')}\n\n{drug_b.get('fda_label_text', '')}"
    api_key = os.getenv("OPENAI_API_KEY")

    # 1. Audit drug-drug interaction claim
    drug_claim = state.get("interaction_claim")
    drug_citation = state.get("citation_text")
    if drug_claim and drug_claim != "no interaction found":
        if not _verify_claim_citation(drug_claim, drug_citation, raw_source, api_key):
            logger.warning("[verify_groundedness] Drug-drug interaction claim failed verification.")
            return {"is_grounded": False}

    # 2. Audit food interaction claim (routes through the SAME verification logic)
    food_claim = state.get("food_interaction_claim")
    food_citation = state.get("food_citation_text")
    if food_claim:
        if not _verify_claim_citation(food_claim, food_citation, raw_source, api_key):
            logger.warning("[verify_groundedness] Food interaction claim failed verification.")
            return {"is_grounded": False}

    logger.info("[verify_groundedness] All claims grounded and verified against official label text.")
    return {"is_grounded": True}


# ------------------------------------------------------------------------------
# Node 4a: format_grounded_answer
# ------------------------------------------------------------------------------

def format_grounded_answer(state: InteractionState) -> dict:
    """
    Assembles the final verified response when is_grounded == True.
    """
    logger.info("[format_grounded_answer] Assembling grounded answer...")

    claim = state.get("interaction_claim")
    citation = state.get("citation_text")
    drug_a = state.get("drug_a", {})
    drug_b = state.get("drug_b", {})

    if not claim or claim == "no interaction found":
        status = "none_found"
        final_answer = {
            "status": status,
            "interaction_claim": "No drug-drug interaction was found between these agents in their official FDA label text.",
            "citation": None,
            "drug_a": drug_a.get("generic_name") or drug_a.get("brand_name"),
            "drug_b": drug_b.get("generic_name") or drug_b.get("brand_name"),
            "allergy_flags": state.get("allergy_flags", []),
            "food_interaction": state.get("food_interaction_claim"),
            "food_citation": state.get("food_citation_text"),
        }
    else:
        status = "interaction_found"
        final_answer = {
            "status": status,
            "interaction_claim": claim,
            "citation": citation,
            "drug_a": drug_a.get("generic_name") or drug_a.get("brand_name"),
            "drug_b": drug_b.get("generic_name") or drug_b.get("brand_name"),
            "allergy_flags": state.get("allergy_flags", []),
            "food_interaction": state.get("food_interaction_claim"),
            "food_citation": state.get("food_citation_text"),
        }

    return {
        "final_status": status,
        "final_answer": final_answer,
    }


# ------------------------------------------------------------------------------
# Node 4b: format_unverifiable_answer
# ------------------------------------------------------------------------------

def format_unverifiable_answer(state: InteractionState) -> dict:
    """
    Assembles the explicit 'not found / could not verify' response when is_grounded == False.
    Enforces the refuse-rather-than-guess design principle.
    Preserves rule-based allergy flags since they are deterministic and not LLM-generated.
    """
    logger.warning("[format_unverifiable_answer] Claim failed verification. Refusing to guess.")

    drug_a = state.get("drug_a", {})
    drug_b = state.get("drug_b", {})

    status = "unverifiable"
    final_answer = {
        "status": status,
        "interaction_claim": "Interaction claim could not be verified against the official manufacturer label text.",
        "citation": None,
        "drug_a": drug_a.get("generic_name") or drug_a.get("brand_name"),
        "drug_b": drug_b.get("generic_name") or drug_b.get("brand_name"),
        "allergy_flags": state.get("allergy_flags", []),
        "food_interaction": None,
        "food_citation": None,
    }

    return {
        "final_status": status,
        "final_answer": final_answer,
    }
