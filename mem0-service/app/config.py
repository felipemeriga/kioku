from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str  # postgresql://.../postgres
    service_token: str  # shared bearer with kioku
    mem0_schema: str = "mem0"
    embedder_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedder_dims: int = 384
    port: int = 8010

    model_config = SettingsConfigDict(env_prefix="MEM0_", extra="ignore")


settings = Settings()  # reads MEM0_DATABASE_URL, MEM0_SERVICE_TOKEN, ...
