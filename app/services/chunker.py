from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode
from datetime import datetime, timezone


def chunk_document(parsed_data: dict, doc_id: str, doc_type: str = "unknown") -> list[TextNode]:
    splitter = SentenceSplitter(chunk_size=256, chunk_overlap=50)
    nodes = []

    filename = parsed_data["metadata"]["filename"]
    uploaded_at = datetime.now(timezone.utc).isoformat()

    for page_entry in parsed_data["pages"]:
        page_num = page_entry["page"]
        page_text = page_entry["text"].strip()
        if not page_text:
            continue

        chunks = splitter.split_text(page_text)
        for idx, chunk in enumerate(chunks):
            node = TextNode(
                text=chunk,
                metadata={
                    "document_id": doc_id,
                    "filename": filename,
                    "file_type": parsed_data["metadata"]["file_type"],
                    "doc_type": doc_type,
                    "source_page": page_num,
                    "chunk_index": idx,
                    "uploaded_at": uploaded_at,
                },
                excluded_embed_metadata_keys=["document_id", "uploaded_at"],
                excluded_llm_metadata_keys=["document_id", "chunk_index"],
            )
            nodes.append(node)

    return nodes
