import re


class BudgetManager:
    """
    Dynamically allocates max_token budgets based on task category,
    prompt complexity (length, multi-part questions), and historical usage.
    """

    # Base budgets per category (minimum reasonable for each type)
    BASE_BUDGETS = {
        "math": 150,
        "code_gen": 350,
        "code_debug": 300,
        "ner": 150,
        "summarize": 200,
        "sentiment": 30,
        "logic": 250,
        "factual": 120,
    }

    # Complexity weight multipliers per category
    COMPLEXITY_WEIGHTS = {
        "math": 1.5,       # multi-step word problems need more
        "code_gen": 1.8,    # complex specs need more output
        "code_debug": 1.4,
        "ner": 1.3,
        "summarize": 1.2,
        "sentiment": 1.0,   # sentiment is always short
        "logic": 1.6,
        "factual": 1.2,
    }

    def __init__(self):
        self.usage_history = {cat: [] for cat in self.BASE_BUDGETS}

    def _estimate_complexity(self, prompt: str) -> float:
        """
        Scores the prompt complexity on a 1.0-2.0 scale based on:
        - Word count (longer prompts = more complex answers)
        - Number of questions (multi-part)
        - Presence of code blocks, lists, or structured content
        """
        words = prompt.split()
        word_count = len(words)

        # Length factor: 1.0 for short (<30 words), scales up to 1.5 for long (>150 words)
        length_factor = min(1.0 + (word_count - 30) / 240, 1.5) if word_count > 30 else 1.0

        # Multi-part factor: each question mark adds complexity
        question_count = prompt.count("?")
        multi_part_factor = 1.0 + min(question_count - 1, 3) * 0.15 if question_count > 1 else 1.0

        # Code presence factor: if the prompt contains code, the answer likely needs more tokens
        code_factor = 1.3 if "```" in prompt or "def " in prompt or "function" in prompt.lower() else 1.0

        # Keywords that signal complex multi-step problems
        complex_keywords = ["step by step", "explain", "compare", "contrast", "list all",
                            "describe", "analyze", "evaluate", "multiple"]
        keyword_factor = 1.2 if any(kw in prompt.lower() for kw in complex_keywords) else 1.0

        return length_factor * multi_part_factor * code_factor * keyword_factor

    def get_budget(self, category: str, prompt: str = "") -> int:
        """
        Returns a dynamically calculated max_tokens budget based on
        the category AND the specific prompt's complexity.
        """
        base = self.BASE_BUDGETS.get(category, 200)

        if not prompt:
            return base

        complexity = self._estimate_complexity(prompt)
        weight = self.COMPLEXITY_WEIGHTS.get(category, 1.2)

        # Dynamic budget = base * complexity * category weight
        dynamic_budget = int(base * complexity * weight)

        # Apply historical adaptation if we have enough samples
        history = self.usage_history.get(category, [])
        if len(history) >= 3:
            avg_used = sum(history) / len(history)
            # If we consistently use far less than budget, tighten it
            if avg_used < dynamic_budget * 0.3:
                dynamic_budget = max(int(avg_used * 2.0), base)

        # Hard caps to prevent runaway generation
        max_cap = 600
        min_floor = 20 if category == "sentiment" else 80

        return max(min_floor, min(dynamic_budget, max_cap))

    def record_usage(self, category: str, tokens_used: int):
        """Records actual token usage for adaptive budget tightening."""
        if category in self.usage_history:
            self.usage_history[category].append(tokens_used)
