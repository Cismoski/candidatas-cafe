"""Dependências comuns das rotas: usuário da sessão e análise do próprio usuário."""

from typing import Annotated

from fastapi import Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..ports import Repository
from ..values import AnalysisId

User = Annotated[CurrentUser, Depends(current_user)]

NOT_FOUND = HTTPException(404, "Análise não encontrada.")


def owned(db: Repository, raw_id: str, user: CurrentUser) -> tuple[AnalysisId, dict]:
    """Análise do usuário, ou 404. Também 404 para id malformado e para análise de
    outro usuário: a resposta não revela se o id existe."""
    try:
        analysis_id = AnalysisId(raw_id)
    except ValueError:
        raise NOT_FOUND from None
    a = db.get_analysis(analysis_id, user.id)
    if a is None:
        raise NOT_FOUND
    return analysis_id, a


def done(db: Repository, raw_id: str, user: CurrentUser) -> tuple[AnalysisId, dict]:
    analysis_id, a = owned(db, raw_id, user)
    if a["status"] != "done" or not a["summary"]:
        raise HTTPException(409, "O assistente fica disponível quando a análise terminar.")
    return analysis_id, a
