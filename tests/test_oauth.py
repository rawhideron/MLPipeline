"""Unit tests for Keycloak OAuth middleware."""

import json
from unittest.mock import MagicMock, patch

import pytest


def _make_rsa_jwk(kid: str = "key1") -> dict:
    """Return a minimal RSA JWK for mocking (not a real key)."""
    return {
        "kid": kid,
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "n": "sIm7p1",
        "e": "AQAB",
    }


def _make_jwks_response(keys: list) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"keys": keys}
    mock_resp.raise_for_status.return_value = None
    return mock_resp


class TestKeycloakOAuthInit:
    """Test KeycloakOAuth initialization."""

    @patch("serving.oauth_middleware.KeycloakOAuth._fetch_public_key")
    def test_reads_env_vars(self, mock_fetch, monkeypatch):
        monkeypatch.setenv("KEYCLOAK_REALM_URL", "https://kc.example.com/realms/test")
        monkeypatch.setenv("OAUTH_CLIENT_ID", "my-client")
        monkeypatch.setenv("OAUTH_CLIENT_SECRET", "s3cr3t")

        from serving.oauth_middleware import KeycloakOAuth

        oauth = KeycloakOAuth()
        assert oauth.realm_url == "https://kc.example.com/realms/test"
        assert oauth.client_id == "my-client"
        assert oauth.client_secret == "s3cr3t"

    @patch("serving.oauth_middleware.KeycloakOAuth._fetch_public_key")
    def test_constructor_args_take_priority(self, mock_fetch):
        from serving.oauth_middleware import KeycloakOAuth

        oauth = KeycloakOAuth(
            realm_url="https://explicit.example.com/realms/r",
            client_id="explicit-client",
            client_secret="explicit-secret",
        )
        assert oauth.realm_url == "https://explicit.example.com/realms/r"
        assert oauth.client_id == "explicit-client"

    @patch("serving.oauth_middleware.KeycloakOAuth._fetch_public_key")
    def test_jwks_uri_derived_from_realm_url(self, mock_fetch):
        from serving.oauth_middleware import KeycloakOAuth

        oauth = KeycloakOAuth(realm_url="https://kc.example.com/realms/r")
        assert (
            oauth.jwks_uri
            == "https://kc.example.com/realms/r/protocol/openid-connect/certs"
        )


class TestFetchPublicKey:
    """Test _fetch_public_key JWKS handling."""

    def _make_oauth(self):
        with patch("serving.oauth_middleware.KeycloakOAuth._fetch_public_key"):
            from serving.oauth_middleware import KeycloakOAuth

            return KeycloakOAuth(realm_url="https://kc.example.com/realms/r")

    def test_selects_matching_kid(self):
        oauth = self._make_oauth()
        key1 = _make_rsa_jwk("key1")
        key2 = _make_rsa_jwk("key2")

        mock_http_client = MagicMock()
        mock_http_client.__enter__.return_value.get.return_value = _make_jwks_response(
            [key1, key2]
        )

        captured = {}

        def fake_from_jwk(key_json):
            captured["key"] = json.loads(key_json)
            return MagicMock()

        with (
            patch("httpx.Client", return_value=mock_http_client),
            patch(
                "serving.oauth_middleware.jwt.algorithms.RSAAlgorithm", create=True
            ) as mock_rsa,
        ):
            mock_rsa.from_jwk.side_effect = fake_from_jwk
            oauth._fetch_public_key(kid="key2")

        assert captured["key"]["kid"] == "key2"

    def test_falls_back_to_first_key_when_kid_not_found(self):
        oauth = self._make_oauth()

        mock_http_client = MagicMock()
        mock_http_client.__enter__.return_value.get.return_value = _make_jwks_response(
            [_make_rsa_jwk("key1")]
        )

        captured = {}

        def fake_from_jwk(key_json):
            captured["key"] = json.loads(key_json)
            return MagicMock()

        with (
            patch("httpx.Client", return_value=mock_http_client),
            patch(
                "serving.oauth_middleware.jwt.algorithms.RSAAlgorithm", create=True
            ) as mock_rsa,
        ):
            mock_rsa.from_jwk.side_effect = fake_from_jwk
            oauth._fetch_public_key(kid="unknown-kid")

        assert captured["key"]["kid"] == "key1"

    def test_empty_keys_logs_error_and_returns(self):
        oauth = self._make_oauth()

        mock_http_client = MagicMock()
        mock_http_client.__enter__.return_value.get.return_value = _make_jwks_response(
            []
        )

        with patch("httpx.Client", return_value=mock_http_client):
            oauth._fetch_public_key()

        assert oauth.public_key is None

    def test_http_error_logs_and_does_not_raise(self):
        oauth = self._make_oauth()

        mock_http_client = MagicMock()
        mock_http_client.__enter__.return_value.get.side_effect = Exception(
            "connection refused"
        )

        with patch("httpx.Client", return_value=mock_http_client):
            oauth._fetch_public_key()

        assert oauth.public_key is None


class TestVerifyToken:
    """Test JWT token verification."""

    def _make_oauth_with_key(self):
        with patch("serving.oauth_middleware.KeycloakOAuth._fetch_public_key"):
            from serving.oauth_middleware import KeycloakOAuth

            oauth = KeycloakOAuth(
                realm_url="https://kc.example.com/realms/r",
                client_id="test-client",
            )
            oauth.public_key = MagicMock()
            return oauth

    def test_returns_payload_on_valid_token(self):

        oauth = self._make_oauth_with_key()
        expected_payload = {
            "sub": "user1",
            "preferred_username": "alice",
            "aud": "test-client",
        }

        with patch("jwt.decode", return_value=expected_payload):
            payload = oauth.verify_token("valid.token.here")

        assert payload["sub"] == "user1"

    def test_raises_401_on_expired_token(self):
        import jwt as pyjwt
        from fastapi import HTTPException

        oauth = self._make_oauth_with_key()

        with patch("jwt.decode", side_effect=pyjwt.ExpiredSignatureError):
            with pytest.raises(HTTPException) as exc_info:
                oauth.verify_token("expired.token")

        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_raises_401_on_invalid_token(self):
        import jwt as pyjwt
        from fastapi import HTTPException

        oauth = self._make_oauth_with_key()

        with patch("jwt.decode", side_effect=pyjwt.InvalidTokenError("bad sig")):
            with pytest.raises(HTTPException) as exc_info:
                oauth.verify_token("invalid.token")

        assert exc_info.value.status_code == 401

    def test_raises_401_on_unexpected_error(self):
        from fastapi import HTTPException

        oauth = self._make_oauth_with_key()

        with patch("jwt.decode", side_effect=RuntimeError("unexpected")):
            with pytest.raises(HTTPException) as exc_info:
                oauth.verify_token("some.token")

        assert exc_info.value.status_code == 401

    def test_fetches_key_by_kid_when_key_absent(self):

        with patch("serving.oauth_middleware.KeycloakOAuth._fetch_public_key"):
            from serving.oauth_middleware import KeycloakOAuth

            oauth = KeycloakOAuth(realm_url="https://kc.example.com/realms/r")
            oauth.public_key = None

        expected_payload = {"sub": "u1", "preferred_username": "bob"}

        with (
            patch(
                "jwt.get_unverified_header",
                return_value={"kid": "key99", "alg": "RS256"},
            ),
            patch.object(oauth, "_fetch_public_key"),
            patch("jwt.decode", return_value=expected_payload),
        ):
            oauth.public_key = MagicMock()
            payload = oauth.verify_token("some.token")

        assert payload["sub"] == "u1"
