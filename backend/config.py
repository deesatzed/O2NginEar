# backend/config.py
import os

# In a real application, these would be loaded from environment variables or a secure config service
# For this subtask, we'll use placeholder values.
# IMPORTANT: These are NOT real credentials.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "YOUR_GOOGLE_CLIENT_ID_HERE")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "YOUR_GOOGLE_CLIENT_SECRET_HERE")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/callback/google") # Ensure this matches GCP setup

# This is the file that would be downloaded from GCP containing client secrets
# For this subtask, we acknowledge its importance but won't create/use a real one.
# In a real app, you'd typically point google-auth-oauthlib to the path of this JSON file.
# For server-side apps, you often just need client_id, client_secret, and redirect_uris.
# CLIENT_SECRETS_FILE = "client_secret.json" # Placeholder

SCOPES = [
    'https://www.googleapis.com/auth/drive.metadata.readonly',
    'https://www.googleapis.com/auth/drive.file', # More comprehensive scope for r/w
]
