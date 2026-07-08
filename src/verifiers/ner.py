import spacy
import json
from typing import Tuple, Optional, Dict

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    print("WARNING: spaCy en_core_web_sm model not found. NER verification will skip.")
    nlp = None

def map_spacy_label(label: str) -> str:
    """Map spaCy entity labels to our categories."""
    mapping = {
        "PERSON": "persons", "ORG": "organizations",
        "GPE": "locations", "LOC": "locations",
        "DATE": "dates", "TIME": "dates",
        "FAC": "locations", "NORP": "organizations",
    }
    return mapping.get(label, "other")

def verify_ner_answer(original_text: str, gemma_answer_json: str) -> Tuple[bool, Optional[str]]:
    """Cross-check Gemma's NER output against spaCy's NER."""
    if not nlp:
        return True, None # Skip if not installed

    try:
        gemma_entities = json.loads(gemma_answer_json)
    except json.JSONDecodeError:
        return False, None # Invalid JSON
        
    doc = nlp(original_text)
    spacy_entities = {}
    for ent in doc.ents:
        category = map_spacy_label(ent.label_)
        if category == "other":
            continue
        if category not in spacy_entities:
            spacy_entities[category] = []
        spacy_entities[category].append(ent.text)
        
    # Compare
    missing = {}
    for category, spacy_ents in spacy_entities.items():
        gemma_ents = gemma_entities.get(category, [])
        gemma_ents_lower = [e.lower() for e in gemma_ents]
        
        for ent in spacy_ents:
            if ent.lower() not in gemma_ents_lower:
                if category not in missing:
                    missing[category] = []
                missing[category].append(ent)
                
    if missing:
        # Merge them
        merged = {**gemma_entities}
        for cat, ents in missing.items():
            if cat in merged:
                # Add only unique ones
                for e in ents:
                    if e not in merged[cat]:
                        merged[cat].append(e)
            else:
                merged[cat] = ents
        return False, json.dumps(merged)
        
    return True, None
