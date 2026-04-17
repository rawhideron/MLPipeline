"""Keycloak OAuth2 middleware for FastAPI."""

import json
import logging
from typing import Dict
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import httpx

logger = logging.getLogger(__name__)

security = HTTPBearer()


class KeycloakOAuth:
    """Keycloak OAuth2 integration."""

    def __init__(
        self,
        realm_url: str = None,
        client_id: str = None,
        client_secret: str = None,
    ):
        """
        Initialize Keycloak OAuth client.

        Args:
            realm_url: Keycloak realm URL (from env var KEYCLOAK_REALM_URL)
            client_id: OAuth client ID (from env var OAUTH_CLIENT_ID)
            client_secret: OAuth client secret (from env var OAUTH_CLIENT_SECRET)
        """
        self.realm_url = realm_url or os.getenv(
            "KEYCLOAK_REALM_URL", "http://keycloak:8080/realms/MLPipeline"
        )
        self.client_id = client_id or os.getenv("OAUTH_CLIENT_ID", "mlpipeline-serving")
        self.client_secret = client_secret or os.getenv("OAUTH_CLIENT_SECRET")

        # Keycloak endpoints
        self.oidc_endpoint = f"{self.realm_url}/.well-known/openid-configuration"
        self.jwks_uri = f"{self.realm_url}/protocol/openid-connect/certs"

        self.public_key = None
        self._fetch_public_key()

    def _fetch_public_key(self):
        """Fetch and cache Keycloak public key."""
        try:
            with httpx.Client() as client:
                response = client.get(self.jwks_uri)
                response.raise_for_status()
                jwks = response.json()
                # For simplicity, use first key (in production, match by kid)
                if jwks.get("keys"):
                    key_data = jwks["keys"][0]
                    self.public_key = jwt.algorithms.RSAAlgorithm.from_jwk(
                        json.dumps(key_data)
                    )
                    logger.info("Successfully fetched Keycloak public key")
        except Exception as e:
            logger.error(f"Failed to fetch Keycloak public key: {str(e)}")

    def verify_token(self, token: str) -> Dict:
        """
        Verify and decode JWT token from Keycloak.

        Args:
            token: JWT token from Authorization header

        Returns:
            Decoded token payload

        Raises:
            HTTPException if token is invalid
        """
        try:
            if not self.public_key:
                self._fetch_public_key()

            payload = jwt.decode(
                token,
                self.public_key,
                algorithms=["RS256"],
                audience=self.client_id,
                options={"verify_signature": True},
            )

            logger.info(f"Token verified for user: {payload.get('preferred_username')}")
            return payload

        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired"
            )
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            )
        except Exception as e:
            logger.error(f"Token verification error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
            )


# Initialize OAuth handler
keycloak_oauth = KeycloakOAuth()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict:
    """
    Dependency for FastAPI endpoints requiring authentication.

    Usage:
        @app.get("/protected")
        async def protected_endpoint(token: dict = Depends(verify_token)):
            return {"user": token.get("preferred_username")}
    """
    token = credentials.credentials
    return keycloak_oauth.verify_token(token)


if __name__ == "__main__":
    import json

    # Test OAuth initialization
    oauth = KeycloakOAuth()
    print(f"Keycloak realm URL: {oauth.realm_url}")
    print(f"Client ID: {oauth.client_id}")
    print("OAuth middleware initialized successfully")
