import os
import logging
import litellm
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.services.graph import setup_indexes
from app.routes import upload, ask, extract

# Set up detailed logging directory and file
os.makedirs("logs", exist_ok=True)

# File handler for all deep logs
file_handler = logging.FileHandler("logs/agentic_rag.log")
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'))

# Configure root logger to purely dump to file
logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler]
)

# Force LiteLLM to output raw API requests/responses, but intercept so it doesn't hit stdout
litellm.set_verbose = True
litellm_logger = logging.getLogger("LiteLLM")
litellm_logger.propagate = False
litellm_logger.handlers = [file_handler]

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create Memgraph indexes
    try:
        setup_indexes()
        print("✅ Memgraph indexes ready")
    except Exception as e:
        print(f"⚠️  Could not set up Memgraph indexes: {e}")
        
    print("🔥 Pre-warming LLM and Embeddings...")
    try:
        from app.services.embedder import embed_query
        from app.config import get_settings
        settings = get_settings()
        
        embed_query("warmup")
        litellm.completion(
            model=settings.LITELLM_MODEL,
            messages=[{"role": "user", "content": "hi"}],
            api_key=settings.OPENAI_API_KEY,
            max_tokens=1
        )
        
        # STT Warmup
        print("🎙️ Warmup STT...")
        from livekit.plugins import openai
        stt = openai.STT()
        # Just creating the object and a dummy call if possible, 
        # but usually object creation is the bottleneck for first-run plugins.
        
        print("✅ Pre-warming complete")
    except Exception as e:
        print(f"⚠️  Pre-warming failed: {e}")
        
    yield

app = FastAPI(
    title="Ultra Doc-Intelligence",
    description="Agentic GraphRAG for logistics documents using Memgraph, LlamaIndex, LangChain & LiteLLM",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, tags=["Documents"])
app.include_router(ask.router, tags=["Q&A"])
app.include_router(extract.router, tags=["Extraction"])

@app.get("/health")
def health():
    return {"status": "ok", "service": "Ultra Doc-Intelligence"}
