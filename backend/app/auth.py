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
from dataclasses import dataclass
from datetime import timedelta

import jwt
import requests
from cachecontrol import CacheControl
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from .db import Database, now
from .ports import Identity, InvalidIdentity
from .settings import Settings

GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
ALGORITHM = "HS256"


class _GoogleTransport(google_requests.Request):
    """Sessão HTTP com cache (respeita o Cache-Control das chaves públicas do
    Google, ~horas) e timeout curto: sem isso a lib baixa os certificados a cada
    login, com timeout padrão de 120 s."""

    def __call__(self, *args, timeout: float = 5, **kwargs):
        return super().__call__(*args, timeout=timeout, **kwargs)


_transport = _GoogleTransport(session=CacheControl(requests.Session()))
CLOCK_SKEW_S = 10  # relógios do cliente/Google/servidor podem divergir alguns segundos


def verify_google_id_token(token: str, client_id: str) -> Identity:
    """Valida o ID token com as chaves públicas do Google (cacheadas pela lib)."""
    try:
        claims = id_token.verify_oauth2_token(
            token, _transport, audience=client_id, clock_skew_in_seconds=CLOCK_SKEW_S
        )
    except ValueError as e:  # assinatura, audiência ou expiração inválidas
        raise InvalidIdentity(str(e)) from e
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise InvalidIdentity("emissor inválido")
    if not claims.get("email_verified"):
        raise InvalidIdentity("e-mail não verificado")
    return Identity(sub=claims["sub"], email=claims["email"], name=claims.get("name"))


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


def authenticate(token: str, settings: Settings, db: Database) -> CurrentUser | None:
    """Valida o JWT, a revogação e a existência do usuário. None se inválido."""
    try:
        claims = decode_token(token, settings)
    except jwt.PyJWTError:
        return None
    if db.is_revoked(claims["jti"]) or db.get_user(claims["sub"]) is None:
        return None
    return CurrentUser(id=claims["sub"], jti=claims["jti"], expires_at_ts=claims["exp"])


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise UNAUTHORIZED
    user = authenticate(
        creds.credentials, request.app.state.services.settings, request.app.state.services.db
    )
    if user is None:
        raise UNAUTHORIZED
    request.state.user_id = user.id  # usado pela chave do rate limit
    return user


class BearerPrecheckMiddleware:
    """Rejeita com 401 as rotas listadas ANTES de ler o corpo.

    Sem isso, o FastAPI faz o parse do multipart (até o limite de upload) antes
    de rodar a dependência de autenticação: qualquer anônimo gastaria memória e
    disco, e respostas 401 nem passam pelo rate limit.
    """

    def __init__(self, app: ASGIApp, routes: set[tuple[str, str]]):
        self.app, self.routes = app, routes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and (scope["method"], scope["path"]) in self.routes:
            auth = dict(scope.get("headers", [])).get(b"authorization", b"").decode("latin-1")
            scheme, _, token = auth.partition(" ")
            services = scope["app"].state.services
            ok = (
                scheme.lower() == "bearer"
                and token
                and await run_in_threadpool(authenticate, token, services.settings, services.db)
            )
            if not ok:
                response = JSONResponse(
                    {"detail": UNAUTHORIZED.detail}, 401, headers=UNAUTHORIZED.headers
                )
                return await response(scope, receive, send)
        await self.app(scope, receive, send)
