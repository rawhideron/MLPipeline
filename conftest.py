import os
import sys
from pathlib import Path

# Allow `from inference_handler import ...` bare imports in serving/app.py
# to resolve when pytest imports it as `serving.app` from the repo root.
sys.path.insert(0, str(Path(__file__).parent / "serving"))

# serving/oauth_middleware.py fetches the Keycloak JWKS at import time. Point it
# at a closed local port so tests never contact the real Keycloak.
os.environ.setdefault("KEYCLOAK_REALM_URL", "http://127.0.0.1:9/realms/test")
