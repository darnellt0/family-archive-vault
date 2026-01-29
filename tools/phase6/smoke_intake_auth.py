import os

json_env = os.getenv("SERVICE_ACCOUNT_JSON")
json_path = os.getenv("SERVICE_ACCOUNT_JSON_PATH")

if json_env:
    print("Auth mode: SERVICE_ACCOUNT_JSON")
elif json_path:
    print("Auth mode: SERVICE_ACCOUNT_JSON_PATH")
else:
    print("ERROR: missing service account credentials")
