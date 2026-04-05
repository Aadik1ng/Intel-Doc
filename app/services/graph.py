from neo4j import GraphDatabase
from app.config import get_settings
from app.services.metadata import MetadataFilter, build_cypher_where
from llama_index.core.schema import TextNode
import logging

logger = logging.getLogger(__name__)
settings = get_settings()


def get_driver():
    return GraphDatabase.driver(
        f"bolt://{settings.MEMGRAPH_HOST}:{settings.MEMGRAPH_PORT}",
        auth=("", ""),
    )


def setup_indexes():
    """Create vector index and property indexes on startup."""
    driver = get_driver()
    with driver.session() as session:
        try:
            session.run(
                """
                CREATE VECTOR INDEX chunk_embeddings
                ON :Chunk(embedding)
                WITH CONFIG {"dimension": 1536, "capacity": 100000, "metric": "cos"}
                """
            )
        except Exception:
            pass  # Index already exists

        for prop in ["document_id", "doc_type", "source_page"]:
            try:
                session.run(f"CREATE INDEX ON :Chunk({prop})")
            except Exception:
                pass

    driver.close()


def store_document(doc_id: str, filename: str, file_type: str, doc_type: str):
    driver = get_driver()
    with driver.session() as session:
        session.run(
            """
            MERGE (d:Document {id: $doc_id})
            SET d.filename = $filename,
                d.file_type = $file_type,
                d.doc_type = $doc_type
            """,
            doc_id=doc_id, filename=filename,
            file_type=file_type, doc_type=doc_type,
        )
    driver.close()


def store_chunks(nodes: list[TextNode], embeddings: list[list[float]]):
    driver = get_driver()
    with driver.session() as session:
        for node, emb in zip(nodes, embeddings):
            m = node.metadata
            chunk_id = f"{m['document_id']}__p{m['source_page']}_c{m['chunk_index']}"
            session.run(
                """
                MERGE (c:Chunk {id: $chunk_id})
                SET c.text = $text,
                    c.document_id = $doc_id,
                    c.filename = $filename,
                    c.file_type = $file_type,
                    c.doc_type = $doc_type,
                    c.source_page = $source_page,
                    c.chunk_index = $chunk_index,
                    c.embedding = $embedding
                WITH c
                MATCH (d:Document {id: $doc_id})
                MERGE (d)-[:HAS_CHUNK]->(c)
                """,
                chunk_id=chunk_id,
                text=node.text,
                doc_id=m["document_id"],
                filename=m["filename"],
                file_type=m["file_type"],
                doc_type=m["doc_type"],
                source_page=m["source_page"],
                chunk_index=m["chunk_index"],
                embedding=emb,
            )
    driver.close()


def store_entities(doc_id: str, entities: list[dict]):
    """Store extracted entities as nodes linked to their source chunks."""
    driver = get_driver()
    with driver.session() as session:
        for ent in entities:
            session.run(
                """
                MERGE (e:Entity {name: $name, type: $type})
                WITH e
                MATCH (c:Chunk {document_id: $doc_id})
                WHERE c.text CONTAINS $name
                MERGE (c)-[:MENTIONS]->(e)
                """,
                name=ent["name"], type=ent["type"], doc_id=doc_id,
            )
    driver.close()


def vector_search(query_embedding: list[float], top_k: int, filters: MetadataFilter) -> list[dict]:
    """Vector similarity search with metadata post-filtering."""
    where_clause = build_cypher_where(filters)
    where_stmt = f"WHERE {where_clause}" if where_clause else ""

    cypher = f"""
        CALL vector_search.search("chunk_embeddings", 20, $embedding)
        YIELD node AS c, similarity
        WITH c, similarity
        {where_stmt}
        RETURN c.text AS text,
               c.source_page AS source_page,
               c.document_id AS document_id,
               c.doc_type AS doc_type,
               c.chunk_index AS chunk_index,
               similarity
        ORDER BY similarity DESC
        LIMIT $top_k
    """

    driver = get_driver()
    results = []
    with driver.session() as session:
        records = session.run(cypher, embedding=query_embedding, top_k=top_k)
        for r in records:
            results.append({
                "text": r["text"],
                "source_page": r["source_page"],
                "document_id": r["document_id"],
                "doc_type": r["doc_type"],
                "chunk_index": r["chunk_index"],
                "similarity": r["similarity"],
            })
    driver.close()
    return results


def get_all_chunks(doc_id: str) -> list[str]:
    """Get all chunk texts for a document (used in extraction)."""
    cypher = """
        MATCH (d:Document {id: $doc_id})-[:HAS_CHUNK]->(c:Chunk)
        RETURN c.text AS text ORDER BY c.source_page, c.chunk_index
    """
    driver = get_driver()
    texts = []
    with driver.session() as session:
        for r in session.run(cypher, doc_id=doc_id):
            texts.append(r["text"])
    driver.close()
    return texts


def graph_traverse(doc_id: str, entity_name: str) -> list[dict]:
    """BFS-style graph traversal from a named entity to find related chunks."""
    cypher = """
        MATCH (e:Entity {name: $name})<-[:MENTIONS]-(c:Chunk {document_id: $doc_id})
        RETURN c.text AS text, c.source_page AS source_page, 1.0 AS similarity
        LIMIT 5
    """
    driver = get_driver()
    results = []
    with driver.session() as session:
        for r in session.run(cypher, name=entity_name, doc_id=doc_id):
            results.append({
                "text": r["text"],
                "source_page": r["source_page"],
                "similarity": r["similarity"],
            })
    driver.close()
    return results
