"""
LangGraph StateGraph orchestrating the agentic RAG loop:
Classify → Route → Retrieve (metadata-filtered) → Validate → [Rewrite → Retrieve]* → Answer
"""
from typing import TypedDict, Optional, Literal
from langgraph.graph import StateGraph, END

from app.agents.classifier import classify_query, QueryClassification
from app.agents.retriever import retrieve_vector, retrieve_graph, hybrid_retrieve
from app.agents.ranker import rank_chunks
from app.agents.validator import validate_retrieval, ValidationResult
from app.agents.answerer import generate_answer, GroundedAnswer
from app.services.metadata import MetadataFilter
from app.services.extractor import extract_structured


class AgentState(TypedDict):
    question: str
    document_id: str
    classification: Optional[dict]
    retrieved_chunks: list[dict]
    ranked_chunks: list[dict]
    validation: Optional[dict]
    answer: Optional[dict]
    retries: int
    filters: dict
    rewritten_query: str
    metrics: dict  # Dynamic metrics container



import logging

logger = logging.getLogger(__name__)

# ── Nodes ──────────────────────────────────────────────────────────────────────

def classify_node(state: AgentState) -> AgentState:
    import time
    start = time.time()
    logger.info("Step: Classifying query and routing...")
    result: QueryClassification = classify_query(state["question"])
    inferred = result.inferred_filters
    merged = MetadataFilter(
        document_id=state["document_id"],
        doc_type=inferred.doc_type,
        source_page=inferred.source_page,
    )
    
    # Heuristic complexity score
    normalized_len = min(len(state["question"]) / 200.0, 1.0)
    complexity = (0.4 * normalized_len) + (0.3 * (1.0 if result.query_type == "structure" else 0.5)) + 0.3
    
    metrics = state.get("metrics", {})
    metrics["query_complexity_score"] = round(complexity, 2)
    metrics["classify_latency"] = time.time() - start
    
    return {
        **state,
        "classification": {
            "query_type": result.query_type,
            "reasoning": result.reasoning,
        },
        "rewritten_query": result.rewritten_query,
        "filters": merged.model_dump(),
        "metrics": metrics,
    }


def retrieve_node(state: AgentState) -> AgentState:
    import time
    start = time.time()
    logger.info("Step: Retrieving chunks...")
    query = state["rewritten_query"]
    filters = MetadataFilter(**state["filters"])
    doc_id = state["document_id"]
    query_type = (state["classification"] or {}).get("query_type", "retrieval")

    if query_type == "structure":
        chunks = hybrid_retrieve(query, filters, doc_id)
        extracted_data = extract_structured(doc_id)
        chunks.append({
            "text": f"STRUCTURED DATA PAYLOAD:\n{extracted_data}",
            "source_page": 1,
            "similarity": 1.0,
            "doc_type": "synthetic_extraction"
        })
    else:
        chunks = retrieve_vector(query, filters)

    latency = time.time() - start
    
    # Calculate Similarity metrics
    similarities = [c.get("similarity", 0.0) for c in chunks] if chunks else [0.0]
    sim_max = max(similarities)
    sim_mean = sum(similarities) / len(similarities)
    
    metrics = state.get("metrics", {})
    metrics["retrieval_latency"] = round(metrics.get("retrieval_latency", 0) + latency, 3)
    metrics["context_similarity_max"] = round(sim_max, 3)
    metrics["context_similarity_mean"] = round(sim_mean, 3)
    metrics["retrieval_success"] = len(chunks) > 0
    metrics["retrieval_iterations"] = state["retries"] + 1

    return {**state, "retrieved_chunks": chunks, "metrics": metrics}


def rank_node(state: AgentState) -> AgentState:
    import time
    start = time.time()
    logger.info("Step: Reranking retrieved chunks for precision...")
    question = state["question"]
    chunks = state["retrieved_chunks"]
    
    # Reranking is only needed if there's more than 1 chunk and not structure-query
    query_type = (state["classification"] or {}).get("query_type", "retrieval")
    if len(chunks) > 1 and query_type != "structure":
        ranked = rank_chunks(question, chunks)
    else:
        ranked = chunks
        
    metrics = state.get("metrics", {})
    metrics["rerank_latency"] = round(time.time() - start, 3)
    
    return {**state, "ranked_chunks": ranked, "metrics": metrics}


def validate_node(state: AgentState) -> AgentState:
    import time
    start = time.time()
    logger.info("Step: Validating reranked context...")
    result: ValidationResult = validate_retrieval(
        state["rewritten_query"], state["ranked_chunks"]
    )
    
    metrics = state.get("metrics", {})
    metrics["validate_latency"] = round(time.time() - start, 3)
    
    # 0.7 * context_similarity_max + 0.3 * context_similarity_mean
    metrics["retrieval_confidence"] = round(0.7 * metrics.get("context_similarity_max", 0) + 0.3 * metrics.get("context_similarity_mean", 0), 2)
    
    # LLM-Judge scores
    metrics["context_relevance"] = result.context_relevance
    metrics["answer_relevance"] = result.answer_relevance

    return {
        **state,
        "validation": {
            "is_relevant": result.is_relevant,
            "confidence": result.confidence,
            "failure_reason": result.failure_reason,
        },
        "metrics": metrics
    }


def rewrite_node(state: AgentState) -> AgentState:
    logger.info("Step: Rewriting query to loosen filters and retry...")
    original = state["question"]
    broader_filters = MetadataFilter(document_id=state["document_id"])
    return {
        **state,
        "retries": state["retries"] + 1,
        "rewritten_query": f"Find information about: {original}",
        "filters": broader_filters.model_dump(),
    }


def answer_node(state: AgentState) -> AgentState:
    import time
    start = time.time()
    logger.info("Step: Generating final grounded answer...")
    validation = state["validation"] or {}
    
    result: GroundedAnswer = generate_answer(
        state["question"],
        state["ranked_chunks"],
        validation.get("confidence", 0.0),
    )
    
    latency = time.time() - start
    metrics = state.get("metrics", {})
    metrics["generation_latency"] = round(latency, 2)
    metrics["model_confidence"] = round(result.confidence, 2)
    metrics["faithfulness_score"] = round(result.faithfulness_score, 2)
    metrics["completeness_score"] = round(result.completeness_score, 2)
    metrics["answer_relevance"] = round(metrics.get("answer_relevance", 0), 2)
    
    # overall_confidence = 0.4 * model + 0.3 * retrieval + 0.3 * faithfulness
    metrics["overall_confidence"] = round((0.4 * result.confidence) + (0.3 * metrics.get("retrieval_confidence", 0)) + (0.3 * metrics["faithfulness_score"]), 2)
    metrics["confidence_gap"] = round(abs(metrics["overall_confidence"] - metrics["faithfulness_score"]), 2)
    
    # Usage metrics
    metrics["token_input"] = result.token_input
    metrics["token_output"] = result.token_output
    metrics["cost"] = round(result.cost, 6)
    
    # Hallucination logic: Stricter on Judge, relax on Similarity
    is_not_specified = "not specified" in result.answer.lower()
    metrics["hallucination_flag"] = False if is_not_specified else (
        metrics.get("faithfulness_score", 0) < 0.6 or 
        metrics.get("answer_relevance", 0) < 0.5
    )
    
    metrics["failure_mode"] = "none"
    if is_not_specified:
        metrics["failure_mode"] = "not_found"
    elif metrics["hallucination_flag"]:
        metrics["failure_mode"] = "hallucination"
        
    if not metrics.get("retrieval_success"):
        metrics["failure_mode"] = "retrieval_failure"

    metrics["answer_length"] = len(result.answer)
    
    # Total latency
    total_lat = (metrics.get("classify_latency", 0) + metrics.get("retrieval_latency", 0) + 
                 metrics.get("rerank_latency", 0) +
                 metrics.get("validate_latency", 0) + metrics.get("generation_latency", 0))
    metrics["latency_seconds"] = round(total_lat, 2)

    return {
        **state,
        "answer": {
            "answer": result.answer,
            "source_texts": result.source_texts,
            "confidence": metrics["overall_confidence"],
            "warning": result.warning,
            **metrics # Inject flattened metrics
        }
    }


def not_found_node(state: AgentState) -> AgentState:
    logger.warning("Step: Aborting. Emitting standard guardrail response.")
    failure = (state["validation"] or {}).get("failure_reason", "Low relevance")
    logger.info("====== PIPELINE END ======")
    return {
        **state,
        "answer": {
            "answer": "Couldn't find that in the document.",
            "source_texts": [],
            "confidence": 0.0,
            "warning": f"Guardrail triggered: {failure}",
            "failure_mode": "not_found",
            "hallucination_flag": False
        }
    }


# ── Routing ────────────────────────────────────────────────────────────────────

def should_continue(state: AgentState) -> Literal["retry", "answer", "fail"]:
    val = state.get("validation") or {}
    is_relevant = val.get("is_relevant", False)
    retries = state.get("retries", 0)

    if is_relevant:
        return "answer"
    if retries < 2:
        return "retry"
    return "fail"


# ── Build Graph ────────────────────────────────────────────────────────────────

def build_pipeline():
    workflow = StateGraph(AgentState)

    workflow.add_node("classify", classify_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("rank", rank_node)
    workflow.add_node("validate", validate_node)
    workflow.add_node("rewrite", rewrite_node)
    workflow.add_node("answer", answer_node)
    workflow.add_node("not_found", not_found_node)

    workflow.set_entry_point("classify")
    workflow.add_edge("classify", "retrieve")
    workflow.add_edge("retrieve", "rank")
    workflow.add_edge("rank", "validate")
    workflow.add_edge("rewrite", "retrieve")
    workflow.add_edge("answer", END)
    workflow.add_edge("not_found", END)

    workflow.add_conditional_edges(
        "validate",
        should_continue,
        {"retry": "rewrite", "answer": "answer", "fail": "not_found"},
    )

    return workflow.compile()


# Singleton pipeline instance
_pipeline = None

def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = build_pipeline()
    return _pipeline


def run_pipeline(document_id: str, question: str, fast_mode: bool = False, query_id: str = None) -> dict:
    import time
    from app.agents.retriever import parallel_retrieve
    from app.services.metadata import MetadataFilter
    from app.agents.mega_node import run_mega_node

    if fast_mode:
        start_time = time.time()
        logger.info(f"⚡ FAST MODE Pipeline triggered for query: {question}")
        filters = MetadataFilter(document_id=document_id)
        
        # Parallel Retrieve
        ret_start = time.time()
        chunks = parallel_retrieve(question, filters, document_id)
        ret_lat = time.time() - ret_start
        
        # Single Mega-Node Call
        result = run_mega_node(question, chunks, document_id, query_id)
        
        # Inject fast-mode specific metrics
        result["retrieval_latency"] = round(ret_lat, 2)
        result["latency_seconds"] = round(time.time() - start_time, 2)
        result["retrieval_success"] = len(chunks) > 0
        result["retrieval_iterations"] = 1
        return result

    pipeline = get_pipeline()
    initial_state: AgentState = {
        "question": question,
        "document_id": document_id,
        "classification": None,
        "retrieved_chunks": [],
        "ranked_chunks": [],
        "validation": None,
        "answer": None,
        "retries": 0,
        "filters": {"document_id": document_id},
        "rewritten_query": question,
        "metrics": {},
    }
    final_state = pipeline.invoke(initial_state)
    ans = final_state.get("answer", {
        "answer": "Couldn't find that in the document.",
        "source_texts": [],
        "confidence": 0.0,
        "warning": "Pipeline completed without answer",
    })
    ans["query_id"] = query_id
    return ans
