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

Cada checagem por CFOP/NCM é bidirecional: pega qualquer combinação (cfop, cst) — ou (ncm, cst) — que toque
a tabela de regra por QUALQUER lado (o CFOP/NCM tem uma regra OU o CST é um dos CSTs regrados nessa direção)
mas não bate exatamente com a regra esperada. Isso cobre tanto "esse CFOP deveria ser CST 70 mas veio com
outro CST" quanto "esse CST 70 apareceu num CFOP que não está na lista".

ESTRUTURA (18/08/2026 — pedido do usuário: "quero uma estrutura semelhante ao que foi feito no ICMS
normal"), replicando o padrão de sql/008 e sql/009 daquele projeto:
- AGRUPAMENTO: ocorrências do mesmo erro (mesma combinação cfop/ncm/cst) dentro da mesma filial/competência
  viram UMA linha em inconsistencias_pc, com `quantidade` = número de itens do 1096 por trás dela, em vez
  de uma linha por combinação sem contagem. `chave_agrupamento` identifica o grupo (ver cada _checar_* para
  o formato exato).
- APRENDIZADO (excecoes_inconsistencia_pc, sql/005): quando o analista revisa um grupo, dá uma justificativa
  e marca "replicar nas próximas apurações", isso vira uma exceção ativa por (empresa_id, tipo,
  chave_agrupamento). Da próxima vez que o mesmo grupo aparecer nesta filial, a inconsistência já nasce
  com status='revisado' e a justificativa preenchida (aplicada_por_excecao=true) — não pede revisão de novo.
"""
from sqlalchemy import text

TIPOS_REGRA = ("cst_regra_cfop", "cst_regra_ncm", "cst_regra_alerta")


def _buscar_excecoes_ativas(session, empresa_id, tipo):
    """chave_agrupamento -> justificativa, só das exceções ativas desta filial/tipo."""
    rows = session.execute(text("""
        select chave_agrupamento, justificativa from excecoes_inconsistencia_pc
        where empresa_id = :eid and tipo = :tipo and ativa = true
    """), {"eid": empresa_id, "tipo": tipo}).mappings().all()
    return {r["chave_agrupamento"]: r["justificativa"] for r in rows}


def _inserir_grupo(session, competencia_id, empresa_id, tipo, cst, cfop, ncm, tipo_operacao, descricao,
                    chave_agrupamento, quantidade, excecoes):
    justificativa = excecoes.get(chave_agrupamento)
    session.execute(text("""
        insert into inconsistencias_pc
            (competencia_id, empresa_id, tipo, cst, cfop, ncm, tipo_operacao, descricao, fonte,
             chave_agrupamento, quantidade, justificativa, aplicada_por_excecao, status)
        values
            (:cid, :eid, :tipo, :cst, :cfop, :ncm, :top, :descricao, 'relatorio_1096',
             :chave, :qtd, :just, :aplicada, :status)
    """), {
        "cid": competencia_id, "eid": empresa_id, "tipo": tipo, "cst": cst, "cfop": cfop, "ncm": ncm,
        "top": tipo_operacao, "descricao": descricao, "chave": chave_agrupamento, "qtd": quantidade,
        "just": justificativa, "aplicada": justificativa is not None,
        "status": "revisado" if justificativa is not None else "pendente",
    })


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
    excecoes = _buscar_excecoes_ativas(session, empresa_id, "cst_regra_cfop")
    achados = session.execute(text("""
        select ri.cfop, ri.cst, ri.tipo_operacao, count(*) as quantidade,
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
        group by ri.cfop, ri.cst, ri.tipo_operacao
        order by ri.cfop, ri.cst
    """), {"cid": competencia_id, "eid": empresa_id}).mappings().all()

    for a in achados:
        chave = f'cfop:{a["cfop"]}|cst:{a["cst"]}|op:{a["tipo_operacao"]}'
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
        _inserir_grupo(session, competencia_id, empresa_id, "cst_regra_cfop", a["cst"], a["cfop"], None,
                       a["tipo_operacao"], descricao, chave, a["quantidade"], excecoes)


def _checar_regra_ncm(session, competencia_id, empresa_id):
    excecoes = _buscar_excecoes_ativas(session, empresa_id, "cst_regra_ncm")
    achados = session.execute(text("""
        select ri.ncm, ri.cst, ri.tipo_operacao, count(*) as quantidade,
               min(ri.cfop) as cfop_repr, count(distinct ri.cfop) as n_cfops,
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
        group by ri.ncm, ri.cst, ri.tipo_operacao
        order by ri.ncm, ri.cst
    """), {"cid": competencia_id, "eid": empresa_id}).mappings().all()

    for a in achados:
        chave = f'ncm:{a["ncm"]}|cst:{a["cst"]}|op:{a["tipo_operacao"]}'
        cfops_nota = f' (CFOP {a["cfop_repr"]})' if a["n_cfops"] == 1 else f' ({a["n_cfops"]} CFOPs diferentes)'
        if a["cst_esperado"] is not None:
            descricao = (
                f'NCM {a["ncm"]} deveria estar com CST {a["cst_esperado"]} (regra NCM × CST) mas veio com '
                f'CST {a["cst"]} no Relatório 1096{cfops_nota} — confira o cadastro do produto no Winthor.'
            )
        else:
            descricao = (
                f'CST {a["cst"]} apareceu no NCM {a["ncm"]}{cfops_nota} no Relatório 1096, mas esse CST só '
                f'é esperado em NCMs específicos (regra NCM × CST) — confira se o NCM está certo para esse '
                f'item.'
            )
        _inserir_grupo(session, competencia_id, empresa_id, "cst_regra_ncm", a["cst"], a["cfop_repr"],
                       a["ncm"], a["tipo_operacao"], descricao, chave, a["quantidade"], excecoes)


def _checar_alerta(session, competencia_id, empresa_id):
    excecoes = _buscar_excecoes_ativas(session, empresa_id, "cst_regra_alerta")
    achados = session.execute(text("""
        select ri.cst, ri.tipo_operacao, count(*) as quantidade,
               min(ri.cfop) as cfop_repr, count(distinct ri.cfop) as n_cfops
        from relatorio_pc_itens ri
        join cst_regra_alerta_pc r on r.cst = ri.cst and r.tipo_operacao = ri.tipo_operacao
        where ri.competencia_id = :cid and ri.empresa_id = :eid
        group by ri.cst, ri.tipo_operacao
        order by ri.cst
    """), {"cid": competencia_id, "eid": empresa_id}).mappings().all()

    for a in achados:
        chave = f'cst:{a["cst"]}|op:{a["tipo_operacao"]}'
        cfops_nota = f'CFOP {a["cfop_repr"]}' if a["n_cfops"] == 1 else f'{a["n_cfops"]} CFOPs diferentes'
        descricao = (
            f'CST {a["cst"]} apareceu {a["quantidade"]}× no Relatório 1096 ({cfops_nota}) — alerta '
            f'informativo, não bloqueia o cálculo (que roda sobre a Rotina 1024), mas vale conferir a '
            f'operação.'
        )
        _inserir_grupo(session, competencia_id, empresa_id, "cst_regra_alerta", a["cst"], a["cfop_repr"],
                       None, a["tipo_operacao"], descricao, chave, a["quantidade"], excecoes)


# --------------------------------------------------------------------------------------- Revisão / aprendizado
def registrar_revisao(session, inconsistencia_id, empresa_id, tipo, chave_agrupamento, ncm, cfop,
                       tipo_operacao, novo_status, justificativa, replicar, usuario=None):
    """Revisa/ignora um grupo de inconsistência (ou só salva a justificativa, sem mudar status, se
    `novo_status` for None) — mesmo padrão do módulo ICMS normal. Se `replicar` for True, grava/atualiza uma
    exceção em excecoes_inconsistencia_pc: nas próximas importações do 1096 desta filial, o mesmo grupo
    (chave_agrupamento) já nasce revisado com esta justificativa, sem pedir revisão de novo. Exige
    justificativa não vazia quando replicar=True (mesma trava do ICMS)."""
    if replicar and not (justificativa or "").strip():
        raise ValueError("Para replicar nas próximas apurações, escreva a justificativa antes.")

    usuario = usuario or {}
    status_final = novo_status  # None = mantém o status atual, só atualiza a justificativa
    if status_final:
        session.execute(text("""
            update inconsistencias_pc
            set status = :status, revisado_por = :uid, revisado_em = now(), justificativa = :just
            where id = :id
        """), {"status": status_final, "uid": usuario.get("id"), "just": (justificativa or "").strip() or None,
               "id": inconsistencia_id})
    else:
        session.execute(text("""
            update inconsistencias_pc set justificativa = :just where id = :id
        """), {"just": (justificativa or "").strip() or None, "id": inconsistencia_id})

    if replicar:
        session.execute(text("""
            insert into excecoes_inconsistencia_pc
                (empresa_id, tipo, chave_agrupamento, ncm, cfop, tipo_operacao, justificativa, ativa,
                 criado_por, criado_por_email)
            values (:eid, :tipo, :chave, :ncm, :cfop, :top, :just, true, :uid, :email)
            on conflict (empresa_id, tipo, chave_agrupamento) do update
                set justificativa = excluded.justificativa, ativa = true, created_at = now(),
                    criado_por = excluded.criado_por, criado_por_email = excluded.criado_por_email
        """), {
            "eid": empresa_id, "tipo": tipo, "chave": chave_agrupamento, "ncm": ncm, "cfop": cfop,
            "top": tipo_operacao, "just": justificativa.strip(), "uid": usuario.get("id"),
            "email": usuario.get("email"),
        })
    session.commit()


def carregar_excecoes(session, empresa_ids):
    """Todas as exceções (ativas e desativadas) das filiais informadas, mais recentes primeiro — usada pela
    tela de gestão de exceções conhecidas. Recebe uma lista porque a apuração de PIS/COFINS é por GRUPO
    (várias filiais), diferente do ICMS normal (uma filial só) — mostra de qual filial é cada exceção."""
    empresa_ids = list(empresa_ids)
    if not empresa_ids:
        return []
    placeholders = ", ".join(f":e{i}" for i in range(len(empresa_ids)))
    params = {f"e{i}": eid for i, eid in enumerate(empresa_ids)}
    rows = session.execute(text(f"""
        select x.id, x.empresa_id, x.tipo, x.ncm, x.cfop, x.tipo_operacao, x.chave_agrupamento,
               x.justificativa, x.ativa, x.criado_por_email, x.created_at,
               coalesce(e.filial_winthor, '(não identificada)') as filial
        from excecoes_inconsistencia_pc x
        left join empresas e on e.id = x.empresa_id
        where x.empresa_id in ({placeholders})
        order by x.ativa desc, x.created_at desc
    """), params).mappings().all()
    return rows


def definir_excecao_ativa(session, excecao_id, ativa):
    session.execute(text("update excecoes_inconsistencia_pc set ativa = :ativa where id = :id"),
                     {"ativa": ativa, "id": excecao_id})
    session.commit()


# --------------------------------------------------------------------------------------- Ajuste manual (log-only)
def registrar_ajuste_cst(session, inconsistencia_id, cst_corrigido, observacao=None, usuario=None):
    """Registra uma correção manual de CST feita na tela — SÓ HISTÓRICO. Não atualiza relatorio_pc_itens,
    não recalcula nada: a apuração continua 100% sobre a Rotina 1024. Serve pra virar uma lista de "o que
    corrigir no Winthor" (rastreável: quem, quando, de que CST original pra que CST corrigido). Marca a
    inconsistência como status='ajustado' (distinto de 'revisado', que é só "vi e não vou mexer"). Essa
    ação é específica do PIS/COFINS (não existe no ICMS) e continua disponível junto com o fluxo de
    revisar/ignorar/replicar descrito acima — são independentes."""
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
