# Ultra Doc-Intelligence

Agentic GraphRAG POC for logistics document Q&A using **Memgraph 3.0**, **LlamaIndex**, **LangChain/LangGraph**, and **LiteLLM**.

## Architecture

```
Upload Flow:   PDF/DOCX/TXT → Parser → SentenceSplitter (LlamaIndex) → LiteLLM Embeddings → Memgraph
                                    → LiteLLM Entity Extraction → Memgraph
                                    → LlamaIndex PropertyGraphIndex (KG build, async)

Ask Flow:      Question → LangGraph StateGraph
                 ├─ Classify (LiteLLM) → query_type + inferred_filters
                 ├─ Retrieve (LangChain MemgraphMetadataRetriever, metadata-filtered)
                 ├─ Validate (3-layer guardrail: similarity + LLM + agreement)
                 ├─ [Rewrite + Retry × 2 if invalid]
                 └─ Answer (LiteLLM, grounded, with source attribution)

Extract Flow:  All chunks → LiteLLM → ShipmentData JSON (11 fields, null if missing)
```

## Chunking Strategy

- **LlamaIndex `SentenceSplitter`**: 512 tokens, 50-token overlap
- Respects sentence boundaries — no mid-sentence cuts
- Each chunk is a `TextNode` with metadata: `document_id`, `filename`, `file_type`, `doc_type`, `source_page`, `chunk_index`

## Retrieval Method

**Dual-path hybrid retrieval:**
1. **Path A** — LangChain `MemgraphMetadataRetriever`: vector search + Cypher WHERE post-filtering
2. **Path B** — Graph traversal via entity-chunk edges in Memgraph
3. **Hybrid** — Both paths merged and deduplicated for `structure` queries

**Metadata Filtering (3 levels):**
- Level 1: `document_id` always applied (prevents cross-doc contamination)
- Level 2: Auto-inferred from question ("on page 3" → `source_page=3`)
- Level 3: Explicit user filters in `/ask` request body

## Guardrails

1. **Similarity threshold** — block if best chunk similarity < 0.35
2. **LLM relevance check** — ask model if context answers the question
3. **Chunk agreement** — penalise when top chunks diverge significantly

## Confidence Scoring

```
confidence = 0.4 × avg_similarity + 0.3 × llm_relevance_score + 0.3 × chunk_agreement
```

Displayed as 🟢 High (≥70%) | 🟡 Medium (≥40%) | 🔴 Low (<40%)

## Setup & Run

### Prerequisites
- Docker (for Memgraph)
- Conda environment `memrag` with Python 3.11

### 1. Start Memgraph
```bash
docker-compose up -d
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### 3. Start API
```bash
conda activate memrag
uvicorn app.main:app --reload --port 8000
```

### 4. Start UI
```bash
conda activate memrag
python -m streamlit run .\ui\streamlit_app.py```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/upload` | Upload PDF/DOCX/TXT |
| POST | `/ask` | Ask a question (with optional metadata filters) |
| POST | `/extract` | Extract structured shipment data |
| GET | `/health` | Health check |

### Example `/ask` with filters
```json
{
  "document_id": "abc-123",
  "question": "What is the carrier rate?",
  "filters": {"source_page": 1, "doc_type": "rate_confirmation"}
}
```

## Failure Cases & Improvements

**Known failure cases:**
- Scanned image PDFs with no text layer (OCR not included in this POC)
- Very short documents with insufficient context for confident retrieval
- Ambiguous questions with multiple possible answers in different chunks

**Improvement ideas:**
- Add OCR fallback (Tesseract/Surya) for scanned PDFs
- Add multi-document comparison queries
- Implement conversation history with LangGraph memory
- Add re-ranking (Cohere Rerank) after vector retrieval
- Expose Memgraph Lab visualisation in UI
