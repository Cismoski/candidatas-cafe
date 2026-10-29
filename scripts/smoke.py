# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Verificação do deploy: o que dá para conferir de fora, sem login.

    uv run scripts/smoke.py --api https://cafe-candidatas-api.onrender.com \\
                            --web https://cafe-candidatas.pages.dev

Confere: API acordada e saudável; rotas protegidas recusam sem token; CORS
aceita só a origem do frontend; headers de segurança na API e no Pages; CSP do
Pages aponta para a API; amostras servidas. Sai com código 1 se algo falhar.
Login, upload e chat precisam de conta Google: ficam no roteiro manual.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

FOREIGN_ORIGIN = "https://origem-nao-autorizada.example"
results: list[tuple[bool, str]] = []


def check(ok: bool, what: str) -> None:
    results.append((ok, what))
    print(f"[{'ok' if ok else 'FALHOU'}] {what}")


def request(url: str, method: str = "GET", headers: dict | None = None, timeout: float = 30):
    """(status, headers em minúsculas, corpo) sem lançar em 4xx/5xx."""
    req = urllib.request.Request(url, method=method, headers=headers or {})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()
    except OSError as e:  # DNS, TLS, conexão recusada: vira FALHOU, não traceback
        print(f"  (sem resposta de {url}: {e})")
        return 0, {}, b""


def csp_directive(csp: str, name: str) -> list[str]:
    """Fontes de uma diretiva da CSP (lista vazia se ela não existir)."""
    for part in csp.split(";"):
        tokens = part.split()
        if tokens and tokens[0] == name:
            return tokens[1:]
    return []


def wake(api: str, budget_s: float = 120) -> bool:
    """O plano gratuito dorme: espera a API acordar antes de checar o resto."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < budget_s:
        try:
            status, _, body = request(f"{api}/health", timeout=30)
            if status == 200 and json.loads(body).get("status") == "ok":
                print(f"API respondeu em {time.monotonic() - t0:.0f} s")
                return True
        except (OSError, ValueError):
            pass
        time.sleep(3)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True, help="URL da API, sem barra final")
    ap.add_argument("--web", required=True, help="URL do frontend, sem barra final")
    a = ap.parse_args()
    api, web = a.api.rstrip("/"), a.web.rstrip("/")

    check(wake(api), "API acorda e /health responde ok")
    if not results[-1][0]:
        return 1

    status, h, _ = request(f"{api}/analyses")
    check(status == 401, f"GET /analyses sem token -> 401 (recebido {status})")
    check(h.get("x-content-type-options") == "nosniff", "API envia X-Content-Type-Options")
    check("max-age" in h.get("strict-transport-security", ""), "API envia HSTS")
    check("server" not in h or "uvicorn" not in h["server"].lower(), "API não expõe o uvicorn")

    status, _, _ = request(f"{api}/analyses/qualquer/files/geojson")
    check(status == 401, f"download sem token -> 401 (recebido {status})")

    pre = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization",
    }
    _, h, _ = request(f"{api}/analyses", "OPTIONS", {**pre, "Origin": web})
    check(h.get("access-control-allow-origin") == web, "CORS aceita a origem do frontend")
    _, h, _ = request(f"{api}/analyses", "OPTIONS", {**pre, "Origin": FOREIGN_ORIGIN})
    check(
        h.get("access-control-allow-origin") not in (FOREIGN_ORIGIN, "*"),
        "CORS recusa outra origem",
    )

    status, h, body = request(f"{web}/")
    check(status == 200 and b'id="root"' in body, "frontend publicado")
    csp = h.get("content-security-policy", "")
    api_origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(api))
    check(api_origin in csp_directive(csp, "connect-src"), "CSP do Pages libera a API")
    check(
        csp_directive(csp, "frame-ancestors") == ["'none'"] or h.get("x-frame-options") == "DENY",
        "Pages bloqueia iframe",
    )
    check(h.get("x-content-type-options") == "nosniff", "Pages envia X-Content-Type-Options")

    # O Pages devolve index.html com 200 para caminho inexistente: conferir o tipo
    status, h, _ = request(f"{web}/amostra/imagem_multiespectral.tif", "HEAD")
    check(
        status == 200 and "text/html" not in h.get("content-type", "text/html"),
        f"amostra do kit servida pelo Pages ({h.get('content-type', 'sem content-type')})",
    )

    failed = [w for ok, w in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} verificações ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
