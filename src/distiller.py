import re
import json

class AnswerDistiller:
    """
    Cleans up the raw output from local Gemma models to ensure we submit
    only the absolute minimum number of tokens required.
    """
    
    @staticmethod
    def distill(raw_text: str) -> str:
        """
        Removes <think> traces, conversational preamble, and trailing filler.
        Extracts structured data (JSON, code) if embedded in verbose responses.
        """
        if not raw_text:
            return ""
            
        # 1. Remove <think>...</think> blocks entirely (including the tags)
        text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL)
        
        # 2. Remove other common reasoning block delimiters if the model forgot <think>
        text = re.sub(r'<\|think\|>.*?<\|/think\|>', '', text, flags=re.DOTALL)
        
        # 3. Handle Chain of Draft delimiter '####'
        if "####" in text:
            parts = text.split("####")
            text = parts[-1].strip()

        # 4. Try to extract JSON if present (handles NER and structured tasks)
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                # Valid JSON found — return it directly (minimal tokens)
                return json.dumps(parsed, separators=(',', ':'))
            except json.JSONDecodeError:
                pass  # Not valid JSON, continue normal distillation

        # 5. Extract code blocks if present
        code_match = re.search(r'```(?:python|py)?\s*\n?(.*?)```', text, re.DOTALL)
        if code_match:
            code = code_match.group(1).strip()
            if code:
                return code
            
        # 6. Strip common chatty preamble
        preambles = [
            r"Here is the answer:\s*",
            r"The answer is:?\s*",
            r"Based on the provided text,?\s*",
            r"Sure,? here is the.*?:\s*",
            r"I can help with that\.\s*",
            r"Here are the .*?:\s*",
            r"The .*? (?:is|are):?\s*",
        ]
        for preamble in preambles:
            text = re.sub(f"^{preamble}", "", text, flags=re.IGNORECASE)
            
        # 7. Clean up Markdown artifacts if it's just a single sentence
        if "```" not in text and "{" not in text:
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
                
        return text.strip()

if __name__ == "__main__":
    # Test cases
    test_1 = "<think>\n2 + 2 is 4.\n</think>\nThe answer is: 4"
    test_2 = "Sure, here is the extracted JSON:\n```json\n{\"persons\": [\"Alice\"]}\n```"
    test_3 = "Thinking... 5 words max\n#### 42"
    test_4 = 'Here are the entities:\n{"persons": ["Satya Nadella"], "organizations": ["Microsoft", "OpenAI"], "locations": ["Redmond", "Washington"], "dates": ["January 15, 2024"]}'
    test_5 = "The sentiment of this text is mixed because it starts positive but ends negative. The overall sentiment is: mixed"
    
    distiller = AnswerDistiller()
    print("Test 1:", repr(distiller.distill(test_1)))  # Should be "4"
    print("Test 2:", repr(distiller.distill(test_2)))  # Should be code
    print("Test 3:", repr(distiller.distill(test_3)))  # Should be "42"
    print("Test 4:", repr(distiller.distill(test_4)))  # Should be compact JSON
    print("Test 5:", repr(distiller.distill(test_5)))  # Should preserve "mixed"
