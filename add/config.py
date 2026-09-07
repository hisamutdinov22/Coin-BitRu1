from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    bot_token: str
    payment_provider_token: str = ""
    admin_ids: str = ""
    channel_username: str = "@Coin_BitRu"
    channel_url: str = "https://t.me/Coin_BitRu"
    database_url: str = "sqlite+aiosqlite:///./data/coin_bitru.db"
    web_host: str = "0.0.0.0"
    web_port: int = 8080

    @property
    def effective_web_port(self) -> int:
        return int(os.getenv('PORT', str(self.web_port)))
    webhook_secret: str = "change-me"
    enable_stars: bool = False
    referral_reward_coins: int = 5000
    referral_5_bonus_usd: int = 5
    coins_per_usd: int = 100000
    withdraw_topup_min_usd: int = 2
    withdraw_min_usd: int = 1
    tournament_prize_usd: int = 100
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def admin_set(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_ids.split(",") if x.strip().isdigit()}

settings = Settings()
