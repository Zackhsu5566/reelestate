from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Anthropic (or compatible API via base_url)
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # WaveSpeed
    wavespeed_api_key: str = ""
    wavespeed_base_url: str = "https://api.wavespeed.ai/api/v3"
    wavespeed_poll_interval: float = 3.0
    wavespeed_poll_timeout: float = 300.0

    # Remotion Render
    render_url: str = "https://render.replowapp.com"
    render_token: str = "reelestate-render-token-2024"
    render_poll_interval: float = 5.0
    render_poll_timeout: float = 600.0

    # R2
    r2_proxy_url: str = "https://reelestate-r2-proxy.beingzackhsu.workers.dev"
    r2_upload_token: str = "reelestate-r2-proxy-token-2024"
    r2_cdn_url: str = "https://assets.replowapp.com"

    # Map API Keys (OpeningScene)
    mapbox_token: str = ""

    # Telegram
    telegram_bot_token: str = ""

    # General
    max_retries: int = 3

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
