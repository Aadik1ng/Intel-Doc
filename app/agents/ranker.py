import litellm
import json
from app.config import get_settings

settings = get_settings()

RANKER_PROMPT = """You are an expert document reranker.
Score each provided context chunk for its likelihood of containing the answer to the question.

SCORING:
10: Contains the literal answer.
8: Highly relevant, matching specific entity roles (e.g., correct address type).
5: Partially relevant.
0: Irrelevant noise.

Return JSON: {"scores": [list of integers 0-10 in the same order as chunks]}"""

def rank_chunks(question: str, chunks: list[dict], top_k: int = 3) -> list[dict]:
    if not chunks:
        return []
    
    # Process as a single batch for 4x speedup
    context_to_rank = "\n---\n".join([f"CHUNK {i}:\n{c['text']}" for i, c in enumerate(chunks[:10])])
    
    try:
        response = litellm.completion(
            model=settings.LITELLM_MODEL,
            messages=[
                {"role": "system", "content": RANKER_PROMPT},
                {"role": "user", "content": f"Question: {question}\n\nContext to rank:\n{context_to_rank}"}
            ],
            api_key=settings.OPENAI_API_KEY,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        scores = data.get("scores", [])
        
        scored_chunks = []
        for i, chunk in enumerate(chunks[:10]):
            score = scores[i] if i < len(scores) else 0
            scored_chunks.append((score, chunk))
            
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        return [c[1] for c in scored_chunks[:top_k] if c[0] > 0] or chunks[:1]
        
    except Exception as e:
        print(f"Ranking error: {e}")
        return chunks[:top_k]
