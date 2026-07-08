from .local_engine import LocalGemmaEngine

class TaskClassifier:
    def __init__(self, engine: LocalGemmaEngine):
        self.engine = engine
        
    def classify(self, prompt: str) -> str:
        """
        Uses the local LLM to classify the user prompt into one of the 8 categories.
        Categories: math, code_gen, code_debug, ner, summarize, sentiment, logic, factual
        """
        system_prompt = """You are a strict classification system. Classify the following user task into exactly ONE of these categories:
- math: Mathematical calculations or word problems
- code_gen: Writing new code or functions
- code_debug: Finding bugs or fixing existing code
- ner: Extracting named entities (people, places, organizations)
- summarize: Condensing text into shorter forms (sentences, words)
- sentiment: Analyzing sentiment (positive, negative, neutral, mixed)
- logic: Logical reasoning or puzzles
- factual: General knowledge questions

Output ONLY the category name in lowercase. No other text, no preamble."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        # We only need a few tokens for classification
        result = self.engine.chat_completion(messages=messages, max_tokens=10, temperature=0.1)
        
        # Clean the output
        category = result["content"].strip().lower()
        
        # Fallback parsing
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

