import re

class AnswerDistiller:
    """
    Cleans up the raw output from local Gemma models to ensure we submit
    only the absolute minimum number of tokens required.
    """
    
    @staticmethod
    def distill(raw_text: str) -> str:
        """
        Removes <think> traces, conversational preamble, and trailing filler.
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
            # We want whatever is after ####
            text = parts[-1].strip()
            
        # 4. Strip common chatty preamble
        preambles = [
            r"Here is the answer:\s*",
            r"The answer is:\s*",
            r"Based on the provided text,?\s*",
            r"Sure,? here is the.*:\s*",
            r"I can help with that\.\s*",
        ]
        for preamble in preambles:
            text = re.sub(f"^{preamble}", "", text, flags=re.IGNORECASE)
            
        # 5. Clean up Markdown artifacts if it's just a single sentence
        # (Be careful not to ruin code blocks or JSON)
        if "```" not in text and "{" not in text:
            # Only strip leading/trailing quotes if it's plain text
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
                
        return text.strip()

if __name__ == "__main__":
    # Test cases
    test_1 = "<think>\n2 + 2 is 4.\n</think>\nThe answer is: 4"
    test_2 = "Sure, here is the extracted JSON:\n```json\n{\"persons\": [\"Alice\"]}\n```"
    test_3 = "Thinking... 5 words max\n#### 42"
    
    distiller = AnswerDistiller()
    print("Test 1:", repr(distiller.distill(test_1))) # Should be "4"
    print("Test 2:", repr(distiller.distill(test_2))) # Should be "```json\n{\"persons\": [\"Alice\"]}\n```"
    print("Test 3:", repr(distiller.distill(test_3))) # Should be "42"
