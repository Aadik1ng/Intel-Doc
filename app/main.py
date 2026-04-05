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
