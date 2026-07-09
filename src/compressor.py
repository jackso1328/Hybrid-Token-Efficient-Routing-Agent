import re

try:
    from llmlingua import PromptCompressor
except ImportError:
    print("WARNING: llmlingua is not installed. Prompt compression will use basic fallback.")
    PromptCompressor = None

class LLMPromptCompressor:
    """
    Compresses long prompts locally before sending them to the API
    to drastically reduce input token costs.
    Uses LLMLingua-2 if available, otherwise a simple regex fallback.
    """
    def __init__(self, model_name: str = "microsoft/llmlingua-2-xlm-roberta-large-meetingbank"):
        self.compressor = None
        if PromptCompressor is not None:
            print("Loading LLMLingua-2 for local prompt compression...")
            try:
                # We use CPU by default to ensure it runs anywhere
                self.compressor = PromptCompressor(
                    model_name=model_name,
                    device_map="cpu"
                )
                print("Compressor loaded.")
            except Exception as e:
                print(f"Failed to load compressor: {e}")

    def compress(self, prompt: str, target_ratio: float = 0.5) -> str:
        """
        Compresses the prompt while preserving critical entities and instructions.
        Bypasses compression for very short prompts.
        """
        if len(prompt.split()) < 50:
            return prompt # Don't bother compressing tiny prompts
            
        if not self.compressor:
            return self._fallback_compress(prompt)
            
        try:
            results = self.compressor.compress_prompt(
                prompt,
                instruction="Answer the question.",
                question="",
                target_token=int(len(prompt.split()) * target_ratio),
                rank_method="llmlingua",
                use_sentence_level_filter=False,
                use_context_level_filter=False,
            )
            compressed_text = results["compressed_prompt"]
            
            # Safety: Ensure we didn't compress it to absolutely nothing
            if len(compressed_text.split()) < 10 and len(prompt.split()) > 20:
                return prompt
                
            return compressed_text
        except Exception as e:
            print(f"Compression failed, using fallback: {e}")
            return self._fallback_compress(prompt)
            
    def _fallback_compress(self, prompt: str) -> str:
        """
        A lightweight regex-based fallback if LLMLingua fails or isn't installed.
        Removes extra whitespace and common filler phrases.
        """
        # Don't mess with code blocks
        if "```" in prompt:
            return prompt
            
        text = re.sub(r'\s+', ' ', prompt)
        fillers = ["please ", "could you ", "would you mind ", "i want you to "]
        for f in fillers:
            text = re.sub(f, "", text, flags=re.IGNORECASE)
            
        return text.strip()

if __name__ == "__main__":
    # Test
    compressor = LLMPromptCompressor()
    long_text = "The Industrial Revolution, now also known as the First Industrial Revolution, was the transition to new manufacturing processes in Europe and the United States, in the period from about 1760 to sometime between 1820 and 1840."
    print("Original:", long_text)
    print("Compressed:", compressor.compress(long_text, 0.4))
