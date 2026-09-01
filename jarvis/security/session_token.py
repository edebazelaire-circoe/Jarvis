import secrets


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)
