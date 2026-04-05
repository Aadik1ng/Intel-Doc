from fastapi import APIRouter, HTTPException
from app.models.document import ExtractionRequest
from app.services.extractor import extract_structured

router = APIRouter()

@router.post("/extract")
def extract_shipment(request: ExtractionRequest):
    if not request.document_id:
        raise HTTPException(400, "document_id is required")

    result = extract_structured(request.document_id)
    return {"document_id": request.document_id, "shipment_data": result}
