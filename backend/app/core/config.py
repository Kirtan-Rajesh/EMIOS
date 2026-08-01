import os
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    PORT: int = 8000
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "emios_secure_password"
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # Relational persistence layer (assessments/uploads/waves - see app/db, app/entities).
    # PostgreSQL via asyncpg is the primary/production target; ORM models under app/entities
    # use only generic SQLAlchemy column types so the same models also run unmodified
    # against SQLite (sqlite+aiosqlite), which is what the test-suite uses.
    DATABASE_URL: str = "postgresql+asyncpg://emios:emios_secure_password@localhost:5432/emios"

    # Auth (JWT). JWT_SECRET_KEY has a dev default here - override via env/.env in
    # any real deployment.
    JWT_SECRET_KEY: str = "emios-dev-secret-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # "production" makes the auth cookie Secure (HTTPS-only, per browser spec a
    # non-HTTPS response can't even set it) - stays "development" for local
    # HTTP work against localhost. Override via env/.env in any real deployment.
    ENVIRONMENT: str = "development"

    # Both real deployment paths (Vite's dev proxy, and main.py serving
    # frontend/dist from the same FastAPI process in prod) are same-origin from
    # the browser's perspective, so this only matters for direct cross-origin
    # tooling - kept as an explicit list (not "*") since allow_credentials=True
    # requires one per the CORS spec (see main.py).
    CORS_ALLOWED_ORIGINS: list[str] = ["http://localhost:5173"]

    # LLM Settings
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None

    AZURE_OPENAI_API_KEY: Optional[str] = None
    AZURE_OPENAI_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_DEPLOYMENT: Optional[str] = "gpt-4o"
    AZURE_OPENAI_API_VERSION: Optional[str] = "2024-05-01-preview"

    # Model IDs, centralized here rather than hardcoded at each provider class in
    # app/core/llm_provider.py / app/core/embeddings.py - change the model for a
    # provider by editing .env, not code.
    OPENAI_MODEL: str = "gpt-4o"
    GEMINI_MODEL: str = "gemini-1.5-flash"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # AWS Bedrock (preferred LLM + embeddings provider - see app/core/llm_provider.py).
    # AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY are optional and meant for local/dev
    # convenience only (via backend/.env, never committed - see .gitignore) - in any
    # real deployment, prefer an IAM role attached to the instance instead and leave
    # these two blank; app.core.config.get_boto3_client() falls back to boto3's normal
    # credential chain (~/.aws/credentials, or an attached IAM role) when unset.
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[SecretStr] = None
    # Some newer models (e.g. Claude) need a cross-region inference profile ID
    # (the "us." prefix) instead of the bare model ID - Bedrock rejects
    # on-demand invocation by bare ID for those with "Retry your request with
    # the ID or ARN of an inference profile that contains this model."
    # Confirmed which models this account actually has entitlement to invoke
    # (listed != invokable - Bedrock's catalog lists far more models than an
    # account is granted access to) by calling converse() directly for each
    # candidate.
    #
    # Switched away from Claude (2026-07-31): every Claude tier (Opus 4.5/4.6,
    # Sonnet 4.5/4.6, Haiku 4.5) started returning ThrottlingException "Too
    # many tokens per day" - a shared daily token quota for Anthropic models
    # on this account, exhausted by heavy same-day testing, not a permissions
    # change (compare app/agents/MASTER_ORCHESTRATOR.md's history, where these
    # same models worked earlier the same day). Rather than wait out the daily
    # reset, benchmarked non-Anthropic alternatives directly against this
    # project's actual formatting prompt (app/agents/prompts.py's
    # "FORMATTING RULE") - qwen.qwen3-coder-next produced clean, correctly-
    # formatted Markdown (real tables, bold, explanatory prose, no backend
    # cleanup needed) in ~2s per call vs. Claude's 15-25s+, which - multiplied
    # across the 12-agent Wave Planner pipeline's sequential real LLM calls
    # (see app/agents/workflow.py's run_full_assessment_stream) - is also a
    # large chunk of why that pipeline took 4-5 minutes end to end. No "us."
    # prefix needed for this one. If Claude access is wanted again later once
    # the daily quota resets, "us.anthropic.claude-sonnet-4-6" was the
    # confirmed-working Claude tier as of the same date.
    BEDROCK_LLM_MODEL_ID: str = "qwen.qwen3-coder-next"
    # 512 was tuned for the pipeline agents' compact JSON responses; the Document
    # Discovery BRD/HLD extractor (app/services_v1/extraction/llm_prompt_extractor.py)
    # asks for a JSON array of systems+dependencies+descriptions, which for a
    # document naming more than a handful of systems can get truncated mid-JSON
    # at 512 tokens - observed directly: a 6-system BRD fit narrowly, a similarly
    # sized HLD didn't and silently produced zero extracted nodes. Raised again
    # 2026-07-31 (2048 -> 4096) when prompts.py's per-agent "agent_log" guidance
    # was changed from an explicit 3-5-sentence cap to "cover every material
    # finding in genuine depth" - a properly detailed multi-paragraph narrative
    # plus the surrounding structured JSON fields can legitimately exceed 2048
    # tokens, and unlike the terse version, silent truncation here would cut off
    # readable prose mid-sentence rather than just an empty list.
    BEDROCK_MAX_TOKENS: int = 4096
    BEDROCK_EMBEDDING_MODEL_ID: str = "amazon.titan-embed-text-v2:0"
    BEDROCK_EMBEDDING_DIMENSIONS: int = 1024

    # Amazon S3 (document storage - see app/core/storage.py). Falls back to local disk
    # under LOCAL_STORAGE_DIR if S3/credentials aren't reachable, same "degrade
    # gracefully" pattern as Neo4j/Qdrant below.
    S3_BUCKET_NAME: str = "emios-documents"
    LOCAL_STORAGE_DIR: str = "./storage_fallback"
    # Upload size cap (app/api/v1/uploads.py) - guards against a single request
    # buffering an unbounded file fully into memory before any check runs.
    MAX_UPLOAD_SIZE_BYTES: int = 25 * 1024 * 1024  # 25MB

    # Zip archive upload (app/api/v1/uploads.py's /uploads/zip, app/services_v1/
    # upload_service.py). The archive itself may legitimately be larger than a
    # single document, but total extracted content and member count are still
    # capped so a crafted/zip-bomb archive can't exhaust memory or spawn
    # thousands of processing jobs from one request.
    MAX_ZIP_UPLOAD_SIZE_BYTES: int = 100 * 1024 * 1024  # 100MB, compressed
    MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES: int = 250 * 1024 * 1024  # 250MB, extracted
    MAX_ZIP_MEMBERS: int = 200

    # Entity resolution (app/services_v1/extraction/entity_resolution.py): a
    # cross-document node whose name-embedding cosine similarity to another
    # node is at/above this is worth asking the LLM reconciliation pass about.
    # This is a RECALL knob only, not a merge decision - actual merges always
    # require an explicit LLM confirmation, so a value that's "too low" just
    # costs a slightly larger (still single, batched) reconciliation prompt,
    # never a wrong autonomous merge. Similarity is inherently relative to
    # whichever embedding provider is active (Bedrock Titan v2, OpenAI, or the
    # local deterministic fallback all have differently-scaled/shaped vector
    # spaces) - this default was set generously low from empirical Titan v2
    # measurements specifically so it stays a safe (if noisier) net if the
    # active provider changes; retune per-provider if reconciliation prompts
    # are consistently too large or too small to be useful.
    ENTITY_RESOLUTION_CANDIDATE_SIMILARITY_FLOOR: float = 0.5

    # Qdrant collection used for document-chunk embeddings (RAG retrieval).
    QDRANT_COLLECTION_NAME: str = "emios_document_chunks"

    # Langfuse Observability Settings (Self-Hosted / Cloud)
    LANGFUSE_PUBLIC_KEY: Optional[str] = "pk-lf-emios-local"
    LANGFUSE_SECRET_KEY: Optional[str] = "sk-lf-emios-local"
    LANGFUSE_HOST: str = "http://localhost:3000"  # Self-Hosted Langfuse Server or https://cloud.langfuse.com
    ENABLE_LANGFUSE_TRACING: bool = True

    # Multi-Agent Settings
    MANDATORY_LLM_CALLS: bool = True
    LLM_TEMPERATURE: float = 0.2
    MAX_SIMULATION_RUNS: int = 1000
    # Applied to the Gemini/OpenAI/Azure OpenAI LangChain clients - matches
    # BedrockProvider's own explicit 30s read timeout (see llm_provider.py) so a
    # hung request to any provider can't block a pipeline run indefinitely.
    LLM_REQUEST_TIMEOUT_SECONDS: int = 30

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()


def get_boto3_client(service_name: str, read_timeout: int = 8):
    """Constructs a boto3 client for `service_name`, honoring explicit
    AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY from Settings if set (local/dev
    convenience), falling back to boto3's own default credential chain
    (~/.aws/credentials, or an attached IAM role) otherwise. Centralizes this
    so app/core/llm_provider.py, app/core/embeddings.py, and app/core/storage.py
    don't each duplicate the same credential-kwargs logic.

    Uses a short connect timeout and a single attempt (no retries) always:
    boto3's defaults (60s connect, multiple retries) mean that on a box with
    no route to AWS - or a Bedrock model/region that isn't actually enabled -
    every LLM call in app/agents/workflow.py silently hangs for minutes instead
    of falling through to the next configured provider (or the deterministic
    fallback) quickly, as every other provider already does.

    `read_timeout` defaults to a fast-fail 8s, appropriate for the cheap
    connectivity-check calls this centralizes (S3 head_bucket, Bedrock
    list_foundation_models). Callers doing actual LLM text generation (e.g.
    BedrockProvider's `bedrock-runtime` client) should pass a larger value -
    generating a full JSON response can legitimately take longer than 8s, and
    at 8s that read timeout was observed cutting off real in-flight Bedrock
    Document Extraction Agent calls, which invoke_with_fallback() then
    silently treated the same as "no provider configured" (see
    app/services_v1/extraction/llm_prompt_extractor.py's "LLM extraction
    unavailable" warning - misleading when a provider *is* configured and
    just needed more time).
    """
    import boto3
    from botocore.config import Config

    kwargs: dict = {
        "region_name": settings.AWS_REGION,
        "config": Config(connect_timeout=3, read_timeout=read_timeout, retries={"max_attempts": 1}),
    }
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY.get_secret_value()
    return boto3.client(service_name, **kwargs)
