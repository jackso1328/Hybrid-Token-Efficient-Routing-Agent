import os
import sys

# Ensure src is in the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from local_engine import LocalGemmaEngine

class TaskClassifier:
    """
    Uses the local LLM to classify user prompts into one of 8 categories.
    If the local model is offline or uncertain, uses robust keyword fallbacks.
    """
    def __init__(self, engine: LocalGemmaEngine):
        self.engine = engine
        self.valid_categories = [
            "math", "code_gen", "code_debug", "ner", "summarize", 
            "sentiment", "logic", "factual"
        ]
        
    def classify(self, prompt: str) -> str:
        """
        Classifies the prompt into exactly ONE category.
        """
        system_prompt = """You are a strict classification system. Classify the following user task into exactly ONE of these categories:
- math: Mathematical calculations, percentages, word problems
- code_gen: Writing new code or functions from scratch
- code_debug: Finding bugs, fixing code, or reviewing code
- ner: Extracting named entities (people, places, organizations)
- summarize: Condensing text into shorter forms (sentences, words)
- sentiment: Analyzing sentiment (positive, negative, neutral, mixed)
- logic: Logical reasoning, deduction, or puzzles
- factual: General knowledge questions, definitions

Output ONLY the category name in lowercase. No other text, no preamble."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        # Try local model classification first
        if self.engine.is_loaded:
            result = self.engine.chat_completion(messages=messages, max_tokens=10, temperature=0.1)
            category = result["content"].strip().lower()
            
            # Check if valid
            for valid in self.valid_categories:
                if valid in category:
                    return valid
                    
        # Robust Keyword Fallback (if local model is dead or confused)
        return self._keyword_fallback(prompt)
        
    def _keyword_fallback(self, prompt: str) -> str:
        p_lower = prompt.lower()
        
        if "sentiment" in p_lower:
            return "sentiment"
        if "summarize" in p_lower or "summary" in p_lower:
            return "summarize"
        if "extract" in p_lower and ("entity" in p_lower or "name" in p_lower or "location" in p_lower):
            return "ner"
        if "bug" in p_lower or "fix" in p_lower or "error" in p_lower:
            return "code_debug"
        if "write a python function" in p_lower or "code" in p_lower or "def " in p_lower:
            if "bug" not in p_lower and "fix" not in p_lower:
                return "code_gen"
        if "math" in p_lower or "calculate" in p_lower or "%" in p_lower or any(op in p_lower for op in ['+', '-', '*', '/']):
            # Distinguish from logic puzzles
            if "pet" not in p_lower and "who" not in p_lower:
                return "math"
        if "puzzle" in p_lower or "logic" in p_lower or ("if" in p_lower and "then" in p_lower):
            return "logic"
            
        return "factual"

if __name__ == "__main__":
    engine = LocalGemmaEngine(model_path="dummy")
    classifier = TaskClassifier(engine)
    print("Test 1:", classifier.classify("What is the capital of France?"))
    print("Test 2:", classifier.classify("Extract the names from this text: Alice went to Paris."))
