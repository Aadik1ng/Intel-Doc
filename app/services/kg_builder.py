import litellm
import logging
from typing import List
from llama_index.core import PropertyGraphIndex
from llama_index.core.indices.property_graph import SchemaLLMPathExtractor
from llama_index.graph_stores.memgraph import MemgraphPropertyGraphStore
from llama_index.core.schema import TextNode
from llama_index.llms.openai import OpenAI as LlamaOpenAI
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.core.graph_stores.types import (
    LabelledNode,
    Relation,
    EntityNode,
    ChunkNode,
)
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Logistics-domain schema for constrained KG extraction
LOGISTICS_ENTITIES = ["Shipper", "Consignee", "Carrier", "Location", "Equipment", "Shipment"]
LOGISTICS_RELATIONS = ["SHIPS_FROM", "SHIPS_TO", "CARRIED_BY", "LOCATED_AT", "HAS_EQUIPMENT", "DELIVERS_TO"]
LOGISTICS_SCHEMA = {
    "Shipper": ["SHIPS_FROM", "SHIPS_TO"],
    "Consignee": ["LOCATED_AT"],
    "Carrier": ["CARRIED_BY"],
    "Shipment": ["SHIPS_FROM", "SHIPS_TO", "CARRIED_BY", "HAS_EQUIPMENT", "DELIVERS_TO"],
    "Equipment": ["HAS_EQUIPMENT"],
}

# ── Monkeypatch for LlamaIndex Memgraph Store ──────────────────────────────────
# The current LlamaIndex MemgraphPropertyGraphStore has a bug where it tries to
# use 'SET n:row.label' and '-[r:row.label]->' which is invalid Cypher syntax.

def patched_upsert_nodes(self, nodes: List[LabelledNode]) -> None:
    from llama_index.graph_stores.memgraph.property_graph import BASE_NODE_LABEL, BASE_ENTITY_LABEL, CHUNK_SIZE
    entity_dicts = []
    chunk_dicts = []
    for item in nodes:
        if isinstance(item, EntityNode):
            entity_dicts.append({**item.dict(), "id": item.id})
        elif isinstance(item, ChunkNode):
            chunk_dicts.append({**item.dict(), "id": item.id})
            
    if chunk_dicts:
        for i in range(0, len(chunk_dicts), CHUNK_SIZE):
            batch = chunk_dicts[i : i + CHUNK_SIZE]
            self.structured_query(
                f"UNWIND $data AS row MERGE (c:{BASE_NODE_LABEL} {{id: row.id}}) "
                "SET c.text = row.text, c:Chunk SET c += row.properties "
                "WITH c, row WHERE row.embedding IS NOT NULL SET c.embedding = row.embedding",
                param_map={"data": batch}
            )

    if entity_dicts:
        # Group by label to avoid dynamic label syntax error
        by_label = {}
        for d in entity_dicts:
            lbl = d.get("label") or "Entity"
            by_label.setdefault(lbl, []).append(d)
        
        for lbl, batch in by_label.items():
            for i in range(0, len(batch), CHUNK_SIZE):
                sub_batch = batch[i : i + CHUNK_SIZE]
                # Filter out potentially invalid characters in label
                safe_label = "".join(c for c in lbl if c.isalnum() or c == "_")
                self.structured_query(
                    f"UNWIND $data AS row MERGE (e:{BASE_NODE_LABEL} {{id: row.id}}) "
                    f"SET e:{BASE_ENTITY_LABEL}, e:{safe_label} "
                    "SET e += CASE WHEN row.properties IS NOT NULL THEN row.properties ELSE e END "
                    "SET e.name = CASE WHEN row.name IS NOT NULL THEN row.name ELSE e.name END "
                    "WITH e, row WHERE row.embedding IS NOT NULL SET e.embedding = row.embedding "
                    "WITH e, row WHERE row.properties.triplet_source_id IS NOT NULL "
                    f"MERGE (c:{BASE_NODE_LABEL} {{id: row.properties.triplet_source_id}}) "
                    "MERGE (e)<-[:MENTIONS]-(c)",
                    param_map={"data": sub_batch}
                )

def patched_upsert_relations(self, relations: List[Relation]) -> None:
    from llama_index.graph_stores.memgraph.property_graph import BASE_NODE_LABEL, CHUNK_SIZE
    by_rel = {}
    for r in relations:
        lbl = r.label or "RELATED_TO"
        by_rel.setdefault(lbl, []).append(r.dict())
    
    for lbl, batch in by_rel.items():
        for i in range(0, len(batch), CHUNK_SIZE):
            sub_batch = batch[i : i + CHUNK_SIZE]
            safe_label = "".join(c for c in lbl if c.isalnum() or c == "_")
            self.structured_query(
                f"UNWIND $data AS row "
                f"MERGE (source:{BASE_NODE_LABEL} {{id: row.source_id}}) "
                f"MERGE (target:{BASE_NODE_LABEL} {{id: row.target_id}}) "
                f"MERGE (source)-[r:{safe_label}]->(target) "
                "SET r += row.properties",
                param_map={"data": sub_batch}
            )

# Apply patches
MemgraphPropertyGraphStore.upsert_nodes = patched_upsert_nodes
MemgraphPropertyGraphStore.upsert_relations = patched_upsert_relations

# ── End Monkeypatch ──────────────────────────────────────────────────────────

def build_knowledge_graph(nodes: list[TextNode], doc_id: str):
    """Use LlamaIndex PropertyGraphIndex to build a logistics KG in Memgraph."""
    try:
        llm = LlamaOpenAI(
            model=settings.CHAT_MODEL,
            api_key=settings.OPENAI_API_KEY,
        )
        embed_model = OpenAIEmbedding(
            model=settings.EMBEDDING_MODEL,
            api_key=settings.OPENAI_API_KEY,
        )
        graph_store = MemgraphPropertyGraphStore(
            url=f"bolt://{settings.MEMGRAPH_HOST}:{settings.MEMGRAPH_PORT}",
            username="",
            password="",
        )
        kg_extractor = SchemaLLMPathExtractor(
            llm=llm,
            possible_entities=LOGISTICS_ENTITIES,
            possible_relations=LOGISTICS_RELATIONS,
            kg_validation_schema=LOGISTICS_SCHEMA,
            strict=False,
        )
        PropertyGraphIndex(
            nodes=nodes[:30],  # Limit KG nodes for speed/cost on POC
            property_graph_store=graph_store,
            kg_extractors=[kg_extractor],
            embed_kg_nodes=False,
            show_progress=False,
        )
        logger.info(f"KG built for doc {doc_id}")
    except Exception as e:
        logger.warning(f"KG build failed (non-fatal): {e}")
