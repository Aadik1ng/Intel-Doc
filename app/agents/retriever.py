"""
LangChain-based metadata-filtered retriever + LlamaIndex graph retriever.
This is the dual-path retriever that forms the core of the agentic pipeline.
"""
from typing import Optional, List
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from pydantic import Field

from app.services.embedder import embed_query
from app.services.graph import vector_search, graph_traverse
from app.services.metadata import MetadataFilter


class MemgraphMetadataRetriever(BaseRetriever):
    """LangChain retriever with Memgraph vector search + Cypher metadata post-filtering."""

    top_k: int = Field(default=15)
    filters: MetadataFilter = Field(default_factory=MetadataFilter)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None,
    ) -> List[Document]:
        query_embedding = embed_query(query)
        results = vector_search(query_embedding, self.top_k, self.filters)

        docs = []
        for r in results:
            docs.append(Document(
                page_content=r["text"],
                metadata={
                    "source_page": r["source_page"],
                    "doc_type": r["doc_type"],
                    "document_id": r["document_id"],
                    "chunk_index": r.get("chunk_index"),
                    "similarity": r["similarity"],
                }
            ))
        return docs


def retrieve_vector(query: str, filters: MetadataFilter, top_k: int = 15) -> list[dict]:
    """Path A: LangChain metadata-filtered vector retrieval."""
    retriever = MemgraphMetadataRetriever(top_k=top_k, filters=filters)
    docs = retriever.invoke(query)
    return [
        {
            "text": d.page_content,
            "source_page": d.metadata.get("source_page"),
            "doc_type": d.metadata.get("doc_type"),
            "similarity": d.metadata.get("similarity", 0.0),
        }
        for d in docs
    ]


def retrieve_graph(doc_id: str, entity_name: str) -> list[dict]:
    """Path B: LlamaIndex-compatible graph traversal from entity name."""
    return graph_traverse(doc_id, entity_name)


def hybrid_retrieve(query: str, filters: MetadataFilter, doc_id: str) -> list[dict]:
    """Merge vector + graph results, deduplicate by text content."""
    vec_results = retrieve_vector(query, filters)

    # Try to extract a key entity term from query for graph traversal
    words = [w.strip("?.,'") for w in query.split() if len(w) > 4]
    graph_results = []
    for word in words[:3]:
        graph_results.extend(retrieve_graph(doc_id, word))

    seen = set()
    combined = []
    for r in vec_results + graph_results:
        key = r["text"][:80]
        if key not in seen:
            seen.add(key)
            combined.append(r)

    return combined[:12]  # Cap at 12 total results
