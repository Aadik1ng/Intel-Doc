from pydantic import BaseModel, Field
from typing import Optional, List, Literal

class DocumentMeta(BaseModel):
    document_id: str
    filename: str
    file_type: str
    uploaded_at: str
    doc_type: Optional[str] = None
    num_chunks: Optional[int] = None

class UploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str = "success"

class MetadataFilter(BaseModel):
    document_id: Optional[str] = None
    doc_type: Optional[str] = None
    source_page: Optional[int] = None
    source_page_range: Optional[List[int]] = None

class AskRequest(BaseModel):
    document_id: str
    question: str
    filters: Optional[MetadataFilter] = None

class AskResponse(BaseModel):
    answer: str
    source_texts: List[str]
    confidence: float
    warning: Optional[str] = None
    
    # Advanced Metrics
    model_confidence: Optional[float] = None
    retrieval_confidence: Optional[float] = None
    overall_confidence: Optional[float] = None
    confidence_gap: Optional[float] = None
    
    latency_seconds: Optional[float] = None
    retrieval_latency: Optional[float] = None
    generation_latency: Optional[float] = None
    
    retrieval_success: Optional[bool] = None
    context_similarity_mean: Optional[float] = None
    context_similarity_max: Optional[float] = None
    retrieval_iterations: Optional[int] = None
    
    answer_relevance: Optional[float] = None
    faithfulness_score: Optional[float] = None
    completeness_score: Optional[float] = None
    context_utilization: Optional[float] = None
    
    hallucination_flag: Optional[bool] = None
    guardrail_type: Optional[str] = None
    failure_mode: Optional[str] = None
    
    token_input: Optional[int] = None
    token_output: Optional[int] = None
    cost: Optional[float] = None
    
    query_complexity_score: Optional[float] = None
    answer_length: Optional[int] = None


class ExtractionRequest(BaseModel):
    document_id: str

class ShipmentData(BaseModel):
    shipment_id: Optional[str] = None
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    pickup_datetime: Optional[str] = None
    delivery_datetime: Optional[str] = None
    equipment_type: Optional[str] = None
    mode: Optional[str] = None
    rate: Optional[str] = None
    currency: Optional[str] = None
    weight: Optional[str] = None
    carrier_name: Optional[str] = None
