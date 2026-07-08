import os

# Fireworks AI Configuration
FIREWORKS_API_KEY = os.environ.get("FIREWORKS_API_KEY")
FIREWORKS_BASE_URL = os.environ.get("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")

# Allowed models for the hackathon
_allowed_models_str = os.environ.get("ALLOWED_MODELS", "")
ALLOWED_MODELS = [m.strip() for m in _allowed_models_str.split(",")] if _allowed_models_str else []

# Verify essential config on load
if not FIREWORKS_API_KEY:
    print("WARNING: FIREWORKS_API_KEY environment variable is not set.")

if not ALLOWED_MODELS:
    print("WARNING: ALLOWED_MODELS environment variable is not set or empty.")
