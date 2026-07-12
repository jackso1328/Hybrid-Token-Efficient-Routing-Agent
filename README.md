---
title: GemmaCascade Router
emoji: 🧠
colorFrom: blue
colorTo: indigo
sdk: gradio
app_file: app.py
pinned: false
---
# Hybrid Token-Efficient Routing Agent

Welcome to the **Hybrid Token-Efficient Routing Agent**, designed for the AMD Developer Hackathon. This project uses a sophisticated, memory-constrained 2-phase pipeline to route complex AI tasks between a lightning-fast local Gemma 2B model and powerful API models, ensuring zero Out-of-Memory (OOM) crashes while maximizing token efficiency.

## 🌟 The 2-Phase Memory Architecture

The strict 4GB RAM limit imposed by the hackathon judging container is the biggest hurdle in running local LLMs. If the system attempts to load both the prompt compressor and the local Gemma model simultaneously, the 4GB limit is immediately exceeded, resulting in a crash.

To solve this, our agent employs a **2-Phase Sequential Architecture** with aggressive Python garbage collection:

*   **Phase 1 (Prompt Compression):** The pipeline first loads the 1.5 GB `LLMLingua-2` model into memory. It reads `tasks.json`, scores token importance, and aggressively compresses long prompts (saving up to 50% of context). Once finished, the pipeline actively destroys the global PyTorch tensors and runs the Garbage Collector, forcefully returning the 1.5 GB of RAM to the Linux OS.
*   **Phase 2 (Local Engine & Routing):** With a completely flushed and clean RAM environment, the 3.4 GB `Gemma 2B` model safely loads into memory. It processes tasks using the pre-compressed prompts, dynamically classifying intent. If a task requires heavy reasoning (Math/Logic) or generates high output entropy, it seamlessly escalates the request to the external API using OpenRouter, keeping API costs strictly under budget.

## 🚀 Getting Started

### Prerequisites
*   **WSL (Ubuntu) or Native Linux**
*   **Docker** (for the final judging container)
*   **OpenRouter API Key**

### Installation (Local Development)
1. Clone the repository and enter the project directory.
2. Create and activate your virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Install the optimized dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create a `.env` file in the root directory and add your API key:
   ```env
   OPENROUTER_API_KEY=your_api_key_here
   ```

### Running the Agent
Simply run the main pipeline script:
```bash
python src/main.py
```
The script will read `input/tasks.json` and generate `output/results.json` while printing the time, cost, and routing decisions to the console.

## 🐳 Docker Deployment

The agent is fully configured to run inside a Docker container strictly capped at 2 vCPUs and 4GB RAM. 

### Build the Image
```bash
docker build -t hybrid-routing-agent .
```

### Run the Container
```bash
docker run --cpus="2.0" --memory="4g" -v $(pwd)/input:/app/input -v $(pwd)/output:/app/output hybrid-routing-agent
```
*(Note: Ensure your `.env` file is properly injected or pass the API key via `-e OPENROUTER_API_KEY=...` when running the container).*

## 📊 Expected Output

Your console will display the dynamic routing decisions in real-time. For example:
```text
[T004] Category: summarize | Dynamic Budget: 271 tokens
[T004] Verification: PASSED
[T004] Source: local
[T004] Completed in 15.56s

[T002] Category: math | Dynamic Budget: 225 tokens
[T002] Verification: FAILED -> Escalating to API
  [API] Using model: tencent/hy3:free (difficulty: hard, max_tokens: 1024)
[T002] Source: api_escalation
[T002] Completed in 70.82s
```

All final answers are formatted beautifully into `output/results.json`.

---
*Built for the AMD Developer Hackathon.*
