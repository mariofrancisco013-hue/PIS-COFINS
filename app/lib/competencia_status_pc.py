"""
Trava de competência encerrada (29/09/2026, migração 017). Módulo sem dependências de propósito — é
importado pelos importadores, lançamentos manuais, grade de itens, ajuste de CST e gravação da apuração, que
chamam `exigir_competencia_aberta` antes de gravar qualquer coisa.

Encerrada = `competencias.status = 'fechada'` (valor que já existia no check desde a 001). Para mexer de novo,
é preciso reabrir a competência (aba Apuração), o que fica registrado em `encerramento_pc_log`.
"""
from sqlalchemy import text

STATUS_FECHADA = "fechada"


class CompetenciaEncerradaError(ValueError):
    """Tentativa de gravar numa competência encerrada. É ValueError para as telas que já tratam esse tipo
    de erro com st.error mostrarem a mensagem normalmente."""


def competencia_fechada(session, competencia_id) -> bool:
    if competencia_id is None:
        return False
    status = session.execute(text("select status from competencias where id = :cid"),
                             {"cid": competencia_id}).scalar()
    return status == STATUS_FECHADA


def exigir_competencia_aberta(session, competencia_id):
    if competencia_fechada(session, competencia_id):
        raise CompetenciaEncerradaError(
            "Esta competência está encerrada — os valores ficaram travados no relatório da escrituração. "
            "Para alterar alguma coisa, reabra a competência na aba Apuração (o motivo fica registrado)."
        )
