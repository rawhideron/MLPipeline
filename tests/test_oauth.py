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
    def test_constructor_args_take_priority(self, mock_fetch, monkeypatch):
        monkeypatch.setenv("KEYCLOAK_REALM_URL", "https://env.example.com/realms/e")
        monkeypatch.setenv("OAUTH_CLIENT_ID", "env-client")
        monkeypatch.setenv("OAUTH_CLIENT_SECRET", "env-secret")

        from serving.oauth_middleware import KeycloakOAuth

        oauth = KeycloakOAuth(
            realm_url="https://explicit.example.com/realms/r",
            client_id="explicit-client",
            client_secret="explicit-secret",
        )
        assert oauth.realm_url == "https://explicit.example.com/realms/r"
        assert oauth.client_id == "explicit-client"
        assert oauth.client_secret == "explicit-secret"

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

        parsed_key = MagicMock()

        def fake_from_jwk(key_json):
            captured["key"] = json.loads(key_json)
            return parsed_key

        with (
            patch("httpx.Client", return_value=mock_http_client),
            patch(
                "serving.oauth_middleware.jwt.algorithms.RSAAlgorithm", create=True
            ) as mock_rsa,
        ):
            mock_rsa.from_jwk.side_effect = fake_from_jwk
            oauth._fetch_public_key(kid="key2")

        assert captured["key"]["kid"] == "key2"
        assert oauth.public_key is parsed_key

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

    def test_empty_keys_logs_error_and_keeps_cached_key(self, caplog):
        oauth = self._make_oauth()
        cached_key = MagicMock()
        oauth.public_key = cached_key

        mock_http_client = MagicMock()
        mock_http_client.__enter__.return_value.get.return_value = _make_jwks_response(
            []
        )

        with patch("httpx.Client", return_value=mock_http_client):
            oauth._fetch_public_key()

        assert oauth.public_key is cached_key
        assert "no keys" in caplog.text

    def test_http_error_logs_and_keeps_cached_key(self, caplog):
        oauth = self._make_oauth()
        cached_key = MagicMock()
        oauth.public_key = cached_key

        mock_http_client = MagicMock()
        mock_http_client.__enter__.return_value.get.side_effect = Exception(
            "connection refused"
        )

        with patch("httpx.Client", return_value=mock_http_client):
            oauth._fetch_public_key()

        assert oauth.public_key is cached_key
        assert "connection refused" in caplog.text

    def test_no_kid_uses_first_key(self):
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
            oauth._fetch_public_key()  # no kid — hits the else branch

        assert captured["key"]["kid"] == "key1"


@pytest.fixture(scope="module")
def signing_key():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_signing_key():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _make_token(key, algorithm="RS256", headers=None, **claim_overrides) -> str:
    """Sign a real JWT; pass a claim as None to omit it."""
    import time

    import jwt as pyjwt

    claims = {
        "sub": "user1",
        "preferred_username": "alice",
        "aud": "test-client",
        "exp": int(time.time()) + 300,
    }
    claims.update(claim_overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return pyjwt.encode(claims, key, algorithm=algorithm, headers=headers)


class TestVerifyToken:
    """Verify real signed tokens against the configured public key.

    jwt.decode is deliberately not mocked: these tests pin the signature,
    algorithm, audience and expiry checks that protect every endpoint.
    """

    @pytest.fixture
    def oauth(self, signing_key):
        with patch("serving.oauth_middleware.KeycloakOAuth._fetch_public_key"):
            from serving.oauth_middleware import KeycloakOAuth

            oauth = KeycloakOAuth(
                realm_url="https://kc.example.com/realms/r",
                client_id="test-client",
            )
        oauth.public_key = signing_key.public_key()
        return oauth

    def _assert_rejected(self, oauth, token) -> str:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            oauth.verify_token(token)
        assert exc_info.value.status_code == 401
        return exc_info.value.detail

    def test_accepts_valid_token(self, oauth, signing_key):
        payload = oauth.verify_token(_make_token(signing_key))

        assert payload["sub"] == "user1"
        assert payload["preferred_username"] == "alice"

    def test_rejects_expired_token(self, oauth, signing_key):
        import time

        token = _make_token(signing_key, exp=int(time.time()) - 60)

        assert "expired" in self._assert_rejected(oauth, token).lower()

    def test_rejects_token_signed_with_other_key(self, oauth, other_signing_key):
        self._assert_rejected(oauth, _make_token(other_signing_key))

    @pytest.mark.parametrize("aud", ["other-client", None])
    def test_rejects_wrong_or_missing_audience(self, oauth, signing_key, aud):
        self._assert_rejected(oauth, _make_token(signing_key, aud=aud))

    def test_rejects_hs256_token(self, oauth):
        token = _make_token("a-shared-secret-of-at-least-32-bytes!", algorithm="HS256")

        self._assert_rejected(oauth, token)

    def test_rejects_unsigned_alg_none_token(self, oauth):
        self._assert_rejected(oauth, _make_token(None, algorithm="none"))

    def test_rejects_malformed_token(self, oauth):
        assert self._assert_rejected(oauth, "not-a-jwt") == "Invalid token"

    def test_only_rs256_is_allowed(self, oauth, signing_key):
        import jwt as pyjwt

        with patch("jwt.decode", wraps=pyjwt.decode) as spy:
            oauth.verify_token(_make_token(signing_key))

        _, kwargs = spy.call_args
        assert kwargs["algorithms"] == ["RS256"]
        assert kwargs["audience"] == "test-client"

    def test_raises_401_on_unexpected_error(self, oauth, signing_key):
        with patch("jwt.decode", side_effect=RuntimeError("unexpected")):
            detail = self._assert_rejected(oauth, _make_token(signing_key))

        assert detail == "Unauthorized"

    def test_fetches_key_by_kid_when_key_absent(self, oauth, signing_key):
        oauth.public_key = None

        def fake_fetch(kid=None):
            oauth.public_key = signing_key.public_key()

        token = _make_token(signing_key, headers={"kid": "key99"})
        with patch.object(
            oauth, "_fetch_public_key", side_effect=fake_fetch
        ) as mock_fetch:
            payload = oauth.verify_token(token)

        mock_fetch.assert_called_once_with(kid="key99")
        assert payload["sub"] == "user1"

    def test_rejects_when_key_cannot_be_fetched(self, oauth, signing_key):
        oauth.public_key = None

        with patch.object(oauth, "_fetch_public_key"):
            self._assert_rejected(oauth, _make_token(signing_key))


class TestVerifyTokenDependency:
    """Test the module-level verify_token FastAPI dependency function."""

    def test_delegates_to_keycloak_oauth(self):
        from serving import oauth_middleware

        mock_creds = MagicMock()
        mock_creds.credentials = "bearer.token.here"

        expected = {"sub": "user1", "preferred_username": "alice"}

        with patch.object(
            oauth_middleware.keycloak_oauth, "verify_token", return_value=expected
        ) as mock_verify:
            result = oauth_middleware.verify_token(mock_creds)

        mock_verify.assert_called_once_with("bearer.token.here")
        assert result["sub"] == "user1"
