from .local_engine import LocalGemmaEngine
import re

class TaskClassifier:
    def __init__(self, engine: LocalGemmaEngine):
        self.engine = engine
        
    def classify(self, prompt: str) -> str:
        """
        Uses the local LLM to classify the user prompt into one of the 8 categories.
        Categories: math, code_gen, code_debug, ner, summarize, sentiment, logic, factual
        """
        system_prompt = """You are a classification system. Classify the following task into exactly ONE of these categories:
- math: Mathematical calculations or word problems
- code_gen: Writing new code or functions
- code_debug: Finding bugs or fixing existing code
- ner: Extracting named entities (people, places, organizations)
- summarize: Condensing text into shorter forms (sentences, words)
- sentiment: Analyzing sentiment (positive, negative, neutral, mixed)
- logic: Logical reasoning or puzzles
- factual: General knowledge questions

Output ONLY the category name. No other text."""

        full_prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
        
        # We only need a few tokens for classification
        result = self.engine.generate(full_prompt, max_tokens=10, temperature=0.1)
        
        # Clean the output
        category = result["text"].strip().lower()
        
        # Fallback parsing if the model outputs something like "Category: math"
        valid_categories = ["math", "code_gen", "code_debug", "ner", "summarize", "sentiment", "logic", "factual"]
        
        for valid in valid_categories:
            if valid in category:
                return valid
                
        # Default fallback
        return "factual"

if __name__ == "__main__":
    engine = LocalGemmaEngine()
    classifier = TaskClassifier(engine)
    print(classifier.classify("What is the capital of France?"))
    print(classifier.classify("Extract the names from this text: Alice went to Paris."))
