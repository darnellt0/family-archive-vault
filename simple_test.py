import sys
print("Python:", sys.version.split()[0])
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    print("Libraries: OK")
except:
    print("Libraries: MISSING")
    sys.exit(1)
print("Test complete")
