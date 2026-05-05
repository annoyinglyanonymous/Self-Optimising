from pydantic_settings import BaseSettings #Pydantic Settings is a library that reads values from your .env file and converts them into Python types automatically.

class Settings(BaseSettings):
    DATABASE_URL:str
    OPENAI_API_KEY :str
    APP_ENV:str
    MAX_BOUNCE_RATE: float=0.03
    MAX_SPAM_RATE: float=0.001
    MIN_BANDIT_TRIALS: int=50
    EXPLORATION_RATE:float=0.12
    SCHEDULER_ENABLED: bool=False
    SCHEDULER_INTERVAL_MINUTES: int=10
    SCHEDULER_BATCH_SIZE: int=10
    AUTH_REQUIRED: bool=False
    JWT_SECRET: str=""
    JWT_EXPIRES_HOURS: int=24
    ENCRYPTION_KEY: str=""
    SENDER_BACKEND: str="stub"  # "stub" | "gmail" | "instantly"
    GMAIL_USERNAME: str=""
    GMAIL_APP_PASSWORD: str=""
    GMAIL_FROM_ADDRESS: str=""
    GMAIL_FROM_NAME: str=""
    INSTANTLY_API_KEY: str=""
    INSTANTLY_API_BASE_URL: str="https://api.instantly.ai/api/v2"
    INSTANTLY_DEFAULT_CAMPAIGN_ID: str=""
    INSTANTLY_CAMPAIGN_MAP: dict[str, str] = {}
    class Config:
        env_file =".env"

settings=Settings()