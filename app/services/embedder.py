import litellm
from app.config import get_settings

settings = get_settings()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using LiteLLM (OpenAI text-embedding-3-small)."""
    response = litellm.embedding(
        model=f"openai/{settings.EMBEDDING_MODEL}",
        input=texts,
        api_key=settings.OPENAI_API_KEY,
    )
    return [item["embedding"] for item in response["data"]]


def embed_query(query: str) -> list[float]:
    """Embed a single query string."""
    return embed_texts([query])[0]
