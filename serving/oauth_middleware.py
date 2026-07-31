"""Keycloak OAuth2 middleware for FastAPI."""

import json
import logging
import os

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

security = HTTPBearer()


class KeycloakOAuth:
    """Keycloak OAuth2 integration."""

    def __init__(
        self,
        realm_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        """
        Initialize Keycloak OAuth client.

        Args:
            realm_url: Keycloak realm URL (from env var KEYCLOAK_REALM_URL)
            client_id: OAuth client ID (from env var OAUTH_CLIENT_ID)
            client_secret: OAuth client secret (from env var OAUTH_CLIENT_SECRET)
        """
        self.realm_url = realm_url or os.getenv(
            "KEYCLOAK_REALM_URL",
            "https://goodmanreunion.duckdns.org/keycloak/realms/MLPipeline",
        )
        self.client_id = client_id or os.getenv("OAUTH_CLIENT_ID", "mlpipeline-serving")
        self.client_secret = client_secret or os.getenv("OAUTH_CLIENT_SECRET")

        # Keycloak endpoints
        self.oidc_endpoint = f"{self.realm_url}/.well-known/openid-configuration"
        self.jwks_uri = f"{self.realm_url}/protocol/openid-connect/certs"

        self.public_key = None
        self._fetch_public_key()

    def _fetch_public_key(self, kid: str | None = None):
        """Fetch and cache Keycloak public key, matching by kid when provided."""
        try:
            with httpx.Client() as client:
                response = client.get(self.jwks_uri)
                response.raise_for_status()
                jwks = response.json()
                keys = jwks.get("keys", [])
                if not keys:
                    logger.error("JWKS response contained no keys")
                    return
                if kid:
                    matched = [k for k in keys if k.get("kid") == kid]
                    key_data = matched[0] if matched else keys[0]
                else:
                    key_data = keys[0]
                self.public_key = jwt.algorithms.RSAAlgorithm.from_jwk(
                    json.dumps(key_data)
                )
                logger.info(
                    "Successfully fetched Keycloak public key (kid=%s)",
                    key_data.get("kid"),
                )
        except Exception as e:  # noqa: BLE001 -- log and continue with no cached key
            logger.error("Failed to fetch Keycloak public key: %s", e)

    def verify_token(self, token: str) -> dict:
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
                kid = jwt.get_unverified_header(token).get("kid")
                self._fetch_public_key(kid=kid)

            payload = jwt.decode(
                token,
                self.public_key,
                algorithms=["RS256"],
                audience=self.client_id,
                options={"verify_signature": True},
            )

            logger.info(
                "Token verified for user: %s", payload.get("preferred_username")
            )
            return payload

        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired"
            )
        except jwt.InvalidTokenError as e:
            logger.warning("Invalid token: %s", e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            )
        except Exception as e:  # noqa: BLE001 -- any other verification failure is unauthorized
            logger.error("Token verification error: %s", e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
            )


# Initialize OAuth handler
keycloak_oauth = KeycloakOAuth()


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),  # noqa: B008 -- required FastAPI DI pattern
) -> dict:
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
    # Test OAuth initialization
    oauth = KeycloakOAuth()
    logger.info("Keycloak realm URL: %s", oauth.realm_url)
    logger.info("Client ID: %s", oauth.client_id)
    logger.info("OAuth middleware initialized successfully")
