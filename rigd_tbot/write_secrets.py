# write_secrets.py
# Minimal standalone test to verify encryption and decryption of screener_api.json.enc

from tbot_bot.support.secrets_manager import save_screener_credentials, load_screener_credentials

test_creds = {
    "PROVIDER_01": "TESTPROV",
    "SCREENER_NAME_01": "Dummy",
    "SCREENER_USERNAME_01": "testuser",
    "SCREENER_PASSWORD_01": "testpw",
    "SCREENER_URL_01": "http://example.com",
    "SCREENER_API_KEY_01": "testapikey",
    "SCREENER_TOKEN_01": "testtoken"
}

print("Saving test credentials...")
save_screener_credentials(test_creds)

print("Reading back credentials...")
loaded = load_screener_credentials()
print(loaded)
