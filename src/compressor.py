import re
import torch
import numpy as np

_compressor_model = None
_compressor_tokenizer = None

def _load_llmlingua_model():
    """Load the LLMLingua-2 model directly via transformers to avoid the llmlingua bug."""
    global _compressor_model, _compressor_tokenizer
    if _compressor_model is not None:
        return True

    try:
        from transformers import AutoTokenizer, AutoModelForTokenClassification
        model_name = "microsoft/llmlingua-2-xlm-roberta-large-meetingbank"
        print("Loading LLMLingua-2 model for local prompt compression...")
        _compressor_tokenizer = AutoTokenizer.from_pretrained(model_name)
        _compressor_model = AutoModelForTokenClassification.from_pretrained(model_name)
        _compressor_model.eval()
        print("Compressor loaded successfully.")
        return True
    except Exception as e:
        print(f"Failed to load compressor model: {e}")
        return False


class LLMPromptCompressor:
    """
    Compresses long prompts locally before sending them to the API
    to drastically reduce input token costs.

    Uses the LLMLingua-2 XLM-RoBERTa model directly (bypassing the buggy
    llmlingua library) to score each token's importance and drop low-value ones.
    Falls back to a regex-based compressor if the model is unavailable.
    """

    def __init__(self):
        self.model_loaded = _load_llmlingua_model()

    def compress(self, prompt: str, target_ratio: float = 0.5) -> str:
        """
        Compresses the prompt while preserving critical entities and instructions.
        Bypasses compression for very short prompts.
        """
        orig_words = len(prompt.split())

        if orig_words < 50:
            print(f"  [Compression] Skipped (prompt is only {orig_words} words, threshold is 50).")
            return prompt

        if not self.model_loaded:
            return self._fallback_compress(prompt)

        try:
            return self._llmlingua_compress(prompt, target_ratio)
        except Exception as e:
            print(f"  [Compression] Model compress failed ({e}), using regex fallback.")
            return self._fallback_compress(prompt)

    def _llmlingua_compress(self, prompt: str, target_ratio: float) -> str:
        """
        Direct token-importance scoring using the LLMLingua-2 model.
        Each token gets a keep/drop probability from the classifier.
        We keep the top-scoring tokens until we hit the target ratio.
        """
        global _compressor_model, _compressor_tokenizer

        # Tokenize
        inputs = _compressor_tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            return_offsets_mapping=True
        )
        offset_mapping = inputs.pop("offset_mapping")[0]

        # Run model (no past_key_values — that's the bug we're avoiding)
        with torch.no_grad():
            outputs = _compressor_model(**inputs)

        # logits shape: [1, seq_len, 2] — class 0 = drop, class 1 = keep
        logits = outputs.logits[0]
        probs = torch.softmax(logits, dim=-1)
        keep_probs = probs[:, 1].cpu().numpy()

        # Build word-level importance scores by averaging token scores
        words = prompt.split()
        char_pos = 0
        word_scores = []
        token_idx = 0

        for word in words:
            word_start = prompt.index(word, char_pos)
            word_end = word_start + len(word)
            char_pos = word_end

            # Find all tokens that overlap with this word
            scores = []
            for ti in range(len(offset_mapping)):
                t_start, t_end = offset_mapping[ti].tolist()
                if t_start >= word_end:
                    break
                if t_end > word_start and t_start < word_end:
                    scores.append(keep_probs[ti])

            avg_score = np.mean(scores) if scores else 0.5
            word_scores.append((word, avg_score))

        # Keep the top-N words by importance to hit target ratio
        target_count = max(int(len(words) * target_ratio), 10)
        
        # Sort by importance, keep top ones, then re-sort by original position
        indexed_scores = [(i, w, s) for i, (w, s) in enumerate(word_scores)]
        indexed_scores.sort(key=lambda x: x[2], reverse=True)
        kept = sorted(indexed_scores[:target_count], key=lambda x: x[0])
        
        compressed = " ".join(w for _, w, _ in kept)

        # Safety check
        comp_words = len(compressed.split())
        if comp_words < 10 and len(words) > 20:
            print(f"  [Compression] Over-compressed ({comp_words} words left). Using original.")
            return prompt

        saved = len(words) - comp_words
        print(f"  [Compression] LLMLingua-2: {len(words)} -> {comp_words} words (saved {saved} words, {saved*100//len(words)}% reduction).")
        return compressed

    def _fallback_compress(self, prompt: str) -> str:
        """
        A lightweight regex-based fallback if the model is unavailable.
        Removes extra whitespace and common filler phrases.
        """
        orig_words = len(prompt.split())

        if "```" in prompt:
            print(f"  [Compression] Skipped fallback (prompt contains code blocks).")
            return prompt

        text = re.sub(r'\s+', ' ', prompt)
        fillers = ["please ", "could you ", "would you mind ", "i want you to "]
        for f in fillers:
            text = re.sub(f, "", text, flags=re.IGNORECASE)

        comp_words = len(text.split())
        saved = orig_words - comp_words
        if saved > 0:
            print(f"  [Compression] Regex fallback: {orig_words} → {comp_words} words (saved {saved} words).")
        else:
            print(f"  [Compression] Regex fallback: no reduction possible ({orig_words} words).")

        return text.strip()

    def free_memory(self):
        """Explicitly release the PyTorch model from RAM so Phase 2 can use the memory."""
        global _compressor_model, _compressor_tokenizer
        _compressor_model = None
        _compressor_tokenizer = None


if __name__ == "__main__":
    compressor = LLMPromptCompressor()
    long_text = "The Industrial Revolution, now also known as the First Industrial Revolution, was the transition to new manufacturing processes in Europe and the United States, in the period from about 1760 to sometime between 1820 and 1840. This transition included going from hand production methods to machines, new chemical manufacturing and iron production processes, the increasing use of steam power and water power, the development of machine tools and the rise of the mechanized factory system. The Industrial Revolution also led to an unprecedented rise in the rate of population growth."
    print("\nOriginal:", long_text)
    compressed = compressor.compress(long_text, 0.4)
    print("Compressed:", compressed)
