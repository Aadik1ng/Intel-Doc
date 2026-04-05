from typing import Optional, List
from pydantic import BaseModel

class MetadataFilter(BaseModel):
    document_id: Optional[str] = None
    doc_type: Optional[str] = None
    source_page: Optional[int] = None
    source_page_range: Optional[List[int]] = None

def build_cypher_where(filters: MetadataFilter) -> str:
    clauses = []
    if filters.document_id:
        clauses.append(f'c.document_id = "{filters.document_id}"')
    if filters.doc_type:
        clauses.append(f'c.doc_type = "{filters.doc_type}"')
    if filters.source_page is not None:
        clauses.append(f'c.source_page = {filters.source_page}')
    if filters.source_page_range and len(filters.source_page_range) == 2:
        lo, hi = filters.source_page_range
        clauses.append(f'c.source_page >= {lo} AND c.source_page <= {hi}')
    
    return " AND ".join(clauses)
