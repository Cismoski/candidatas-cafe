"""Autenticação: ID token do Google -> JWT próprio da aplicação.

Fluxo:
1. O frontend obtém um ID token pelo Google Identity Services.
2. POST /auth/google: o backend valida assinatura (chaves públicas do Google),
   audiência (= nosso client ID), emissor, expiração e e-mail verificado.
3. O backend emite o próprio JWT (HS256, curto, com jti). O ID token do Google
   não é reutilizado como sessão: a validade e a revogação ficam sob nosso controle.
4. Logout grava o jti em revoked_tokens até a expiração natural do token.

Decisão para o desafio: o JWT vai no header Authorization (Bearer). Em produção
eu usaria cookie httpOnly + SameSite no mesmo site (ver README).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from .db import Database, now
from .settings import Settings

GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
ALGORITHM = "HS256"


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None


class InvalidGoogleToken(Exception):
    pass


GoogleVerifier = Callable[[str, str], GoogleIdentity]

_transport = google_requests.Request()


def verify_google_id_token(token: str, client_id: str) -> GoogleIdentity:
    """Valida o ID token com as chaves públicas do Google (cacheadas pela lib)."""
    try:
        claims = id_token.verify_oauth2_token(token, _transport, audience=client_id)
    except ValueError as e:  # assinatura, audiência ou expiração inválidas
        raise InvalidGoogleToken(str(e)) from e
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise InvalidGoogleToken("emissor inválido")
    if not claims.get("email_verified"):
        raise InvalidGoogleToken("e-mail não verificado")
    return GoogleIdentity(sub=claims["sub"], email=claims["email"], name=claims.get("name"))


@dataclass(frozen=True)
class CurrentUser:
    id: str
    jti: str
    expires_at_ts: int


def issue_token(user_id: str, settings: Settings) -> tuple[str, int]:
    issued = now()
    exp = issued + timedelta(minutes=settings.jwt_ttl_minutes)
    payload = {
        "sub": user_id,
        "jti": str(uuid.uuid4()),
        "iat": int(issued.timestamp()),
        "nbf": int(issued.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)
    return token, settings.jwt_ttl_minutes * 60


def decode_token(token: str, settings: Settings) -> dict:
    return jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[ALGORITHM],  # lista fixa: impede "alg: none" e troca de algoritmo
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["exp", "iat", "sub", "jti", "iss", "aud"]},
    )


_bearer = HTTPBearer(auto_error=False)

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sessão inválida ou expirada. Entre novamente.",
    headers={"WWW-Authenticate": "Bearer"},
)


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise UNAUTHORIZED
    settings: Settings = request.app.state.settings
    db: Database = request.app.state.db
    try:
        claims = decode_token(creds.credentials, settings)
    except jwt.PyJWTError:
        raise UNAUTHORIZED from None
    if db.is_revoked(claims["jti"]) or db.get_user(claims["sub"]) is None:
        raise UNAUTHORIZED
    request.state.user_id = claims["sub"]  # usado pela chave do rate limit
    return CurrentUser(id=claims["sub"], jti=claims["jti"], expires_at_ts=claims["exp"])
