"""Authentication module for Home Assistant Gateway."""

import asyncio
import aiohttp
import base64
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class AuthToken:
    """Authentication token data."""
    access_token: str
    token_type: str = "Bearer"
    expires_at: Optional[datetime] = None
    refresh_token: Optional[str] = None

    def is_expired(self) -> bool:
        """Check if token is expired."""
        if self.expires_at is None:
            return False
        return datetime.now() >= self.expires_at


class Authenticator:
    """Handles authentication with Home Assistant."""

    def __init__(self, config):
        self.config = config
        self.token: Optional[AuthToken] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the authenticator."""
        self.session = aiohttp.ClientSession()

    async def close(self) -> None:
        """Close the authenticator."""
        if self.session:
            await self.session.close()

    async def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for API requests."""
        async with self._lock:
            if self.config.home_assistant.auth_type == "long_lived_token":
                return {"Authorization": f"Bearer {self.config.home_assistant.access_token}"}
            elif self.config.home_assistant.auth_type == "username_password":
                if self.token and not self.token.is_expired():
                    return {"Authorization": f"{self.token.token_type} {self.token.access_token}"}
                await self._login()
                return {"Authorization": f"{self.token.token_type} {self.token.access_token}"}
            elif self.config.home_assistant.auth_type == "oauth2":
                if self.token and not self.token.is_expired():
                    return {"Authorization": f"{self.token.token_type} {self.token.access_token}"}
                await self._oauth2_login()
                return {"Authorization": f"{self.token.token_type} {self.token.access_token}"}
            else:
                raise ValueError(f"Unsupported auth type: {self.config.home_assistant.auth_type}")

    async def _login(self) -> None:
        """Login with username and password."""
        if not self.config.home_assistant.username or not self.config.home_assistant.password:
            raise ValueError("Username and password are required for login")

        login_data = {
            "username": self.config.home_assistant.username,
            "password": self.config.home_assistant.password,
            "client_id": "ha_gateway",
            "grant_type": "password"
        }

        try:
            response = await self.session.post(
                f"{self.config.home_assistant.url}/auth/token",
                data=login_data,
                ssl=self._get_ssl_context()
            )
            response.raise_for_status()
            data = await response.json()

            # Calculate expiration time (usually 1 hour)
            expires_in = data.get("expires_in", 3600)
            self.token = AuthToken(
                access_token=data["access_token"],
                token_type=data.get("token_type", "Bearer"),
                expires_at=datetime.now() + timedelta(seconds=expires_in),
                refresh_token=data.get("refresh_token")
            )

        except aiohttp.ClientError as e:
            raise AuthenticationError(f"Login failed: {e}")

    async def _oauth2_login(self) -> None:
        """Login with OAuth2."""
        # OAuth2 implementation depends on your OAuth2 provider
        # This is a placeholder for OAuth2 authentication
        raise NotImplementedError("OAuth2 authentication not implemented yet")

    async def refresh_token(self) -> bool:
        """Refresh the access token."""
        if not self.token or not self.token.refresh_token:
            return False

        try:
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": self.token.refresh_token,
                "client_id": "ha_gateway"
            }

            response = await self.session.post(
                f"{self.config.home_assistant.url}/auth/token",
                data=refresh_data,
                ssl=self._get_ssl_context()
            )
            response.raise_for_status()
            data = await response.json()

            # Update token
            expires_in = data.get("expires_in", 3600)
            self.token = AuthToken(
                access_token=data["access_token"],
                token_type=data.get("token_type", "Bearer"),
                expires_at=datetime.now() + timedelta(seconds=expires_in),
                refresh_token=data.get("refresh_token", self.token.refresh_token)
            )

            return True

        except aiohttp.ClientError:
            # Refresh failed, try to login again
            await self._login()
            return True

    def _get_ssl_context(self):
        """Get SSL context for HTTPS requests."""
        if not self.config.home_assistant.verify_ssl:
            return False
        return None


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass