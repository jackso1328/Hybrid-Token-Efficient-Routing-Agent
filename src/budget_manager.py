class BudgetManager:
    """
    Dynamically tracks and adjusts the max_token budget per task category.
    Prevents the LLM from entering infinite generation loops.
    """
    def __init__(self):
        # Base budgets (initial conservative estimates per category)
        self.category_budgets = {
            "math": 150,
            "code_gen": 300,
            "code_debug": 250,
            "ner": 100,
            "summarize": 150,
            "sentiment": 10,
            "logic": 250,
            "factual": 100
        }
        # Track historical usage to adapt dynamically
        self.usage_history = {cat: [] for cat in self.category_budgets}

    def get_budget(self, category: str) -> int:
        """Returns the current max_tokens budget for a category."""
        return self.category_budgets.get(category, 200)

    def record_usage(self, category: str, tokens_used: int):
        """
        Records the token usage and updates the budget if needed.
        If a category consistently uses very few tokens, we tighten the budget to save tokens.
        """
        if category not in self.usage_history:
            return
            
        self.usage_history[category].append(tokens_used)
        
        # Once we have enough samples, we can dynamically adjust the budget
        history = self.usage_history[category]
        if len(history) >= 5:
            # Set new budget to the max observed usage + 20% safety margin
            # But never exceed the original baseline by too much
            max_observed = max(history)
            new_budget = int(max_observed * 1.2)
            
            # Floor to prevent extreme budget cuts
            min_floor = 10 if category == "sentiment" else 50
            
            self.category_budgets[category] = max(min_floor, new_budget)
