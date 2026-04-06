import litellm
import json
import time
import logging
from app.config import get_settings
from app.models.document import AskResponse

settings = get_settings()
logger = logging.getLogger(__name__)

MEGA_PROMPT = """You are an expert logistics document analyzer optimizing for extreme speed and precision.
You are given a user query and a set of retrieved text chunks from the document.
Your task is to:
1. Identify the most relevant chunks that directly answer the query.
2. Formulate a concise, accurate answer based ONLY on the provided chunks.
3. Assess your confidence that the answer is completely supported by the text (Grounding Score).

If the chunks do not contain the answer, set answer to "Couldn't find that in the document." and confidence to 0.0.

Return EXACTLY this JSON structure:
{
    "selected_chunks": [list of integers representing the CHUNK IDs you used],
    "answer": "Your concise answer",
    "grounding_confidence": 0.95
}"""

def run_mega_node(query: str, chunks: list[dict], doc_id: str, query_id: str = None) -> dict:
    """Single pass LLM call to rank, answer, and validate."""
    start = time.time()
    
    if not chunks:
        return {
            "answer": "Couldn't find that in the document.",
            "source_texts": [],
            "confidence": 0.0,
            "warning": "No relevant context found.",
            "failure_mode": "not_found",
            "generation_latency": 0.0,
            "query_id": query_id
        }

    formatted_chunks = "\n---\n".join([f"CHUNK ID: {i}\nContent: {c.get('text', '')}" for i, c in enumerate(chunks)])
    
    try:
        response = litellm.completion(
            model=settings.LITELLM_MODEL,
            messages=[
                {"role": "system", "content": MEGA_PROMPT},
                {"role": "user", "content": f"Query: {query}\n\nContext Chunks:\n{formatted_chunks}"}
            ],
            api_key=settings.OPENAI_API_KEY,
            response_format={"type": "json_object"},
        )
        
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        # gpt-4o-mini rates
        cost = (tokens_in * 0.15 + tokens_out * 0.60) / 1_000_000
        
        result_json = json.loads(response.choices[0].message.content)
        
        ans = result_json.get("answer", "Not specified in the document.")
        conf = float(result_json.get("grounding_confidence", 0.0))
        selected_ids = result_json.get("selected_chunks", [])
        
        source_texts = [chunks[i].get("text", "") for i in selected_ids if isinstance(i, int) and i < len(chunks)]
        if not source_texts: # Fallback if LLM doesn't list IDs correctly
            source_texts = [chunks[0].get("text", "")]
            
        failure_mode = "none"
        if "not specified" in ans.lower():
            failure_mode = "not_found"
            conf = 0.0
        
        latency = round(time.time() - start, 2)
        
        return {
            "answer": ans,
            "source_texts": source_texts,
            "confidence": conf,
            "model_confidence": conf,
            "faithfulness_score": conf,
            "failure_mode": failure_mode,
            "generation_latency": latency,
            "token_input": tokens_in,
            "token_output": tokens_out,
            "cost": cost,
            "query_id": query_id
        }
        
    except Exception as e:
        logger.error(f"Mega Node Error: {e}")
        return {
            "answer": "System encountered an error processing the answer.",
            "source_texts": [],
            "confidence": 0.0,
            "failure_mode": "error",
            "generation_latency": round(time.time() - start, 2),
            "query_id": query_id
        }
