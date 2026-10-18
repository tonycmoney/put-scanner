from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.strategy.rules import Rules


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./scanner.db"

    # Webull OpenAPI credentials. The scanner does not run until both are set.
    webull_app_key: str | None = None
    webull_app_secret: str | None = None
    webull_env: str = "sandbox"  # sandbox | production
    webull_host: str | None = None  # override the API host if needed

    # Optional: Discord or Slack incoming webhook for new pick alerts.
    alert_webhook_url: str | None = None

    scheduler_enabled: bool = True
    timezone: str = "America/New_York"
    scan_times: str = "10:00,11:00,12:00,13:00,14:00,15:00,15:55"
    grade_time: str = "16:15"
    manual_scan_cooldown_s: int = 300

    budget: float = 5000.0
    max_loss_pct: float = 0.05

    @property
    def webull_configured(self) -> bool:
        return bool(self.webull_app_key and self.webull_app_secret)

    def rules(self) -> Rules:
        return Rules(budget=self.budget, max_loss_pct=self.max_loss_pct)


@lru_cache
def get_settings() -> Settings:
    return Settings()
