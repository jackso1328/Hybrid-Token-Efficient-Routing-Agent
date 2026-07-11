FROM python:3.11-slim AS base

# Install build dependencies for llama-cpp-python
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the spacy model during build
RUN pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1.tar.gz

# Pre-download the LLMLingua-2 Hugging Face model so it doesn't freeze at runtime!
RUN python -c "from transformers import AutoTokenizer, AutoModelForTokenClassification; model_name='microsoft/llmlingua-2-xlm-roberta-large-meetingbank'; AutoTokenizer.from_pretrained(model_name); AutoModelForTokenClassification.from_pretrained(model_name)"

# Copy the Gemma model (3.4 GB - separate layer for caching)
COPY gemma-4-E2B-it-Q4_K_M.gguf .

# Copy the ReasonLite math model (484 MB - separate layer for caching)
COPY ReasonLite-0.6B.Q4_K_M.gguf .

# Copy the rest of the application
COPY . .

# Ensure absolute input/output directories exist for the hackathon harness
RUN mkdir -p /input /output

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV IN_DOCKER=1

CMD ["python", "src/main.py"]
