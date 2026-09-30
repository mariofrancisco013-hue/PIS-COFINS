"""
Encerramento e reabertura da competência — Lucro Real (29/09/2026, migração 017).

Encerrar = recalcular a apuração uma última vez, gerar o relatório da escrituração (PDF + Excel anexo),
gravar os dois arquivos em `escrituracao_pc` (nova versão) e travar a competência (status 'fechada'). O
download sempre entrega os arquivos gravados — a foto fixa do momento do encerramento.

Reabrir = voltar o status para 'calculada' (com motivo obrigatório, registrado em `encerramento_pc_log`).
As versões anteriores do relatório ficam gravadas como histórico; encerrar de novo gera a versão seguinte.
"""
from sqlalchemy import inspect as sa_inspect, text

from lib.calculo_pis_cofins_lucro_real import calcular_apuracao_pc, salvar_apuracao_pc
from lib.competencia_status_pc import STATUS_FECHADA, exigir_competencia_aberta
from lib.escrituracao_arquivos_pc import gerar_pdf, gerar_xlsx, nomes_arquivos
from lib.escrituracao_pc import montar_escrituracao


def tabelas_prontas(session) -> bool:
    """False se a migração 017 ainda não rodou — a tela mostra o aviso em vez de quebrar."""
    insp = sa_inspect(session.get_bind())
    return insp.has_table("escrituracao_pc") and insp.has_table("encerramento_pc_log")


def encerrar_competencia(session, competencia_id, usuario=None):
    exigir_competencia_aberta(session, competencia_id)
    linhas = calcular_apuracao_pc(session, competencia_id)
    salvar_apuracao_pc(session, competencia_id, linhas)

    versao = (session.execute(text("select max(versao) from escrituracao_pc where competencia_id = :cid"),
                              {"cid": competencia_id}).scalar() or 0) + 1
    dados = montar_escrituracao(session, competencia_id, usuario=usuario, versao=versao)
    nome_pdf, nome_xlsx = nomes_arquivos(dados)
    xlsx = gerar_xlsx(dados)
    pdf = gerar_pdf(dados, nome_xlsx)

    session.execute(text("""
        insert into escrituracao_pc (competencia_id, versao, gerado_por, pis_darf, cofins_darf, pdf, xlsx)
        values (:cid, :v, :u, :pis, :cofins, :pdf, :xlsx)
    """), {"cid": competencia_id, "v": versao, "u": usuario, "pis": str(dados["darf"]["darf_pis"]),
           "cofins": str(dados["darf"]["darf_cofins"]), "pdf": pdf, "xlsx": xlsx})
    session.execute(text("update competencias set status = :st where id = :cid"),
                    {"st": STATUS_FECHADA, "cid": competencia_id})
    session.execute(text("""
        insert into encerramento_pc_log (competencia_id, acao, usuario) values (:cid, 'encerrar', :u)
    """), {"cid": competencia_id, "u": usuario})
    session.commit()
    return {"versao": versao, "darf": dados["darf"], "conferencias_com_diferenca":
            [c for c in dados["conferencias"] if not c["ok"]]}


def reabrir_competencia(session, competencia_id, usuario=None, motivo=None):
    if not (motivo or "").strip():
        raise ValueError("Informe o motivo da reabertura.")
    session.execute(text("update competencias set status = 'calculada' where id = :cid and status = :st"),
                    {"cid": competencia_id, "st": STATUS_FECHADA})
    session.execute(text("""
        insert into encerramento_pc_log (competencia_id, acao, usuario, motivo) values (:cid, 'reabrir', :u, :m)
    """), {"cid": competencia_id, "u": usuario, "m": motivo.strip()})
    session.commit()


def versoes(session, competencia_id):
    """Versões gravadas (sem os arquivos), da mais nova para a mais antiga."""
    return [dict(r) for r in session.execute(text("""
        select versao, gerado_em, gerado_por, pis_darf, cofins_darf
        from escrituracao_pc where competencia_id = :cid order by versao desc
    """), {"cid": competencia_id}).mappings().all()]


def arquivos(session, competencia_id, versao):
    r = session.execute(text("""
        select e.versao, e.pdf, e.xlsx, c.cnpj_raiz, c.ano, c.mes
        from escrituracao_pc e join competencias c on c.id = e.competencia_id
        where e.competencia_id = :cid and e.versao = :v
    """), {"cid": competencia_id, "v": versao}).mappings().first()
    if r is None:
        return None
    base = f"Escrituracao_PIS_COFINS_{r['cnpj_raiz']}_{r['ano']}-{int(r['mes']):02d}_v{r['versao']}"
    return {"pdf": bytes(r["pdf"]), "xlsx": bytes(r["xlsx"]), "nome_pdf": base + ".pdf",
            "nome_xlsx": base + "_Anexo.xlsx"}


def historico(session, competencia_id):
    return [dict(r) for r in session.execute(text("""
        select acao, usuario, motivo, em from encerramento_pc_log where competencia_id = :cid order by em desc
    """), {"cid": competencia_id}).mappings().all()]
