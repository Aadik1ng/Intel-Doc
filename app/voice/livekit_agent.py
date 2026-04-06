import asyncio
import time
import logging
import numpy as np
import httpx

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.agents.stt import StreamAdapter, STTStream
from livekit.plugins import openai, silero
from livekit import rtc

# Ensure we import our local embedding for fast similarity comparisons
from app.services.embedder import embed_query

logger = logging.getLogger("livekit-agent")

FASTAPI_URL = "http://localhost:8000/ask"
DOCUMENT_ID = "b6c509a9-0372-4513-9e9e-780eea5a8167" # Target doc from benchmarks

class AgentState:
    def __init__(self):
        self.latest_query_id = 0
        self.last_trigger_time = 0.0
        self.in_flight_queries = {}
        self.stability_window_ms = 250
        self.cooldown_after_trigger_ms = 400

    def get_next_query_id(self) -> str:
        self.latest_query_id += 1
        return str(self.latest_query_id)

    def is_cooling_down(self) -> bool:
        return (time.time() - self.last_trigger_time) * 1000 < self.cooldown_after_trigger_ms

    def record_trigger(self):
        self.last_trigger_time = time.time()

state = AgentState()
httpx_client = httpx.AsyncClient()

def compute_similarity(text1: str, text2: str) -> float:
    """Computes cosine similarity using NumPy (faster startup than SciPy)."""
    try:
        e1 = np.array(embed_query(text1))
        e2 = np.array(embed_query(text2))
        if e1 is None or e2 is None: return 0.0
        norm1 = np.linalg.norm(e1)
        norm2 = np.linalg.norm(e2)
        if norm1 == 0 or norm2 == 0: return 0.0
        return np.dot(e1, e2) / (norm1 * norm2)
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return 0.0

def passes_heuristic_gates(words: list[str]) -> bool:
    """3-Layer Heuristic Gating (No LLM)."""
    # 1. Length
    if len(words) < 5:
        return False
    
    # 2. Semantic Hint (Domain keywords)
    text = " ".join(words).lower()
    domain_keywords = ["consignee", "address", "shipper", "weight", "date", "rate", "invoice", "pieces", "pickup", "delivery"]
    has_noun = any(k in text for k in domain_keywords)
    wh_words = ["what", "where", "who", "when", "how"]
    has_wh = any(w in text for w in wh_words)
    
    # Needs a question word or a domain keyword to be worth searching
    if not (has_noun or has_wh):
        return False
        
    return True

async def trigger_graphrag(query: str, query_id: str, is_final: bool = False):
    """Sends the query to the FastAPI GraphRAG backend."""
    logger.info(f"🚀 Triggering /ask [id={query_id}] (Final={is_final}): '{query}'")
    try:
        response = await httpx_client.post(
            FASTAPI_URL,
            json={
                "document_id": DOCUMENT_ID,
                "question": query,
                "fast_mode": True,
                "query_id": query_id
            },
            timeout=10.0
        )
        response.raise_for_status()
        data = response.json()
        
        # VALIDATE AGAINST RACE CONDITIONS
        if str(data.get("query_id")) != str(state.latest_query_id):
            logger.warning(f"Discarding stale response [id={data.get('query_id')}] (Latest logic moved on to {state.latest_query_id})")
            return
            
        ans = data.get("answer", "")
        latency = data.get("latency_seconds", 0)
        logger.info(f"✅ Response [id={query_id}] in {latency}s: {ans}")
        # Here you would route text to TTS or DataChannel
        
    except Exception as e:
        logger.error(f"Error querying GraphRAG: {e}")

async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    
    logger.info("Connected to LiveKit room. Waiting for speech...")
    
    # Use OpenAI's Whisper adapter (fast but robust)
    stt = openai.STT()
    stt_stream = stt.stream()

    last_partial_text = ""
    last_partial_time = time.time()
    
    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication: rtc.TrackPublication, participant: rtc.RemoteParticipant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            audio_stream = rtc.AudioStream(track)
            
            async def forward_audio():
                async for frame in audio_stream:
                    stt_stream.push_frame(frame)
            
            asyncio.create_task(forward_audio())
    
    async for event in stt_stream:
        if event.type == "transcript":
            text = event.alternatives[0].text.strip()
            if not text:
                continue
                
            if not event.alternatives[0].is_final:
                # PARTIAL STREAM HANDLING
                now = time.time()
                
                # Check Layer 3: Stability (has it been 250ms since last transcript change?)
                # We simulate stability by detecting pauses in updates.
                if text != last_partial_text:
                    last_partial_text = text
                    last_partial_time = now
                    continue # Not stable yet
                
                stability_ms = (now - last_partial_time) * 1000
                if stability_ms < 250:
                    continue # Wait for stability
                    
                if state.is_cooling_down():
                    continue
                    
                words = text.split()
                if passes_heuristic_gates(words):
                    q_id = state.get_next_query_id()
                    state.record_trigger()
                    state.in_flight_queries[q_id] = text
                    asyncio.create_task(trigger_graphrag(text, q_id, is_final=False))
                    
            else:
                # FINAL STT HANDLING
                # Reconcile with latest partial
                latest_q_id = str(state.latest_query_id)
                latest_partial_text = state.in_flight_queries.get(latest_q_id, "")
                
                if latest_partial_text:
                    sim = compute_similarity(latest_partial_text, text)
                    logger.info(f"Final vs Partial similarity: {sim:.3f}")
                    if sim >= 0.85:
                        logger.info("Meaning unchanged. Skipping duplicate query.")
                        continue
                        
                # If meaning changed or no partial was triggered, trigger final.
                if passes_heuristic_gates(text.split()):
                    q_id = state.get_next_query_id()
                    state.record_trigger()
                    asyncio.create_task(trigger_graphrag(text, q_id, is_final=True))
                
                # Reset buffers for next utterance
                last_partial_text = ""

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
