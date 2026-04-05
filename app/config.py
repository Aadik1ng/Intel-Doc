from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    OPENAI_API_KEY: str
    MEMGRAPH_HOST: str = "localhost"
    MEMGRAPH_PORT: int = 7687
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    CHAT_MODEL: str = "gpt-4o-mini"
    LITELLM_MODEL: str = "openai/gpt-4o-mini"

@lru_cache()
def get_settings():
    return Settings()
