from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    jwt_secret: str = "change-me-jwt"
    qr_secret: str = "change-me-qr"
    data_key: str = ""  # khóa Fernet (32 byte base64 url-safe); để trống = dẫn xuất từ jwt_secret (chỉ dev)
    jwt_expire_minutes: int = 60 * 8
    session_ttl_minutes: int = 60 * 4
    cors_origins: str = "http://localhost:5173"
    public_url: str = "http://localhost:5173"  # URL công khai của web (gồm tiền tố /booking khi chạy dưới IIS)

    # SePay / VietQR
    sepay_api_key: str = "dev-sepay-key"
    bank_code: str = "MBBank"
    bank_account: str = "0000000000"

    hold_minutes: int = 15


settings = Settings()
