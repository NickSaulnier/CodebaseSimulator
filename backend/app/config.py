from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:latest"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # RAG (ChromaDB + sentence-transformers)
    chroma_persist_dir: str = ".chroma"
    rag_embedding_model: str = "all-MiniLM-L6-v2"
    rag_chunk_lines: int = 55
    rag_chunk_overlap_lines: int = 10
    rag_top_k: int = 8
    rag_enabled: bool = True


settings = Settings()
