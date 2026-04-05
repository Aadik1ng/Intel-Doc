import litellm
import json
from pydantic import BaseModel
from typing import Optional
from app.config import get_settings

settings = get_settings()

SIMILARITY_THRESHOLD = 0.15
AGREEMENT_THRESHOLD = 0.50

VALIDATOR_PROMPT = """You are a strict retrieval validation agent.
Your job is to determine if the retrieved context text explicitly contains the specific answer to the user's question.

CRITICAL RULES:
1. Do NOT rely on outside knowledge.
2. If the EXACT factual answer (e.g., a specific phone number or name) is NOT literally visible in the text, you MUST return `is_relevant: false`.
3. Do not assume or hallucinate standard filler information.
4. If the context explicitly states that the requested information is "N/A", "None", or blank, you MUST consider the context RELEVANT (is_relevant: true) and give a high relevance_score, because it successfully answers that the info is missing.

Return JSON with:
- is_relevant: true/false
- relevance_score: 0.0-1.0 (how explicitly the context answers the question)
- failure_reason: null or short explanation"""


class ValidationResult(BaseModel):
    is_relevant: bool
    confidence: float
    context_relevance: float
    answer_relevance: float
    failure_reason: Optional[str] = None


def validate_retrieval(question: str, chunks: list[dict]) -> ValidationResult:
    if not chunks:
        return ValidationResult(
            is_relevant=False,
            confidence=0.0,
            failure_reason="No chunks retrieved"
        )

    # Guard 1: similarity threshold
    best_similarity = max(c["similarity"] for c in chunks)
    if best_similarity < SIMILARITY_THRESHOLD:
        return ValidationResult(
            is_relevant=False,
            confidence=best_similarity,
            failure_reason=f"Best similarity {best_similarity:.2f} below threshold {SIMILARITY_THRESHOLD}"
        )

    avg_similarity = sum(c["similarity"] for c in chunks) / len(chunks)

    # BATCH JUDGE: Context & Answer Relevance
    context_preview = "\n---\n".join(c["text"] for c in chunks[:5])
    try:
        val_resp = litellm.completion(
            model=settings.LITELLM_MODEL,
            messages=[
                {"role": "system", "content": """You are a retrieval judge.
1. CONTEXT_SCORE: Is the context likely to contain the facts needed to answer the user question? (0-1)
2. RELEVANCE_SCORE: How well does the provided context address the user's specific query intent? (0-1)
Return JSON: {"context_score": float, "relevance_score": float, "reasoning": str}"""},
                {"role": "user", "content": f"Question: {question}\n\nContext:\n{context_preview}"}
            ],
            api_key=settings.OPENAI_API_KEY,
            response_format={"type": "json_object"},
        )
        val_data = json.loads(val_resp.choices[0].message.content)
        context_relevance = float(val_data.get("context_score", 0.5))
        relevance = float(val_data.get("relevance_score", 0.5))
        reasoning = val_data.get("reasoning", "")
    except:
        context_relevance, relevance, reasoning = 0.5, 0.5, "Judge failed"

    # Guard: Overall is_relevant
    is_relevant = context_relevance > 0.4 and relevance > 0.4

    # Composite confidence
    confidence = round(0.5 * context_relevance + 0.5 * relevance, 3)

    return ValidationResult(
        is_relevant=is_relevant,
        confidence=confidence,
        context_relevance=context_relevance,
        answer_relevance=relevance,
        failure_reason=reasoning if not is_relevant else None,
    )
