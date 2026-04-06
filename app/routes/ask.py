from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from app.models.document import AskRequest, AskResponse
from app.agents.pipeline import run_pipeline
import openai
from app.config import get_settings

router = APIRouter()

@router.post("/ask", response_model=AskResponse)
def ask_question(request: AskRequest):
    if not request.document_id:
        raise HTTPException(400, "document_id is required")
    if not request.question.strip():
        raise HTTPException(400, "question cannot be empty")

    result = run_pipeline(request.document_id, request.question, fast_mode=request.fast_mode, query_id=request.query_id)

    # Legacy confidence support
    ov_conf = result.get("overall_confidence", result.get("confidence", 0.0))

    return AskResponse(
        answer=result.get("answer", "Not found in document."),
        source_texts=result.get("source_texts", []),
        confidence=ov_conf,
        warning=result.get("warning"),
        query_id=result.get("query_id"),
        
        # New observability metrics
        model_confidence=result.get("model_confidence"),
        retrieval_confidence=result.get("retrieval_confidence"),
        overall_confidence=ov_conf,
        confidence_gap=result.get("confidence_gap"),
        
        latency_seconds=result.get("latency_seconds"),
        retrieval_latency=result.get("retrieval_latency"),
        generation_latency=result.get("generation_latency"),
        
        retrieval_success=result.get("retrieval_success"),
        context_similarity_mean=result.get("context_similarity_mean"),
        context_similarity_max=result.get("context_similarity_max"),
        retrieval_iterations=result.get("retrieval_iterations"),
        
        answer_relevance=result.get("answer_relevance"),
        faithfulness_score=result.get("faithfulness_score"),
        completeness_score=result.get("completeness_score"),
        context_utilization=result.get("context_utilization"),
        
        hallucination_flag=result.get("hallucination_flag"),
        guardrail_type=result.get("guardrail_type"),
        failure_mode=result.get("failure_mode"),
        
        token_input=result.get("token_input"),
        token_output=result.get("token_output"),
        cost=result.get("cost"),
        
        query_complexity_score=result.get("query_complexity_score"),
        answer_length=result.get("answer_length"),
    )

@router.post("/ask_audio", response_model=AskResponse)
async def ask_audio(document_id: str = Form(...), query_id: str = Form("0"), file: UploadFile = File(...)):
    settings = get_settings()
    # openai 2.x uses AsyncOpenAI
    client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    
    # Read file content into memory for Whisper
    content = await file.read()
    
    transcription = await client.audio.transcriptions.create(
        model="whisper-1",
        file=(file.filename, content, file.content_type)
    )
    
    question = transcription.text
    if not question.strip():
        raise HTTPException(400, "Could not transcribe audio")
        
    req = AskRequest(
        document_id=document_id,
        question=question,
        fast_mode=True,
        query_id=query_id
    )
    
    # Hand off to standard text pipeline execution
    resp = ask_question(req)
    resp.transcribed_question = f"🎤 {question}"
    return resp
