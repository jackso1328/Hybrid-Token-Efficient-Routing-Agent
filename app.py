import sys
import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import spaces

@spaces.GPU
def dummy_gpu_function():
    pass

# Ensure src is in the path so we can import the router
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
from src.main import GemmaCascadeRouter

app = FastAPI(
    title="GemmaCascade API Backend",
    description="Live backend API for the Hybrid Token-Efficient Routing Agent",
    version="1.0"
)

# Initialize the router once when the server starts
print("Starting FastAPI Backend... Initializing GemmaCascadeRouter")
try:
    router = GemmaCascadeRouter()
except Exception as e:
    print(f"Failed to initialize router: {e}")
    router = None

class TaskRequest(BaseModel):
    task_id: str
    prompt: str

@app.get("/")
def health_check():
    return {"status": "healthy", "model_loaded": router.local_engine.is_loaded if router else False}

@app.post("/solve")
def solve_task(request: TaskRequest):
    if not router:
        raise HTTPException(status_code=500, detail="Router failed to initialize.")
    
    task_dict = {
        "task_id": request.task_id,
        "prompt": request.prompt
    }
    
    try:
        result = router.process_task(task_dict)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    # Hugging Face Spaces requires the app to bind to 0.0.0.0:7860
    uvicorn.run(app, host="0.0.0.0", port=7860)
