import litellm
import json
from pydantic import BaseModel
from typing import Optional
from app.config import get_settings

settings = get_settings()

ANSWERER_PROMPT = """You are a strictly bound logistics document Q&A assistant.
Your job is to extract answers EXACTLY as they appear in the provided source context.
1. Do NOT format, standardize, or invent information under any circumstances.
2. Never inject template filler data (like "+1 234 567 8900").
3. If the specific fact is not explicitly visible in the text, you MUST answer exactly: "Not specified in the document."
4. If reasoning or multiple elements are requested, you MUST provide a complete, full-sentence explanation covering all required points.
5. Do not include extra prefixes before exact match numbers or IDs (like "Fax: " before a fax number).

Return JSON with:
- answer: your exact string answer
- source_texts: list of direct quotes from context supporting your answer (max 3)
- warning: null, or "Low confidence" if you're unsure"""


class GroundedAnswer(BaseModel):
    answer: str
    source_texts: list[str]
    confidence: float
    warning: Optional[str] = None
    token_input: int = 0
    token_output: int = 0
    cost: float = 0.0
    faithfulness_score: float = 0.0
    completeness_score: float = 0.0


def generate_answer(question: str, chunks: list[dict], confidence: float) -> GroundedAnswer:
    if not chunks:
        return GroundedAnswer(
            answer="Not specified in the document.",
            source_texts=[],
            confidence=0.0,
            warning="No context retrieved"
        )

    numbered_context = "\n\n".join(
        f"[Source {i+1}, Page {c.get('source_page', '?')}]:\n{c['text']}"
        for i, c in enumerate(chunks[:5])
    )

    response = litellm.completion(
        model=settings.LITELLM_MODEL,
        messages=[
            {"role": "system", "content": ANSWERER_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nContext:\n{numbered_context}"}
        ],
        api_key=settings.OPENAI_API_KEY,
        response_format={"type": "json_object"},
    )

    raw_payload = response.choices[0].message.content
    data = json.loads(raw_payload)
    answer = data.get("answer", "Not specified in the document.")
    source_texts = data.get("source_texts", [])
    warning = data.get("warning")

    # Usage & Cost
    in_tokens = getattr(response.usage, "prompt_tokens", 0)
    out_tokens = getattr(response.usage, "completion_tokens", 0)
    # GPT-4o-mini rates ($0.15 / 1M in, $0.60 / 1M out)
    cost = (in_tokens * 0.15 / 1_000_000) + (out_tokens * 0.60 / 1_000_000)

    # JUDGE: True Faithfulness (Grounding) & Completeness
    faithfulness_score = 0.5
    completeness_score = 1.0
    if "not specified" not in answer.lower():
        try:
            judge_resp = litellm.completion(
                model=settings.LITELLM_MODEL,
                messages=[
                    {"role": "system", "content": """You are a strict logistics audit judge. 
Analyze the Answer given the Context.
1. FAITHFULNESS: Is every claim in the answer literally supported by the context? Pay extreme attention to roles (e.g., if the answer says 'Shipper' but context says 'Consignee', score is 0.0). Ignore formatting differences.
2. COMPLETENESS: If the question has multiple parts (e.g., 'weight AND units'), does the answer address ALL of them?

Return JSON with 'faithfulness' (0-1) and 'completeness' (0-1)."""},
                    {"role": "user", "content": f"Question: {question}\nAnswer: {answer}\n\nContext:\n{numbered_context}"}
                ],
                api_key=settings.OPENAI_API_KEY,
                response_format={"type": "json_object"},
            )
            judge_data = json.loads(judge_resp.choices[0].message.content)
            faithfulness_score = float(judge_data.get("faithfulness", 0.5))
            completeness_score = float(judge_data.get("completeness", 1.0))
        except: pass

    if "not specified" in answer.lower():
        return GroundedAnswer(
            answer=answer,
            source_texts=[],
            confidence=0.0,
            warning="Not specified in the document.",
            token_input=in_tokens,
            token_output=out_tokens,
            cost=cost,
            faithfulness_score=1.0,
            completeness_score=1.0
        )

    if confidence < 0.4:
        warning = "Low confidence — verify against source document"

    return GroundedAnswer(
        answer=answer,
        source_texts=source_texts,
        confidence=confidence,
        warning=warning,
        token_input=in_tokens,
        token_output=out_tokens,
        cost=cost,
        faithfulness_score=faithfulness_score,
        completeness_score=completeness_score
    )
