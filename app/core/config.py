from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str

    # Authentication
    SECRET_KEY: str
    HASH_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    # mqtt credential for mobile app
    MQTT_BROKER: str
    MQTT_PUB_USERNAME: str
    MQTT_PUB_PASSWORD: str


settings = Settings()
