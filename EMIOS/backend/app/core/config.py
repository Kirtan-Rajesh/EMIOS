import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    PORT: int = 8000
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "emios_secure_password"
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # LLM Settings
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    
    AZURE_OPENAI_API_KEY: Optional[str] = None
    AZURE_OPENAI_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_DEPLOYMENT: Optional[str] = "gpt-4o"
    AZURE_OPENAI_API_VERSION: Optional[str] = "2024-05-01-preview"

    # Langfuse Observability Settings (Self-Hosted / Cloud)
    LANGFUSE_PUBLIC_KEY: Optional[str] = "pk-lf-emios-local"
    LANGFUSE_SECRET_KEY: Optional[str] = "sk-lf-emios-local"
    LANGFUSE_HOST: str = "http://localhost:3000"  # Self-Hosted Langfuse Server or https://cloud.langfuse.com
    ENABLE_LANGFUSE_TRACING: bool = True

    # Multi-Agent Settings
    MANDATORY_LLM_CALLS: bool = True
    LLM_TEMPERATURE: float = 0.2
    MAX_SIMULATION_RUNS: int = 1000

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
