import litellm
import json
from typing import Literal
from pydantic import BaseModel
from app.config import get_settings
from app.services.metadata import MetadataFilter

settings = get_settings()


class QueryClassification(BaseModel):
    query_type: Literal["retrieval", "structure", "extraction"]
    rewritten_query: str
    inferred_filters: MetadataFilter
    reasoning: str


CLASSIFIER_PROMPT = """You are a query classification agent for a logistics document assistant.

Classify the user's question into one of:
- "retrieval": Direct fact lookup (rate, date, name, weight, etc.)
- "structure": Relationship question (who ships to whom, what route, connections)
- "extraction": Request to extract all structured shipment fields

Also:
1. Rewrite the query to be clearer and more search-friendly
2. Infer metadata filters if the question implies them:
   - "on page 3" → source_page: 3
   - "from the BOL" or "bill of lading" → doc_type: "bol"
   - "from the invoice" → doc_type: "invoice"
   - "rate confirmation" → doc_type: "rate_confirmation"

Return a JSON object with keys:
query_type, rewritten_query, inferred_filters (object with optional keys: doc_type, source_page), reasoning"""


def classify_query(question: str) -> QueryClassification:
    response = litellm.completion(
        model=settings.LITELLM_MODEL,
        messages=[
            {"role": "system", "content": CLASSIFIER_PROMPT},
            {"role": "user", "content": question},
        ],
        api_key=settings.OPENAI_API_KEY,
        response_format={"type": "json_object"},
    )
    data = json.loads(response.choices[0].message.content)

    # Parse inferred_filters safely
    raw_filters = data.get("inferred_filters", {}) or {}
    inferred = MetadataFilter(
        doc_type=raw_filters.get("doc_type"),
        source_page=raw_filters.get("source_page"),
    )

    return QueryClassification(
        query_type=data.get("query_type", "retrieval"),
        rewritten_query=data.get("rewritten_query", question),
        inferred_filters=inferred,
        reasoning=data.get("reasoning", ""),
    )
