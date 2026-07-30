"""Upstox OAuth 2.0 authorization flow.

Upstox uses an authorization code grant:
  1. Direct user to authorization URL
  2. User logs in, gets redirected with `?code=XYZ`
  3. Exchange code for access_token

Access token is valid until ~3:30 AM IST next day. Then re-auth is required.
"""
from __future__ import annotations

import urllib.parse

import httpx

AUTH_ENDPOINT = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_ENDPOINT = "https://api.upstox.com/v2/login/authorization/token"


def build_auth_url(
    api_key: str,
    redirect_uri: str,
    state: str = "stockpredict",
) -> str:
    """Build the URL the user should open in their browser to authorize our app."""
    params = {
        "response_type": "code",
        "client_id": api_key,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


def exchange_code(
    api_key: str,
    api_secret: str,
    redirect_uri: str,
    code: str,
) -> dict:
    """Exchange an auth code for an access token. Returns the full JSON response."""
    headers = {
        "Accept": "application/json",
        "Api-Version": "2.0",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "code": code,
        "client_id": api_key,
        "client_secret": api_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    resp = httpx.post(TOKEN_ENDPOINT, headers=headers, data=data, timeout=20.0)
    resp.raise_for_status()
    return resp.json()
