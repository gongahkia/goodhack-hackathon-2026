from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import Settings
from .models import Node
from .store import GraphStore


GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "openid",
    "email",
    "profile",
]
OAUTH_STATE_TTL_SECONDS = 600
TOKEN_REFRESH_SKEW_SECONDS = 60


@dataclass(frozen=True)
class CalendarCredentials:
    access_token: str
    calendar_id: str
    source: str


def google_oauth_configured(settings: Settings) -> bool:
    return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret and settings.google_oauth_redirect_uri)


async def create_google_oauth_authorization(store: GraphStore, patient_id: str, settings: Settings) -> dict[str, str]:
    if not settings.google_calendar_oauth_enabled:
        raise RuntimeError("Google Calendar OAuth is disabled.")
    if not google_oauth_configured(settings):
        raise RuntimeError("Google OAuth client config is incomplete.")
    state = token_urlsafe(32)
    await store.set_system_state(
        f"google_oauth_state:{state}",
        {"patient_id": patient_id, "created_at": datetime.now(UTC).isoformat()},
        datetime.now(UTC) + timedelta(seconds=OAUTH_STATE_TTL_SECONDS),
    )
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_CALENDAR_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return {"authorization_url": f"{settings.google_oauth_auth_url}?{urlencode(params)}", "state": state}


async def link_google_calendar_account(store: GraphStore, patient_id: str, settings: Settings, code: str, state: str) -> Node:
    if not settings.google_calendar_oauth_enabled:
        raise RuntimeError("Google Calendar OAuth is disabled.")
    state_key = f"google_oauth_state:{state}"
    state_row = await store.get_system_state(state_key)
    if not state_row or not isinstance(state_row.get("value"), dict) or state_row["value"].get("patient_id") != patient_id:
        raise ValueError("Invalid or expired Google OAuth state.")
    token_payload = await _exchange_authorization_code(settings, code)
    userinfo = await _fetch_userinfo(settings, token_payload.get("access_token"))
    expires_at = _expires_at(token_payload.get("expires_in"))
    existing = await active_google_calendar_account(store, patient_id)
    payload = {
        "patient_id": patient_id,
        "provider": "google_calendar",
        "connection_status": "linked",
        "calendar_id": settings.google_calendar_id,
        "google_sub": userinfo.get("sub"),
        "email": userinfo.get("email"),
        "scope": token_payload.get("scope"),
        "access_token": token_payload.get("access_token"),
        "refresh_token": token_payload.get("refresh_token") or (existing.payload.get("refresh_token") if existing else None),
        "id_token": token_payload.get("id_token"),
        "access_token_expires_at": expires_at.isoformat() if expires_at else None,
        "linked_at": datetime.now(UTC).isoformat(),
    }
    if existing:
        return await store.update_node_payload(existing.id, payload, "approved")
    return await store.create_node("calendar_account", payload, "user", status="approved")


async def active_google_calendar_account(store: GraphStore, patient_id: str) -> Node | None:
    accounts = await store.list_nodes(patient_id, ["calendar_account"])
    return next(
        (
            account
            for account in accounts
            if account.status == "approved"
            and account.payload.get("provider") == "google_calendar"
            and account.payload.get("connection_status") == "linked"
        ),
        None,
    )


async def disconnect_google_calendar_account(store: GraphStore, patient_id: str) -> Node | None:
    account = await active_google_calendar_account(store, patient_id)
    if not account:
        return None
    return await store.update_node_payload(
        account.id,
        {"connection_status": "disconnected", "disconnected_at": datetime.now(UTC).isoformat()},
        "dismissed",
    )


async def resolve_google_calendar_credentials(settings: Settings, store: GraphStore | None = None, patient_id: str | None = None) -> CalendarCredentials | None:
    if settings.google_calendar_oauth_enabled and store and patient_id:
        account = await active_google_calendar_account(store, patient_id)
        if account:
            token = await _valid_oauth_access_token(store, account, settings)
            if token:
                return CalendarCredentials(token, str(account.payload.get("calendar_id") or settings.google_calendar_id), "oauth")
    if settings.google_calendar_access_token:
        return CalendarCredentials(settings.google_calendar_access_token, settings.google_calendar_id, "demo_env")
    return None


async def _valid_oauth_access_token(store: GraphStore, account: Node, settings: Settings) -> str | None:
    token = account.payload.get("access_token")
    expires_at = _parse_datetime(account.payload.get("access_token_expires_at"))
    if token and expires_at and expires_at > datetime.now(UTC) + timedelta(seconds=TOKEN_REFRESH_SKEW_SECONDS):
        return str(token)
    refresh_token = account.payload.get("refresh_token")
    if not refresh_token:
        return str(token) if token else None
    refreshed = await _refresh_access_token(settings, str(refresh_token))
    expires_at = _expires_at(refreshed.get("expires_in"))
    await store.update_node_payload(
        account.id,
        {
            "access_token": refreshed.get("access_token"),
            "scope": refreshed.get("scope") or account.payload.get("scope"),
            "access_token_expires_at": expires_at.isoformat() if expires_at else None,
            "token_refreshed_at": datetime.now(UTC).isoformat(),
        },
        "approved",
    )
    return str(refreshed.get("access_token")) if refreshed.get("access_token") else None


async def _exchange_authorization_code(settings: Settings, code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            settings.google_oauth_token_url,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
    return response.json()


async def _refresh_access_token(settings: Settings, refresh_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            settings.google_oauth_token_url,
            data={
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
    return response.json()


async def _fetch_userinfo(settings: Settings, access_token: Any) -> dict[str, Any]:
    if not access_token:
        return {}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(settings.google_oauth_userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
        response.raise_for_status()
    return response.json()


def _expires_at(expires_in: Any) -> datetime | None:
    try:
        return datetime.now(UTC) + timedelta(seconds=int(expires_in))
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
