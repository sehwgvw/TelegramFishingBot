import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8538101699:AAE_zPwy8Zgl8BSJcceWvSFooSsPGyJvZ3U")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7544069555"))

API_CREDENTIALS = [
    {
        "api_id": int(os.getenv("API_ID", "32114806")),
        "api_hash": os.getenv("API_HASH", "16ece23e5b4033a9aa9a307d1d508be4")
    }
]

REFERRAL_BONUS = 50
