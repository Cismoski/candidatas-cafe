"""Normalização de texto comum à guarda e às respostas automáticas."""

import unicodedata


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))
