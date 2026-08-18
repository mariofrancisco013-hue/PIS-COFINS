"""
Checagem de CST × CFOP/NCM no Relatório 1096 — regras extensíveis (tabelas cst_regra_cfop_pc/
cst_regra_ncm_pc/cst_regra_alerta_pc, ver sql/004_regras_cst_pc.sql), confirmadas com o usuário em
14/08/2026 (à noite): CST 70 (entrada, sem direito a crédito) e CST 06 (saída, espelho) só deveriam
aparecer em CFOPs específicos de compra/venda; CST 71/74 (entrada, isenção/sem incidência) e CST 07
(saída, união dos NCMs de 71+74) só em NCMs específicos; CST 98 (entrada) deve sempre gerar alerta, mas
nunca bloquear nada.

Isso é conferência pura sobre o Relatório 1096 — NÃO afeta o cálculo da apuração (que roda 100% sobre a
Rotina 1024, ver calculo_pis_cofins_lucro_real.py) nem o CST gravado em relatorio_pc_itens. Achados viram
linhas em inconsistencias_pc com fonte='relatorio_1096', do mesmo jeito que cst_nao_mapeado/cfop_sem_grupo
já funcionam — só que com tipo='cst_regra_cfop'/'cst_regra_ncm'/'cst_regra_alerta'.

Cada checagem por CFOP/NCM é bidirecional num único SELECT: pega qualquer combinação (cfop, cst) — ou
(ncm, cst) — que toque a tabela de regra por QUALQUER lado (o CFOP/NCM tem uma regra OU o CST é um dos
CSTs regrados nessa direção) mas não bate exatamente com a regra esperada. Isso cobre tanto "esse CFOP
deveria ser CST 70 mas veio com outro CST" quanto "esse CST 70 apareceu num CFOP que não está na lista".
"""
from sqlalchemy import text

TIPOS_REGRA = ("cst_regra_cfop", "cst_regra_ncm", "cst_regra_alerta")


def registrar_inconsistencias_cst_regras(session, competencia_id, empresa_id):
    """Roda as 3 checagens (CFOP, NCM, alerta) para os itens do 1096 desta filial nesta competência.
    Escopado por empresa_id, mesmo padrão do resto do módulo: recria do zero só os achados desta filial,
    sem tocar em outras filiais do mesmo grupo. Chame depois de importar_arquivo (dentro de
    importacao_pc.importar_1096, junto com _registrar_inconsistencias_1096)."""
    session.execute(text(f"""
        delete from inconsistencias_pc
        where competencia_id = :cid and empresa_id = :eid
          and tipo in ({", ".join(f"'{t}'" for t in TIPOS_REGRA)})
    """), {"cid": competencia_id, "eid": empresa_id})

    _checar_regra_cfop(session, competencia_id, empresa_id)
    _checar_regra_ncm(session, competencia_id, empresa_id)
    _checar_alerta(session, competencia_id, empresa_id)
    session.commit()


def _checar_regra_cfop(session, competencia_id, empresa_id):
    achados = session.execute(text("""
        select distinct ri.cfop, ri.cst, ri.tipo_operacao,
               (select r.cst from cst_regra_cfop_pc r
                where r.cfop = ri.cfop and r.tipo_operacao = ri.tipo_operacao) as cst_esperado
        from relatorio_pc_itens ri
        where ri.competencia_id = :cid and ri.empresa_id = :eid
          and (
              exists (select 1 from cst_regra_cfop_pc r
                      where r.cfop = ri.cfop and r.tipo_operacao = ri.tipo_operacao)
              or exists (select 1 from cst_regra_cfop_pc r
                         where r.cst = ri.cst and r.tipo_operacao = ri.tipo_operacao)
          )
          and not exists (select 1 from cst_regra_cfop_pc r
                           where r.cfop = ri.cfop and r.cst = ri.cst and r.tipo_operacao = ri.tipo_operacao)
        order by ri.cfop, ri.cst
    """), {"cid": competencia_id, "eid": empresa_id}).mappings().all()

    for a in achados:
        if a["cst_esperado"] is not None:
            descricao = (
                f'CFOP {a["cfop"]} deveria estar com CST {a["cst_esperado"]} (regra CFOP × CST) mas veio '
                f'com CST {a["cst"]} no Relatório 1096 — confira o cadastro do produto/operação no Winthor.'
            )
        else:
            descricao = (
                f'CST {a["cst"]} apareceu no CFOP {a["cfop"]} no Relatório 1096, mas esse CST só é esperado '
                f'em CFOPs específicos (regra CFOP × CST) — confira se o CFOP está certo para esse item.'
            )
        session.execute(text("""
            insert into inconsistencias_pc (competencia_id, empresa_id, tipo, cst, cfop, tipo_operacao,
                                             descricao, fonte)
            values (:cid, :eid, 'cst_regra_cfop', :cst, :cfop, :tipo, :descricao, 'relatorio_1096')
        """), {"cid": competencia_id, "eid": empresa_id, "cst": a["cst"], "cfop": a["cfop"],
               "tipo": a["tipo_operacao"], "descricao": descricao})


def _checar_regra_ncm(session, competencia_id, empresa_id):
    achados = session.execute(text("""
        select distinct ri.ncm, ri.cst, ri.tipo_operacao, ri.cfop,
               (select r.cst from cst_regra_ncm_pc r
                where r.ncm = ri.ncm and r.tipo_operacao = ri.tipo_operacao) as cst_esperado
        from relatorio_pc_itens ri
        where ri.competencia_id = :cid and ri.empresa_id = :eid and ri.ncm is not null
          and (
              exists (select 1 from cst_regra_ncm_pc r
                      where r.ncm = ri.ncm and r.tipo_operacao = ri.tipo_operacao)
              or exists (select 1 from cst_regra_ncm_pc r
                         where r.cst = ri.cst and r.tipo_operacao = ri.tipo_operacao)
          )
          and not exists (select 1 from cst_regra_ncm_pc r
                           where r.ncm = ri.ncm and r.cst = ri.cst and r.tipo_operacao = ri.tipo_operacao)
        order by ri.ncm, ri.cst
    """), {"cid": competencia_id, "eid": empresa_id}).mappings().all()

    for a in achados:
        if a["cst_esperado"] is not None:
            descricao = (
                f'NCM {a["ncm"]} deveria estar com CST {a["cst_esperado"]} (regra NCM × CST) mas veio com '
                f'CST {a["cst"]} no Relatório 1096 (CFOP {a["cfop"]}) — confira o cadastro do produto no '
                f'Winthor.'
            )
        else:
            descricao = (
                f'CST {a["cst"]} apareceu no NCM {a["ncm"]} (CFOP {a["cfop"]}) no Relatório 1096, mas esse '
                f'CST só é esperado em NCMs específicos (regra NCM × CST) — confira se o NCM está certo '
                f'para esse item.'
            )
        session.execute(text("""
            insert into inconsistencias_pc (competencia_id, empresa_id, tipo, cst, cfop, ncm, tipo_operacao,
                                             descricao, fonte)
            values (:cid, :eid, 'cst_regra_ncm', :cst, :cfop, :ncm, :tipo, :descricao, 'relatorio_1096')
        """), {"cid": competencia_id, "eid": empresa_id, "cst": a["cst"], "cfop": a["cfop"], "ncm": a["ncm"],
               "tipo": a["tipo_operacao"], "descricao": descricao})


def _checar_alerta(session, competencia_id, empresa_id):
    achados = session.execute(text("""
        select distinct ri.cst, ri.cfop, ri.tipo_operacao
        from relatorio_pc_itens ri
        join cst_regra_alerta_pc r on r.cst = ri.cst and r.tipo_operacao = ri.tipo_operacao
        where ri.competencia_id = :cid and ri.empresa_id = :eid
        order by ri.cst, ri.cfop
    """), {"cid": competencia_id, "eid": empresa_id}).mappings().all()

    for a in achados:
        descricao = (
            f'CST {a["cst"]} (CFOP {a["cfop"]}) apareceu no Relatório 1096 — alerta informativo, não bloqueia '
            f'o cálculo (que roda sobre a Rotina 1024), mas vale conferir a operação.'
        )
        session.execute(text("""
            insert into inconsistencias_pc (competencia_id, empresa_id, tipo, cst, cfop, tipo_operacao,
                                             descricao, fonte)
            values (:cid, :eid, 'cst_regra_alerta', :cst, :cfop, :tipo, :descricao, 'relatorio_1096')
        """), {"cid": competencia_id, "eid": empresa_id, "cst": a["cst"], "cfop": a["cfop"],
               "tipo": a["tipo_operacao"], "descricao": descricao})


# --------------------------------------------------------------------------------------- Ajuste manual (log-only)
def registrar_ajuste_cst(session, inconsistencia_id, cst_corrigido, observacao=None, usuario=None):
    """Registra uma correção manual de CST feita na tela — SÓ HISTÓRICO. Não atualiza relatorio_pc_itens,
    não recalcula nada: a apuração continua 100% sobre a Rotina 1024. Serve pra virar uma lista de "o que
    corrigir no Winthor" (rastreável: quem, quando, de que CST original pra que CST corrigido). Marca a
    inconsistência como status='ajustado' (distinto de 'revisado', que é só "vi e não vou mexer")."""
    usuario = usuario or {}
    original = session.execute(
        text("select cst from inconsistencias_pc where id = :id"), {"id": inconsistencia_id}
    ).scalar()
    session.execute(text("""
        insert into ajustes_cst_pc (inconsistencia_id, cst_original, cst_corrigido, observacao, ajustado_por)
        values (:iid, :original, :corrigido, :obs, :por)
    """), {"iid": inconsistencia_id, "original": original, "corrigido": cst_corrigido, "obs": observacao,
           "por": usuario.get("id")})
    session.execute(text("""
        update inconsistencias_pc
        set status = 'ajustado', revisado_por = :por, revisado_em = now()
        where id = :id
    """), {"id": inconsistencia_id, "por": usuario.get("id")})
    session.commit()


def carregar_historico_ajustes(session, competencia_id):
    """Uma linha por ajuste manual registrado nesta competência — usada pra exportar/consultar a lista de
    correções pendentes de aplicar no Winthor (CST original → CST corrigido, quem, quando, em que CFOP/NCM)."""
    rows = session.execute(text("""
        select a.id, a.inconsistencia_id, a.cst_original, a.cst_corrigido, a.observacao, a.ajustado_em,
               i.cfop, i.ncm, i.tipo_operacao, i.descricao,
               coalesce(e.filial_winthor, '(não identificada)') as filial
        from ajustes_cst_pc a
        join inconsistencias_pc i on i.id = a.inconsistencia_id
        left join empresas e on e.id = i.empresa_id
        where i.competencia_id = :cid
        order by a.ajustado_em desc
    """), {"cid": competencia_id}).mappings().all()
    return rows
