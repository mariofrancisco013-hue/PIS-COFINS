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

ESTRUTURA (18/08/2026, à noite — segundo pedido do mesmo dia: "quero mais ou menos essa estrutura",
mostrando a tela do ICMS Normal inteira, com banner de status, abas de cadastro e "CFOPs sem Validação"),
mais dois complementos, ver sql/006_planilha_editavel_pc.sql:
- "CFOPs sem checagem de CST" (cfops_sem_checagem_cst_pc, por filial): equivalente a cfops_sem_validacao do
  ICMS Normal — marca um CFOP inteiro como "não precisa checar CST" para uma filial, e as 3 funções
  _checar_* abaixo passam a ignorar itens desse CFOP. Diferença para as exceções por chave_agrupamento
  acima: aqui é "não checar mais este CFOP", lá é "não avisar de novo sobre este erro específico" — os dois
  mecanismos convivem, um não substitui o outro.
- CRUD das tabelas de regra (cst_regra_cfop_pc/cst_regra_ncm_pc/cst_regra_alerta_pc) pela própria tela, em
  vez de só por `insert` direto no banco — ver `listar_regras_*`/`salvar_regras_*` mais abaixo. As regras
  continuam GLOBAIS (não por filial), diferente do cadastro de CFOPs sem checagem.
"""
import pandas as pd
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


def cfops_excluidos_checagem(session, empresa_id):
    """Lista de códigos de CFOP marcados como "sem checagem de CST" para esta filial — usada pelas 3 funções
    _checar_* abaixo para ignorar itens desses CFOPs."""
    return session.execute(text(
        "select cfop from cfops_sem_checagem_cst_pc where empresa_id = :eid"
    ), {"eid": empresa_id}).scalars().all()


def _clausula_cfops_excluidos(session, empresa_id, alias, params, prefix="cfx"):
    """Monta `and not (<alias>.cfop in (...))` com placeholders dinâmicos (mesma convenção do resto do
    projeto — ver nota em planilha_pc._where_empresas) para os CFOPs marcados como "sem checagem" desta
    filial. Sem CFOP marcado, devolve string vazia (não filtra nada)."""
    cfops = cfops_excluidos_checagem(session, empresa_id)
    if not cfops:
        return ""
    placeholders = ", ".join(f":{prefix}{i}" for i in range(len(cfops)))
    for i, c in enumerate(cfops):
        params[f"{prefix}{i}"] = c
    return f" and not ({alias}.cfop in ({placeholders}))"


def listar_cfops_sem_checagem(session, empresa_id):
    rows = session.execute(text("""
        select c.id, c.cfop, cp.descricao, c.motivo, c.criado_por_email, c.created_at
        from cfops_sem_checagem_cst_pc c
        left join cfop_pis_cofins cp on cp.codigo = c.cfop
        where c.empresa_id = :eid
        order by c.cfop
    """), {"eid": empresa_id}).mappings().all()
    return rows


def salvar_cfops_sem_checagem(session, empresa_id, df_original, df_editado, usuario=None):
    """Grade editável com `num_rows='dynamic'` — linha nova (sem id) insere, linha removida na grade
    exclui. Mesmo padrão de `ncm_tributado.py`/`cfops_sem_validacao.py` do módulo ICMS Normal."""
    ids_originais = set(df_original["id"].dropna().astype(int)) if not df_original.empty else set()
    ids_editados = set(df_editado["id"].dropna().astype(int)) if "id" in df_editado.columns else set()

    removidos = ids_originais - ids_editados
    for cfop_id in removidos:
        session.execute(text("delete from cfops_sem_checagem_cst_pc where id = :id"), {"id": int(cfop_id)})

    incluidos = 0
    novas = df_editado[df_editado["id"].isna()] if "id" in df_editado.columns else df_editado
    usuario = usuario or {}
    for _, row in novas.iterrows():
        cfop_raw = row.get("cfop")
        if pd.isna(cfop_raw):
            continue
        session.execute(text("""
            insert into cfops_sem_checagem_cst_pc (empresa_id, cfop, motivo, criado_por, criado_por_email)
            values (:eid, :cfop, :motivo, :uid, :email)
            on conflict (empresa_id, cfop) do update
                set motivo = excluded.motivo, criado_por = excluded.criado_por,
                    criado_por_email = excluded.criado_por_email
        """), {
            "eid": empresa_id, "cfop": int(cfop_raw), "motivo": row.get("motivo") or None,
            "uid": usuario.get("id"), "email": usuario.get("email"),
        })
        incluidos += 1

    session.commit()
    return {"incluidos": incluidos, "removidos": len(removidos)}


def registrar_inconsistencias_cst_regras(session, competencia_id, empresa_id):
    """Roda as 3 checagens (CFOP, NCM, alerta) para os itens do 1096 desta filial nesta competência.
    Escopado por empresa_id, mesmo padrão do resto do módulo: recria do zero só os achados desta filial,
    sem tocar em outras filiais do mesmo grupo. Chame depois de importar_arquivo (dentro de
    importacao_pc.importar_1096, junto com _registrar_inconsistencias_1096) e também depois de salvar
    edições na grade de Saída/Entrada (ver planilha_pc.recalcular_inconsistencias_apos_edicao)."""
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
    params = {"cid": competencia_id, "eid": empresa_id}
    clausula_excluidos = _clausula_cfops_excluidos(session, empresa_id, "ri", params)
    achados = session.execute(text(f"""
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
          {clausula_excluidos}
        group by ri.cfop, ri.cst, ri.tipo_operacao
        order by ri.cfop, ri.cst
    """), params).mappings().all()

    # Duas situações bem diferentes, tratadas separadas — pedido do usuário em 18/08/2026 ("agrupar os NCMs
    # por erro em um único alerta", aplicado aqui também por simetria/consistência, ver _checar_regra_ncm):
    # 1) O CFOP TEM regra e o CST bateu errado: fica um grupo por CFOP (faz sentido — cada CFOP tem um CST
    #    esperado diferente, agrupar CFOPs diferentes aqui misturaria coisas diferentes).
    # 2) O CFOP NÃO tem regra, mas o CST em si É um dos regrados nessa direção — antes virava um card por
    #    CFOP repetindo a mesma frase ("esse CST só é esperado em CFOPs específicos"); agora todos os CFOPs
    #    com esse mesmo CST fora da lista entram num alerta só, por CST + operação (a lista de CFOPs
    #    afetados fica na descrição). Ver planilha_pc.carregar_itens_editavel — o casamento da coluna
    #    "⚠️ Inconsistência" da grade foi ajustado para aceitar `cfop is null` neste caso.
    for a in achados:
        if a["cst_esperado"] is None:
            continue
        chave = f'cfop:{a["cfop"]}|cst:{a["cst"]}|op:{a["tipo_operacao"]}'
        descricao = (
            f'CFOP {a["cfop"]} deveria estar com CST {a["cst_esperado"]} (regra CFOP × CST) mas veio '
            f'com CST {a["cst"]} no Relatório 1096 — confira o cadastro do produto/operação no Winthor.'
        )
        _inserir_grupo(session, competencia_id, empresa_id, "cst_regra_cfop", a["cst"], a["cfop"], None,
                       a["tipo_operacao"], descricao, chave, a["quantidade"], excecoes)

    por_cst = {}
    for a in achados:
        if a["cst_esperado"] is not None:
            continue
        g = por_cst.setdefault((a["cst"], a["tipo_operacao"]), {"cfops": [], "quantidade": 0})
        g["cfops"].append(a["cfop"])
        g["quantidade"] += a["quantidade"]
    for (cst, tipo_operacao), g in por_cst.items():
        chave = f'cst:{cst}|op:{tipo_operacao}'
        cfops_unicos = sorted(set(g["cfops"]))
        n = len(cfops_unicos)
        amostra = ", ".join(str(c) for c in cfops_unicos[:8]) + (f" e mais {n - 8}" if n > 8 else "")
        descricao = (
            f'CST {cst} apareceu no Relatório 1096 em {n} CFOP(s) diferente(s) ({amostra}), mas esse CST só '
            f'é esperado em CFOPs específicos (regra CFOP × CST) — confira se o CFOP está certo para esses '
            f'itens.'
        )
        _inserir_grupo(session, competencia_id, empresa_id, "cst_regra_cfop", cst, None, None,
                       tipo_operacao, descricao, chave, g["quantidade"], excecoes)


def _checar_regra_ncm(session, competencia_id, empresa_id):
    excecoes = _buscar_excecoes_ativas(session, empresa_id, "cst_regra_ncm")
    params = {"cid": competencia_id, "eid": empresa_id}
    clausula_excluidos = _clausula_cfops_excluidos(session, empresa_id, "ri", params)
    achados = session.execute(text(f"""
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
          {clausula_excluidos}
        group by ri.ncm, ri.cst, ri.tipo_operacao
        order by ri.ncm, ri.cst
    """), params).mappings().all()

    # Mesma distinção de duas situações explicada em _checar_regra_cfop (pedido do usuário em 18/08/2026,
    # "agrupar os NCMs por erro em um único alerta" — este é exatamente o caso que motivou o pedido, com o
    # screenshot mostrando um card por NCM repetindo a mesma frase para o mesmo CST 74 fora da lista):
    # 1) O NCM TEM regra e o CST bateu errado: continua um grupo por NCM (cada NCM pode esperar um CST
    #    diferente, agrupar NCMs diferentes aqui misturaria coisas diferentes).
    # 2) O NCM NÃO tem regra, mas o CST em si É um dos regrados nessa direção: agora todos os NCMs com esse
    #    mesmo CST fora da lista entram num alerta só, por CST + operação (lista de NCMs afetados na
    #    descrição). Ver planilha_pc.carregar_itens_editavel — o casamento da coluna "⚠️ Inconsistência" da
    #    grade foi ajustado para aceitar `ncm is null` neste caso.
    for a in achados:
        if a["cst_esperado"] is None:
            continue
        chave = f'ncm:{a["ncm"]}|cst:{a["cst"]}|op:{a["tipo_operacao"]}'
        cfops_nota = f' (CFOP {a["cfop_repr"]})' if a["n_cfops"] == 1 else f' ({a["n_cfops"]} CFOPs diferentes)'
        descricao = (
            f'NCM {a["ncm"]} deveria estar com CST {a["cst_esperado"]} (regra NCM × CST) mas veio com '
            f'CST {a["cst"]} no Relatório 1096{cfops_nota} — confira o cadastro do produto no Winthor.'
        )
        _inserir_grupo(session, competencia_id, empresa_id, "cst_regra_ncm", a["cst"], a["cfop_repr"],
                       a["ncm"], a["tipo_operacao"], descricao, chave, a["quantidade"], excecoes)

    por_cst = {}
    for a in achados:
        if a["cst_esperado"] is not None:
            continue
        g = por_cst.setdefault((a["cst"], a["tipo_operacao"]), {"ncms": [], "quantidade": 0})
        g["ncms"].append(a["ncm"])
        g["quantidade"] += a["quantidade"]
    for (cst, tipo_operacao), g in por_cst.items():
        chave = f'cst:{cst}|op:{tipo_operacao}'
        ncms_unicos = sorted(set(g["ncms"]))
        n = len(ncms_unicos)
        amostra = ", ".join(str(c) for c in ncms_unicos[:8]) + (f" e mais {n - 8}" if n > 8 else "")
        descricao = (
            f'CST {cst} apareceu no Relatório 1096 em {n} NCM(s) diferente(s) ({amostra}), mas esse CST só '
            f'é esperado em NCMs específicos (regra NCM × CST) — confira se o NCM está certo para esses '
            f'itens.'
        )
        _inserir_grupo(session, competencia_id, empresa_id, "cst_regra_ncm", cst, None, None,
                       tipo_operacao, descricao, chave, g["quantidade"], excecoes)


def _checar_alerta(session, competencia_id, empresa_id):
    excecoes = _buscar_excecoes_ativas(session, empresa_id, "cst_regra_alerta")
    params = {"cid": competencia_id, "eid": empresa_id}
    clausula_excluidos = _clausula_cfops_excluidos(session, empresa_id, "ri", params)
    achados = session.execute(text(f"""
        select ri.cst, ri.tipo_operacao, count(*) as quantidade,
               min(ri.cfop) as cfop_repr, count(distinct ri.cfop) as n_cfops
        from relatorio_pc_itens ri
        join cst_regra_alerta_pc r on r.cst = ri.cst and r.tipo_operacao = ri.tipo_operacao
        where ri.competencia_id = :cid and ri.empresa_id = :eid
          {clausula_excluidos}
        group by ri.cst, ri.tipo_operacao
        order by ri.cst
    """), params).mappings().all()

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


# --------------------------------------------------------------------------------------- Ajuste manual de CST
# Até 20/08/2026 (sessão de continuação) isso era só histórico (registrar_ajuste_cst, mantida abaixo pros
# casos de escopo ambíguo). Pedido do usuário no mesmo dia ("que esses ajustes fiquem salvos para ajuste no
# sistema"): quando dá pra saber com segurança QUAIS itens do Relatório 1096 geraram a inconsistência,
# `aplicar_ajuste_cst` agora corrige de verdade o CST em relatorio_pc_itens (mantendo o CST original no
# histórico de ajustes_cst_pc) e quem chama (a página) recalcula a apuração na sequência — ver
# `escopo_ajuste_seguro` pra quando isso é seguro fazer.
def escopo_ajuste_seguro(row) -> bool:
    """True quando dá pra identificar, sem ambiguidade, o conjunto EXATO de itens de `relatorio_pc_itens`
    por trás da inconsistência — condição pra `aplicar_ajuste_cst` poder corrigir o CST de verdade:

    - 'cst_nao_mapeado': sempre seguro — o CST em si não existe na tabela oficial (ver
      importacao_pc._registrar_inconsistencias_1096), então TODO item desta filial/competência/operação com
      esse CST literal está errado da mesma forma; não há "alguns itens certos, outros errados" dentro do
      grupo.
    - 'cst_regra_cfop' / 'cst_regra_ncm': seguro só no caso 1 de `_checar_regra_cfop`/`_checar_regra_ncm`
      (`cst_esperado` não era None quando a inconsistência foi gerada) — aí a linha tem um CFOP ou NCM
      específico gravado. O caso 2 (mesmo CST espalhado por vários CFOPs/NCMs diferentes, sem um "CST
      esperado" único) grava cfop=None e ncm=None nesses dois tipos — ver `_inserir_grupo` nas duas funções
      — então não há um CFOP/NCM único pra escopar a correção; aplicar mudaria itens que talvez precisassem
      de CSTs diferentes entre si.
    - 'cst_regra_alerta': nunca seguro — `_checar_alerta` agrupa só por (cst, tipo_operacao), sem CFOP/NCM
      nenhum (o `cfop_repr` salvo na linha é só uma AMOSTRA pra descrição, "min(cfop)" entre vários
      diferentes — não é o escopo real do grupo).
    - qualquer outro tipo (ex.: 'cfop_sem_grupo'): não tem CST pra ajustar, nem chega a aparecer nesta tela
      (ver TIPOS_COM_CST_AJUSTAVEL nas páginas).

    `row` pode ser um dict/Row do SQLAlchemy (cfop/ncm ausentes = None) OU uma linha de DataFrame do pandas
    (cfop/ncm ausentes = NaN, um float) — vindo da tela, que monta o card a partir de um `df_inc.iterrows()`.
    Usa `pd.notna()` (não `is not None`) pra tratar os dois casos igual: `NaN is not None` dá True em Python
    puro (são objetos diferentes), o que faria esta função achar por engano que uma linha SEM CFOP/NCM tinha
    um CFOP/NCM válido — um bug que aplicaria a correção com escopo largo demais."""
    tipo = row["tipo"]
    if tipo == "cst_nao_mapeado":
        return True
    if tipo == "cst_regra_cfop":
        return pd.notna(row["cfop"])
    if tipo == "cst_regra_ncm":
        return pd.notna(row["ncm"])
    return False


def aplicar_ajuste_cst(session, inconsistencia_id, cst_corrigido, observacao=None, usuario=None):
    """Corrige de verdade o CST dos itens de `relatorio_pc_itens` por trás desta inconsistência, grava o
    histórico em `ajustes_cst_pc` (mesma tabela/formato de antes) e marca a inconsistência como 'ajustado'.
    NÃO recalcula a apuração sozinha — quem chama (a página) roda `calcular_apuracao_pc`/
    `salvar_apuracao_pc` (ou os equivalentes do Presumido) logo em seguida, mesmo botão que já existia
    ("🔄 Calcular apuração"). Levanta ValueError se `escopo_ajuste_seguro` for False — chame
    `registrar_ajuste_cst` (log-only) nesse caso, é o único caminho seguro pra escopo ambíguo.

    Retorna {"n_itens_corrigidos": int} — pode ser 0 numa borda rara (o item que gerou a inconsistência foi
    editado/excluído manualmente na grade Entrada/Saída depois de a inconsistência ter sido gerada e antes
    de o ajuste ser aplicado); não é tratado como erro, só reflete a realidade atual dos dados."""
    row = session.execute(text("""
        select competencia_id, empresa_id, tipo, cst, cfop, ncm, tipo_operacao
        from inconsistencias_pc where id = :id
    """), {"id": inconsistencia_id}).mappings().first()
    if row is None:
        raise ValueError("Inconsistência não encontrada.")
    if not escopo_ajuste_seguro(row):
        raise ValueError(
            "Esta inconsistência não tem um CFOP ou NCM específico associado (o mesmo CST aparece em itens "
            "de origens diferentes) — aplicar uma correção automática arriscaria mudar itens que talvez "
            "precisassem de um CST diferente entre si. Use 'Registrar ajuste (só histórico)' e corrija "
            "item a item no Winthor, ou cadastre uma Regra de CST × CFOP/NCM (aba 🔖) para a próxima "
            "importação já vir certa."
        )

    # Escopo por tipo — ver docstring de escopo_ajuste_seguro pra por que NCM não soma cláusula de CFOP
    # (cfop_repr é só amostra) e por que cst_nao_mapeado não tem cláusula de CFOP/NCM nenhuma.
    params = {
        "cid": row["competencia_id"], "eid": row["empresa_id"], "top": row["tipo_operacao"],
        "cst_orig": row["cst"], "cst_novo": cst_corrigido,
    }
    clausula = ""
    if row["tipo"] == "cst_regra_cfop":
        clausula = " and cfop = :cfop"
        params["cfop"] = row["cfop"]
    elif row["tipo"] == "cst_regra_ncm":
        clausula = " and ncm = :ncm"
        params["ncm"] = row["ncm"]

    resultado = session.execute(text(f"""
        update relatorio_pc_itens
        set cst = :cst_novo
        where competencia_id = :cid and empresa_id = :eid and tipo_operacao = :top and cst = :cst_orig
        {clausula}
    """), params)
    n_itens = resultado.rowcount

    usuario = usuario or {}
    session.execute(text("""
        insert into ajustes_cst_pc (inconsistencia_id, cst_original, cst_corrigido, observacao, ajustado_por,
                                     aplicado)
        values (:iid, :original, :corrigido, :obs, :por, true)
    """), {"iid": inconsistencia_id, "original": row["cst"], "corrigido": cst_corrigido, "obs": observacao,
           "por": usuario.get("id")})
    session.execute(text("""
        update inconsistencias_pc
        set status = 'ajustado', revisado_por = :por, revisado_em = now()
        where id = :id
    """), {"id": inconsistencia_id, "por": usuario.get("id")})
    session.commit()
    return {"n_itens_corrigidos": n_itens}


def registrar_ajuste_cst(session, inconsistencia_id, cst_corrigido, observacao=None, usuario=None):
    """Registra uma correção manual de CST feita na tela — SÓ HISTÓRICO. Não atualiza relatorio_pc_itens,
    não recalcula nada: a apuração continua 100% sobre a Rotina 1024. Serve pra virar uma lista de "o que
    corrigir no Winthor" (rastreável: quem, quando, de que CST original pra que CST corrigido). Usado só
    quando `escopo_ajuste_seguro` é False (ver `aplicar_ajuste_cst`) — nesses casos aplicar de verdade
    arriscaria corrigir itens que não deveriam mudar. Marca a inconsistência como status='ajustado'
    (distinto de 'revisado', que é só "vi e não vou mexer")."""
    usuario = usuario or {}
    original = session.execute(
        text("select cst from inconsistencias_pc where id = :id"), {"id": inconsistencia_id}
    ).scalar()
    session.execute(text("""
        insert into ajustes_cst_pc (inconsistencia_id, cst_original, cst_corrigido, observacao, ajustado_por,
                                     aplicado)
        values (:iid, :original, :corrigido, :obs, :por, false)
    """), {"iid": inconsistencia_id, "original": original, "corrigido": cst_corrigido, "obs": observacao,
           "por": usuario.get("id")})
    session.execute(text("""
        update inconsistencias_pc
        set status = 'ajustado', revisado_por = :por, revisado_em = now()
        where id = :id
    """), {"id": inconsistencia_id, "por": usuario.get("id")})
    session.commit()


# --------------------------------------------------------------------------------------- Cadastro de regras
# (18/08/2026, à noite) — CRUD pela tela das tabelas cst_regra_cfop_pc/cst_regra_ncm_pc/cst_regra_alerta_pc
# (ver sql/004_regras_cst_pc.sql), em vez de só `insert` direto no banco. GLOBAIS (não por filial, diferente
# do cadastro de CFOPs sem checagem acima) — mesmo padrão de grade editável `num_rows='dynamic'` do módulo
# ICMS Normal (linha nova insere, linha removida na grade exclui; o CFOP/NCM/CST em si não é editável depois
# de criado, só a observação — mais simples que suportar edição in-place).
def listar_regras_cfop(session):
    rows = session.execute(text("""
        select r.id, r.cst, r.cfop, r.tipo_operacao, r.observacao, r.created_at
        from cst_regra_cfop_pc r order by r.tipo_operacao, r.cfop
    """)).mappings().all()
    return rows


def salvar_regras_cfop(session, df_original, df_editado):
    # colunas_conflito = só (cfop, tipo_operacao) — é ISSO que a unique constraint da tabela cobre (ver
    # sql/004_regras_cst_pc.sql: unique(cfop, tipo_operacao)), não as 3 colunas de colunas_chave. "cst" é o
    # VALOR da regra (o CST esperado), não faz parte da identidade dela — daí um CFOP só poder ter UM CST
    # esperado por direção, que é literalmente o que a regra representa.
    return _salvar_regra_generica(
        session, "cst_regra_cfop_pc", ["cst", "cfop", "tipo_operacao"], ["cfop", "tipo_operacao"],
        df_original, df_editado,
    )


def listar_regras_ncm(session):
    rows = session.execute(text("""
        select r.id, r.cst, r.ncm, r.tipo_operacao, r.observacao, r.created_at
        from cst_regra_ncm_pc r order by r.tipo_operacao, r.ncm
    """)).mappings().all()
    return rows


def salvar_regras_ncm(session, df_original, df_editado):
    # Mesmo raciocínio de salvar_regras_cfop: a unique constraint é (ncm, tipo_operacao), não as 3 colunas.
    return _salvar_regra_generica(
        session, "cst_regra_ncm_pc", ["cst", "ncm", "tipo_operacao"], ["ncm", "tipo_operacao"],
        df_original, df_editado,
    )


def listar_regras_alerta(session):
    rows = session.execute(text("""
        select r.id, r.cst, r.tipo_operacao, r.observacao, r.created_at
        from cst_regra_alerta_pc r order by r.tipo_operacao, r.cst
    """)).mappings().all()
    return rows


def salvar_regras_alerta(session, df_original, df_editado):
    # Aqui SIM colunas_chave e colunas_conflito coincidem: a identidade da regra "sempre-alerta" é
    # (cst, tipo_operacao) — não há um "valor esperado" separado do CST, como nas outras duas.
    return _salvar_regra_generica(
        session, "cst_regra_alerta_pc", ["cst", "tipo_operacao"], ["cst", "tipo_operacao"],
        df_original, df_editado,
    )


def _int_ou_valor(col, v):
    return int(v) if col in ("cst", "cfop") else v


def _salvar_regra_generica(session, tabela, colunas_chave, colunas_conflito, df_original, df_editado):
    """Linha nova (sem id) insere; linha removida na grade exclui; qualquer coluna de uma linha EXISTENTE
    que tiver mudado (inclusive o próprio CST/CFOP/NCM digitado na grade, não só a observação) é atualizada
    por id. Retorna {"incluidos", "removidos", "atualizados"}. Não recalcula inconsistências sozinha — como
    as regras são globais (afetam todas as filiais), quem chama decide se quer rodar
    `registrar_inconsistencias_cst_regras` de novo (a tela mostra um aviso pedindo para recalcular
    manualmente, mesmo padrão de "Calcular apuração" do restante do app).

    `colunas_chave` (validação de linha nova) e `colunas_conflito` (o que a unique constraint da tabela
    realmente cobre — ver sql/004_regras_cst_pc.sql) são conjuntos DIFERENTES para cst_regra_cfop_pc/
    cst_regra_ncm_pc: a unique é só (cfop, tipo_operacao) / (ncm, tipo_operacao) — "cst" é o VALOR da regra,
    não faz parte da identidade dela. Achado na revisão antes da entrega: usar colunas_chave como alvo do
    `on conflict` gerava `on conflict (cst, cfop, tipo_operacao)`, que não bate com NENHUMA unique/exclusion
    constraint real da tabela — o Postgres rejeita isso com erro ("no unique or exclusion constraint
    matching the ON CONFLICT specification"), quebrando a tela ao tentar incluir qualquer regra nova."""
    ids_originais = set(df_original["id"].dropna().astype(int)) if not df_original.empty else set()
    ids_editados = set(df_editado["id"].dropna().astype(int)) if "id" in df_editado.columns else set()

    removidos = ids_originais - ids_editados
    for rid in removidos:
        session.execute(text(f"delete from {tabela} where id = :id"), {"id": int(rid)})

    atualizados = 0
    colunas_editaveis = colunas_chave + ["observacao"]
    if not df_original.empty:
        orig = df_original.set_index("id")
        for rid in (ids_originais & ids_editados):
            linha_edit = df_editado[df_editado["id"] == rid]
            if linha_edit.empty:
                continue
            linha_edit = linha_edit.iloc[0]
            valores, mudou = {}, False
            for col in colunas_editaveis:
                v_orig = orig.loc[rid, col] if col in orig.columns else None
                v_edit = linha_edit.get(col)
                v_orig_norm = None if pd.isna(v_orig) else v_orig
                v_edit_norm = None if pd.isna(v_edit) else v_edit
                if v_orig_norm != v_edit_norm:
                    mudou = True
                valores[col] = _int_ou_valor(col, v_edit_norm) if v_edit_norm is not None else None
            if mudou:
                sets_sql = ", ".join(f"{c} = :{c}" for c in colunas_editaveis)
                session.execute(text(f"update {tabela} set {sets_sql} where id = :id"),
                                 {**valores, "id": int(rid)})
                atualizados += 1

    incluidos = 0
    novas = df_editado[df_editado["id"].isna()] if "id" in df_editado.columns else df_editado
    colunas_sql = ", ".join(colunas_chave + ["observacao"])
    placeholders_sql = ", ".join(f":{c}" for c in colunas_chave) + ", :obs"
    conflito_sql = ", ".join(colunas_conflito)
    # No conflito, atualiza toda coluna de colunas_chave que NÃO faz parte da identidade (ex: "cst" em
    # cst_regra_cfop_pc/cst_regra_ncm_pc) — reinserir a mesma combinação CFOP+operação com um CST diferente
    # deve atualizar qual CST é esperado, não só a observação.
    sets_conflito = ", ".join(
        f"{c} = excluded.{c}" for c in colunas_chave if c not in colunas_conflito
    )
    sets_conflito = (sets_conflito + ", " if sets_conflito else "") + "observacao = excluded.observacao"
    for _, row in novas.iterrows():
        valores = {}
        valido = True
        for col in colunas_chave:
            v = row.get(col)
            if pd.isna(v) or (isinstance(v, str) and not v.strip()):
                valido = False
                break
            valores[col] = _int_ou_valor(col, v)
        if not valido:
            continue
        valores["obs"] = row.get("observacao") or None
        session.execute(text(f"""
            insert into {tabela} ({colunas_sql}) values ({placeholders_sql})
            on conflict ({conflito_sql}) do update set {sets_conflito}
        """), valores)
        incluidos += 1

    session.commit()
    return {"incluidos": incluidos, "removidos": len(removidos), "atualizados": atualizados}


def carregar_historico_ajustes(session, competencia_id):
    """Uma linha por ajuste manual registrado nesta competência — usada pra exportar/consultar a lista de
    ajustes de CST. `aplicado` (coluna nova, migração sql/010) distingue os dois caminhos desde 20/08/2026:
    True = corrigido de verdade em relatorio_pc_itens (aplicar_ajuste_cst, escopo inequívoco); False = só
    histórico/checklist pra corrigir manualmente no Winthor (registrar_ajuste_cst, escopo ambíguo). Ajustes
    de ANTES desta migração ficam com aplicado=false por padrão — é o comportamento real deles (nenhum
    mexeu em relatorio_pc_itens)."""
    rows = session.execute(text("""
        select a.id, a.inconsistencia_id, a.cst_original, a.cst_corrigido, a.observacao, a.ajustado_em,
               coalesce(a.aplicado, false) as aplicado,
               i.cfop, i.ncm, i.tipo_operacao, i.descricao,
               coalesce(e.filial_winthor, '(não identificada)') as filial
        from ajustes_cst_pc a
        join inconsistencias_pc i on i.id = a.inconsistencia_id
        left join empresas e on e.id = i.empresa_id
        where i.competencia_id = :cid
        order by a.ajustado_em desc
    """), {"cid": competencia_id}).mappings().all()
    return rows
