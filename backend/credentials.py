"""Per-user API credentials stored in the operating system's credential vault.

No keys are committed to Git, stored in SQLite or written to project files.
Windows: the keyring package normally uses Windows Credential Manager.
"""
from __future__ import annotations

SERVICE_NAME = "Lab Research Agent"
PROVIDERS = {"Gemini", "OpenAI"}


def _backend():
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("Install keyring: python -m pip install keyring") from exc
    return keyring


def get_key(provider: str) -> str:
    if provider not in PROVIDERS:
        raise ValueError("Unknown AI provider")
    try:
        return _backend().get_password(SERVICE_NAME, provider) or ""
    except Exception as exc:
        raise RuntimeError("Could not read credentials from the OS credential store") from exc


def save_key(provider: str, secret: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError("Unknown AI provider")
    secret = (secret or "").strip()
    if not secret:
        raise ValueError("Enter an API key before saving")
    try:
        _backend().set_password(SERVICE_NAME, provider, secret)
    except Exception as exc:
        raise RuntimeError("Could not save credentials to the OS credential store") from exc


def delete_key(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError("Unknown AI provider")
    try:
        if _backend().get_password(SERVICE_NAME, provider):
            _backend().delete_password(SERVICE_NAME, provider)
    except Exception as exc:
        raise RuntimeError("Could not delete credentials from the OS credential store") from exc
