FROM python:3.11-slim AS base

# Install build dependencies for llama-cpp-python
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the spacy model during build
RUN python -m spacy download en_core_web_sm

# Copy the rest of the application
COPY . .

# Set environment variables for non-interactive output
ENV PYTHONUNBUFFERED=1

CMD ["python", "src/main.py"]
