"""Pydantic schemas for system config API."""

from pydantic import BaseModel


class OllamaLlmConfig(BaseModel):
    server_url: str = "http://10.165.25.39:11434"
    model_name: str = ""
    context_length: int | None = None
    context_length_manual: bool = False
    temperature: float = 0.1
    max_output_tokens: int = 8192
    retry: int = 3
    timeout: int = 600


class OllamaEmbeddingConfig(BaseModel):
    server_url: str = "http://10.165.44.28:11434"
    model_name: str = ""
    context_length: int | None = None
    context_length_manual: bool = False
    dimensions: int | None = None
    dimensions_manual: bool = False
    batch_size: int | None = None


class OllamaHahaCodeConfig(BaseModel):
    anthropic_base_url: str = ""
    anthropic_model: str = ""
    anthropic_sonnet_model: str = ""
    anthropic_haiku_model: str = ""
    anthropic_auth_token: str = "ollama"


class CloudConfig(BaseModel):
    api: dict = {}
    embedding: dict = {}
    haha_code: dict = {}


class SystemConfigUpdate(BaseModel):
    mode: str  # "cloud" | "local"
    cloud_config: CloudConfig | None = None
    local_llm_config: OllamaLlmConfig | None = None
    local_embedding_config: OllamaEmbeddingConfig | None = None
    local_haha_code_config: OllamaHahaCodeConfig | None = None


class SystemConfigResponse(BaseModel):
    mode: str
    cloud_config: CloudConfig
    local_llm_config: OllamaLlmConfig | None
    local_embedding_config: OllamaEmbeddingConfig | None
    local_haha_code_config: OllamaHahaCodeConfig | None
    updated_at: str | None
    updated_by: int | None


class OllamaModelInfo(BaseModel):
    name: str
    context_length: int | None = None
    dimensions: int | None = None


class OllamaConnectionTest(BaseModel):
    server_url: str
    model_name: str | None = None