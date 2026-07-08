import os

# API Configuration (Supports both Fireworks and OpenRouter)
FIREWORKS_API_KEY = os.environ.get("FIREWORKS_API_KEY")
FIREWORKS_BASE_URL = os.environ.get("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Allowed models for the hackathon (Fallback to free Gemma if empty)
_allowed_models_str = os.environ.get("ALLOWED_MODELS", "")
ALLOWED_MODELS = [m.strip() for m in _allowed_models_str.split(",")] if _allowed_models_str else ["google/gemma-2-9b-it:free"]

# Verify essential config on load
if not FIREWORKS_API_KEY and not OPENROUTER_API_KEY:
    print("WARNING: Neither FIREWORKS_API_KEY nor OPENROUTER_API_KEY environment variables are set. API fallback will fail.")

