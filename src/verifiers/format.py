import re
from typing import Tuple, Optional, Dict

def extract_length_constraint(prompt: str) -> Optional[Dict]:
    """Parse length constraints from the prompt text."""
    # Matches "in 2 sentences", "in exactly one sentence"
    m = re.search(r'in (\w+|\d+) sentences?', prompt, re.IGNORECASE)
    if m:
        word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
        count = word_to_num.get(m.group(1).lower(), None)
        if count is None:
            try:
                count = int(m.group(1))
            except ValueError:
                return None
        return {"type": "sentences", "count": count}
        
    # Matches "under 50 words", "in 100 words"
    m = re.search(r'(?:in|under|within|max(?:imum)?)\s+(\d+)\s+words?', prompt, re.IGNORECASE)
    if m:
        return {"type": "words", "max": int(m.group(1))}
        
    return None

def verify_summary(prompt: str, gemma_answer: str, local_engine=None) -> Tuple[bool, Optional[str]]:
    """Verify summary meets format/length constraints."""
    constraints = extract_length_constraint(prompt)
    
    if not constraints:
        return True, None # No specific constraints found
        
    if constraints["type"] == "sentences":
        # Rough sentence count
        actual_sentences = len([s for s in gemma_answer.split('.') if s.strip()])
        if actual_sentences > constraints["count"] + 1:
            if local_engine and local_engine.is_loaded:
                retry_prompt = f"Shorten this to exactly {constraints['count']} sentence(s):\n{gemma_answer}"
                result = local_engine.generate(retry_prompt, max_tokens=100, temperature=0.1)
                return False, result["text"].strip()
            return False, None
            
    elif constraints["type"] == "words":
        actual_words = len(gemma_answer.split())
        if actual_words > constraints["max"] * 1.2: # 20% tolerance
            if local_engine and local_engine.is_loaded:
                retry_prompt = f"Rewrite in {constraints['max']} words or fewer:\n{gemma_answer}"
                result = local_engine.generate(retry_prompt, max_tokens=constraints["max"]*2, temperature=0.1)
                return False, result["text"].strip()
            return False, None
            
    return True, None
