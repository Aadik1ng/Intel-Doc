import litellm
import json
from app.config import get_settings
from app.services.graph import get_all_chunks
from app.models.document import ShipmentData

settings = get_settings()

EXTRACTION_SYSTEM_PROMPT = """You are a logistics document parser. Extract structured shipment data from the provided document text.
Return ONLY a valid JSON object with exactly these keys:
shipment_id, shipper, consignee, pickup_datetime, delivery_datetime,
equipment_type, mode, rate, currency, weight, carrier_name.
Use null for any field not found in the document. Do not invent or assume values."""


def extract_structured(doc_id: str) -> dict:
    chunks = get_all_chunks(doc_id)
    full_text = "\n\n".join(chunks)[:12000]  # Token budget limit

    response = litellm.completion(
        model=settings.LITELLM_MODEL,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Document text:\n{full_text}"}
        ],
        api_key=settings.OPENAI_API_KEY,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    data = json.loads(raw)

    # Validate with Pydantic, fill missing with None. Convert all nested types to strings.
    shipment_dict = {}
    for k in ShipmentData.model_fields:
        val = data.get(k)
        shipment_dict[k] = str(val) if val is not None else None
        
    shipment = ShipmentData(**shipment_dict)
    return shipment.model_dump()


def extract_entities_from_text(text: str) -> list[dict]:
    """Extract logistics entities for KG population."""
    prompt = """Extract named entities from this logistics document text.
Return a JSON array of objects with keys: "name" and "type".
Entity types: Shipper, Consignee, Carrier, Location, Equipment, Date, Rate.
Only extract entities clearly mentioned in the text."""

    response = litellm.completion(
        model=settings.LITELLM_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text[:4000]}
        ],
        api_key=settings.OPENAI_API_KEY,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    try:
        result = json.loads(raw)
        entities = result.get("entities", result) if isinstance(result, dict) else result
        return entities if isinstance(entities, list) else []
    except Exception:
        return []


def classify_doc_type(text: str) -> str:
    """Classify document into a logistics document category."""
    prompt = """Classify this logistics document. Return ONLY one of:
rate_confirmation, bol, invoice, shipment_instructions, other"""

    response = litellm.completion(
        model=settings.LITELLM_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text[:2000]}
        ],
        api_key=settings.OPENAI_API_KEY,
    )
    raw = response.choices[0].message.content.strip().lower()
    valid = {"rate_confirmation", "bol", "invoice", "shipment_instructions", "other"}
    return raw if raw in valid else "other"
