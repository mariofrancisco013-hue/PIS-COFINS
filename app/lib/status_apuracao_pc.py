# Status de "apuração válida" — mesmo padrão do módulo ICMS (app/lib/status_apuracao.py): se a competência
# já foi calculada e não tem nenhuma inconsistência pendente (CST/CFOP não mapeados), está válida.
from sqlalchemy import text


def classificar_status(status_calculo: str, n_pendentes: int) -> dict:
    if status_calculo != "calculada":
        return {
            "valida": False, "n_pendentes": n_pendentes, "nivel": "info",
            "texto": "Apuração ainda não calculada.",
        }
    if not n_pendentes:
        return {
            "valida": True, "n_pendentes": 0, "nivel": "success",
            "texto": "Apuração válida — nenhuma inconsistência pendente.",
        }
    return {
        "valida": False, "n_pendentes": n_pendentes, "nivel": "warning",
        "texto": f"{n_pendentes} inconsistência(s) pendente(s) — revise na aba Inconsistências antes de "
                 f"considerar esta apuração fechada.",
    }


def status_competencia(session, competencia_id: int, status_calculo: str) -> dict:
    n_pendentes = session.execute(text("""
        select count(*) from inconsistencias_pc where competencia_id = :cid and status = 'pendente'
    """), {"cid": competencia_id}).scalar()
    return classificar_status(status_calculo, n_pendentes)
