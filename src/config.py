import os
import sys

try:
    from dotenv import load_dotenv
    # Load .env from the project root, not from cwd
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _dotenv_path = os.path.join(_project_root, ".env")
    if os.path.exists(_dotenv_path):
        load_dotenv(_dotenv_path)
    else:
        # Also try .env.example as fallback
        _dotenv_example = os.path.join(_project_root, ".env.example")
        if os.path.exists(_dotenv_example):
            load_dotenv(_dotenv_example)
except ImportError:
    pass

# ──────────────────────────────────────────────
# Project Paths
# ──────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The local Gemma 4 E4B model — check both possible locations
_model_name = "gemma-4-E4B-it-Q4_K_M.gguf"
_model_in_root = os.path.join(PROJECT_ROOT, _model_name)
_model_in_models = os.path.join(PROJECT_ROOT, "models", _model_name.lower().replace("-", "_"))

if os.path.exists(_model_in_root):
    LOCAL_MODEL_PATH = _model_in_root
elif os.path.exists(_model_in_models):
    LOCAL_MODEL_PATH = _model_in_models
else:
    # Try a glob to find any .gguf file
    import glob
    gguf_files = glob.glob(os.path.join(PROJECT_ROOT, "*.gguf"))
    if not gguf_files:
        gguf_files = glob.glob(os.path.join(PROJECT_ROOT, "models", "*.gguf"))
    LOCAL_MODEL_PATH = gguf_files[0] if gguf_files else os.path.join(PROJECT_ROOT, _model_name)

INPUT_PATH = os.path.join(PROJECT_ROOT, "input", "tasks.json")
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "output", "results.json")

# ──────────────────────────────────────────────
# API Configuration (Supports Fireworks + OpenRouter)
# ──────────────────────────────────────────────
FIREWORKS_API_KEY = os.environ.get("FIREWORKS_API_KEY")
FIREWORKS_BASE_URL = os.environ.get("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Allowed models for the hackathon
_allowed_models_str = os.environ.get("ALLOWED_MODELS", "")
if _allowed_models_str:
    ALLOWED_MODELS = [m.strip() for m in _allowed_models_str.split(",") if m.strip()]
else:
    ALLOWED_MODELS = ["tencent/hy3:free"]

# Verify essential config on load
if not FIREWORKS_API_KEY and not OPENROUTER_API_KEY:
    print("WARNING: Neither FIREWORKS_API_KEY nor OPENROUTER_API_KEY is set. API fallback will fail.")
else:
    _active = "Fireworks" if FIREWORKS_API_KEY else "OpenRouter"
    print(f"Config loaded: API provider = {_active}, Model path = {LOCAL_MODEL_PATH}")
