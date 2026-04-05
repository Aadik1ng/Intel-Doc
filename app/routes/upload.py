import uuid
import tempfile
import os
import asyncio
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.services.parser import parse_document
from app.services.chunker import chunk_document
from app.services.embedder import embed_texts
from app.services.graph import store_document, store_chunks, store_entities
from app.services.extractor import extract_entities_from_text, classify_doc_type
from app.services.kg_builder import build_knowledge_graph

router = APIRouter()

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    allowed = {".pdf", ".docx", ".txt"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        raise HTTPException(400, f"Unsupported file type: {ext}. Use PDF, DOCX, or TXT.")

    doc_id = str(uuid.uuid4())

    # Save uploaded file to temp
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # 1. Parse
        parsed = parse_document(tmp_path, file.filename)

        # 2. Classify document type
        doc_type = classify_doc_type(parsed["text"][:2000])

        # 3. Chunk with metadata
        nodes = chunk_document(parsed, doc_id, doc_type)

        # 4. Embed all chunks
        texts = [n.text for n in nodes]
        embeddings = embed_texts(texts)

        # 5. Store in Memgraph
        store_document(doc_id, file.filename, parsed["metadata"]["file_type"], doc_type)
        store_chunks(nodes, embeddings)

        # 6. Extract entities for KG
        entities = extract_entities_from_text(parsed["text"][:4000])
        if entities:
            store_entities(doc_id, entities)

        # 7. Build LlamaIndex PropertyGraph (non-blocking)
        asyncio.create_task(
            asyncio.to_thread(build_knowledge_graph, nodes, doc_id)
        )

        return {
            "document_id": doc_id,
            "filename": file.filename,
            "doc_type": doc_type,
            "num_chunks": len(nodes),
            "entities_found": len(entities),
            "status": "success",
        }

    finally:
        os.unlink(tmp_path)
