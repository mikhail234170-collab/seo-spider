from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SITE_LENS_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = Path("./data")
    default_max_urls: int = 500
    default_rate_per_sec: float = 2.0
    render_timeout_ms: int = 15000

    @property
    def db_path(self) -> Path:
        return self.data_dir / "site_lens.db"

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
