"""
Leitura/edição em grade (estilo planilha) dos itens do Relatório 1096 (Entrada/Saída) — pedido do usuário
em 18/08/2026 ("quero mais ou menos essa estrutura", mostrando a Planilha de Entrada/Saída do módulo ICMS
Normal): mesmo padrão de `lib/planilha.py` daquele projeto (grade editável com `st.data_editor`, alterações
gravadas linha a linha com auditoria, visão Analítica/Sintética), adaptado para os dados do PIS/COFINS.

DIFERENÇA CRÍTICA em relação ao ICMS Normal — leia antes de mexer aqui: no ICMS Normal, editar a planilha
muda o CALCULADO da apuração (a apuração roda sobre `notas_fiscais_itens`). Aqui NÃO — `relatorio_pc_itens`
(Relatório 1096) é só CONFERÊNCIA desde a revisão de metodologia de 14/08/2026; a Apuração (linhas 1.x-11.x)
roda 100% sobre `resumo_1024_pc` (Rotina 1024) e nunca lê esta tabela. Editar um item aqui só recalcula:
(a) as inconsistências de CST × CFOP/NCM desta filial (`cst_regras_pc.registrar_inconsistencias_cst_regras`,
chamada pela página depois de salvar), e (b) a Conferência 1024×1096 (que já é calculada on-the-fly a cada
vez que a aba é aberta, não precisa de ação extra). Se um dia o usuário pedir para a Apuração também refletir
edições feitas aqui, isso é uma mudança de arquitetura que merece confirmação explícita antes de implementar
— não é o que foi pedido em 18/08/2026.

Também diferente do ICMS: aqui não há granularidade de NF nem coluna de parceiro/fornecedor (nem o 1096 nem
a Rotina 1024 trazem isso — ver metodologia), e a apuração é por GRUPO (várias filiais), não por uma filial
só — por isso as funções abaixo recebem uma LISTA de `empresa_ids` (todas as filiais do grupo/competência),
não uma filial única, e a grade mostra uma coluna "Filial" para diferenciar de onde veio cada item.

O CST **não é editável na grade** — de propósito: já existe um fluxo dedicado para correção de CST (ver
`cst_regras_pc.py` — cards de inconsistência com revisão/replicar/exceções aprendidas, mais o registro de
ajuste com histórico). Duplicar isso como uma coluna editável aqui criaria dois jeitos diferentes de "corrigir
CST" com histórico e comportamento diferentes — a grade edita CFOP, NCM e os valores; CST continua só
naquele outro fluxo.
"""
import numpy as np
import pandas as pd
from sqlalchemy import text

COLUNAS_EDITAVEIS = [
    "id", "produto_codigo", "ncm", "cfop", "quantidade", "valor_contabil", "valor_desconto", "valor_itens",
    "valor_tributado", "aliq_pis", "valor_pis", "aliq_cofins", "valor_cofins", "valor_nao_tributado",
]
# Colunas só de leitura, calculadas via join — não fazem parte de COLUNAS_EDITAVEIS porque salvar_itens_
# editados não deve tentar gravar nelas.
COLUNAS_TODAS = COLUNAS_EDITAVEIS + ["empresa_id", "filial", "cst", "inconsistencia"]

# Rótulo curto por tipo de inconsistência, para mostrar direto na grade — mesmo espírito do
# LABELS_INCONSISTENCIA do módulo ICMS Normal (lib/planilha.py), adaptado aos tipos do PIS/COFINS. A
# descrição completa de cada achado continua só na aba Inconsistências / seção "Inconsistências desta
# operação".
LABELS_INCONSISTENCIA = {
    "cst_nao_mapeado": "CST fora da tabela oficial",
    "cfop_sem_grupo": "CFOP sem grupo cadastrado",
    "cst_regra_cfop": "CST × CFOP divergente",
    "cst_regra_ncm": "CST × NCM divergente",
    "cst_regra_alerta": "CST sempre-alerta",
}


def _formatar_inconsistencia(tipos_raw):
    """Mesmo cuidado do módulo ICMS (`lib/planilha.py::_formatar_inconsistencia`): `string_agg` NULL vira
    NaN (float) no pandas, e `bool(float('nan'))` é True em Python — por isso `pd.isna()`, não `if not`."""
    if pd.isna(tipos_raw):
        return None
    labels = [LABELS_INCONSISTENCIA.get(t, t) for t in str(tipos_raw).split(",")]
    return "⚠️ " + "; ".join(labels)


def _where_empresas(empresa_ids, alias, params, prefix):
    """Monta um `alias.empresa_id in (:p0, :p1, ...)` com placeholders dinâmicos — mesma convenção já usada
    no resto do projeto (ex: `importacao_pc.checar_duplicacao`, `cst_regras_pc.carregar_excecoes`), em vez
    de `= any(:lista)` do Postgres, por consistência com o restante do código. `empresa_ids` vazio devolve
    uma condição sempre falsa (nenhuma filial = nenhum item), em vez de gerar SQL inválido com `in ()`."""
    ids = list(empresa_ids)
    if not ids:
        return "false"
    placeholders = ", ".join(f":{prefix}{i}" for i in range(len(ids)))
    for i, eid in enumerate(ids):
        params[f"{prefix}{i}"] = eid
    return f"{alias}.empresa_id in ({placeholders})"


def _clausula_cfops_permitidos(cfops_permitidos, alias, params, prefix="cfp"):
    """Filtro OPCIONAL e genérico por uma lista fechada de CFOPs, no formato `<alias>.cfop in (...)` (SEM o
    "and" na frente — quem chama decide como encaixar, ver usos abaixo) — usado pela aba Entrada do Lucro
    Presumido (sessão de continuação, 20/08/2026: "na entrada considerar somente CFOP de devolução",
    confirmado com o usuário que isso vale também para a grade/resumos, não só para a geração automática de
    inconsistências — ver o equivalente `cst_regras_pc.clausula_entrada_permitida_presumido`, usado nas
    checagens). `None` (padrão) = sem filtro nenhum — mantém o Lucro Real e a aba Saída do Presumido 100%
    inalterados."""
    if cfops_permitidos is None:
        return ""
    cfops = list(cfops_permitidos)
    placeholders = ", ".join(f":{prefix}{i}" for i in range(len(cfops)))
    for i, c in enumerate(cfops):
        params[f"{prefix}{i}"] = c
    return f"{alias}.cfop in ({placeholders})"


def carregar_itens_editavel(session, competencia_id, tipo_operacao, empresa_ids, cfop_filtro=None,
                             ncm_filtro=None, busca=None, tipos_inconsistencia=None, limite=500,
                             cfops_permitidos=None):
    """Devolve (DataFrame, total_sem_filtro_de_limite) — itens do Relatório 1096 de TODAS as filiais do
    grupo passadas em `empresa_ids` (a apuração de PIS/COFINS é por grupo, não por filial única).

    `inconsistencia` é um resumo (rótulo curto) de toda inconsistência PENDENTE de fonte='relatorio_1096'
    que bate com este item — casado por (empresa_id, tipo_operacao) + CFOP/NCM/CST conforme o tipo (mesma
    chave usada para gerar cada uma em cst_regras_pc.py), sem precisar de uma tabela de vínculo por item
    (diferença do ICMS Normal, que usa `inconsistencia_itens` — não precisamos aqui porque as checagens do
    PIS/COFINS já são por CFOP/NCM/CST exato, não por nota fiscal individual).

    `cfops_permitidos` (opcional) restringe a uma lista fechada de CFOPs — ver `_clausula_cfops_permitidos`."""
    params = {"cid": competencia_id, "tipo": tipo_operacao}
    where = ["ri.competencia_id = :cid", "ri.tipo_operacao = :tipo", _where_empresas(empresa_ids, "ri", params, "eid")]
    clausula_permitidos = _clausula_cfops_permitidos(cfops_permitidos, "ri", params)
    if clausula_permitidos:
        where.append(clausula_permitidos)
    if cfop_filtro:
        where.append("ri.cfop = :cfop")
        params["cfop"] = cfop_filtro
    if ncm_filtro:
        where.append("ri.ncm ilike :ncm_filtro")
        params["ncm_filtro"] = f"{ncm_filtro.strip()}%"
    if busca:
        where.append("ri.produto_codigo ilike :busca")
        params["busca"] = f"%{busca}%"
    if tipos_inconsistencia:
        tipos_params = {}
        tipos_sql = ", ".join(f":tinc{i}" for i in range(len(tipos_inconsistencia)))
        for i, t in enumerate(tipos_inconsistencia):
            tipos_params[f"tinc{i}"] = t
        params.update(tipos_params)
        where.append(f"""exists (
            select 1 from inconsistencias_pc i2
            where i2.competencia_id = ri.competencia_id and i2.empresa_id = ri.empresa_id
              and i2.status = 'pendente' and i2.fonte = 'relatorio_1096' and i2.tipo in ({tipos_sql})
              and (
                  -- cfop/ncm is null = alerta consolidado por CST (achado "esse CST está fora da lista de
                  -- regras" — ver cst_regras_pc._checar_regra_cfop/_checar_regra_ncm, 18/08/2026: "agrupar
                  -- os NCMs/CFOPs por erro em um único alerta"). Casa com QUALQUER item deste CST/operação
                  -- que NÃO tenha ganhado sua própria regra específica depois (ver `not exists` abaixo,
                  -- correção de 21/08/2026: "Inclui o CFOP na regra mais a inconsistência não sai" — sem essa
                  -- checagem, um CFOP recém-cadastrado com regra própria continuava aparecendo flagado só
                  -- porque OUTRO CFOP com o mesmo CST ainda não tinha regra e mantinha o alerta consolidado
                  -- (cfop/ncm null) vivo, e o "or i2.cfop is null" batia com QUALQUER cfop, inclusive o já
                  -- resolvido).
                  (i2.tipo = 'cst_regra_cfop' and i2.cst = ri.cst and (
                      i2.cfop = ri.cfop
                      or (i2.cfop is null and not exists (
                          select 1 from cst_regra_cfop_pc r2
                          where r2.cfop = ri.cfop and r2.cst = ri.cst and r2.tipo_operacao = ri.tipo_operacao
                      ))
                  ))
                  or (i2.tipo = 'cst_regra_ncm' and i2.cst = ri.cst and (
                      i2.ncm = ri.ncm
                      or (i2.ncm is null and not exists (
                          select 1 from cst_regra_ncm_pc r2
                          where r2.ncm = ri.ncm and r2.cst = ri.cst and r2.tipo_operacao = ri.tipo_operacao
                      ))
                  ))
                  or (i2.tipo = 'cst_regra_alerta' and i2.cst = ri.cst)
                  or (i2.tipo = 'cst_nao_mapeado' and i2.cst = ri.cst)
                  or (i2.tipo = 'cfop_sem_grupo' and i2.cfop = ri.cfop)
              )
        )""")
    where_sql = " and ".join(where)

    total = session.execute(text(f"select count(*) from relatorio_pc_itens ri where {where_sql}"), params).scalar()

    params["limite"] = limite
    rows = session.execute(text(f"""
        select ri.id, ri.empresa_id, coalesce(e.filial_winthor, '(não identificada)') as filial,
               ri.produto_codigo, ri.ncm, ri.cst, ri.cfop, ri.quantidade, ri.valor_contabil,
               ri.valor_desconto, ri.valor_itens, ri.valor_tributado, ri.aliq_pis, ri.valor_pis,
               ri.aliq_cofins, ri.valor_cofins, ri.valor_nao_tributado,
               inc.tipos_pendentes
        from relatorio_pc_itens ri
        left join empresas e on e.id = ri.empresa_id
        left join lateral (
            select string_agg(distinct i.tipo, ',') as tipos_pendentes
            from inconsistencias_pc i
            where i.competencia_id = ri.competencia_id and i.empresa_id = ri.empresa_id
              and i.status = 'pendente' and i.fonte = 'relatorio_1096'
              and (
                  -- mesmo ajuste do bloco de tipos_inconsistencia acima (ver comentário lá, 21/08/2026):
                  -- alerta consolidado (cfop/ncm null) só casa com um item se ele ainda NÃO tiver ganhado
                  -- sua própria regra específica de CFOP/NCM — senão um CFOP recém-corrigido continua
                  -- aparecendo flagado na grade só por causa de outro CFOP com o mesmo CST ainda sem regra.
                  (i.tipo = 'cst_regra_cfop' and i.cst = ri.cst and (
                      i.cfop = ri.cfop
                      or (i.cfop is null and not exists (
                          select 1 from cst_regra_cfop_pc r2
                          where r2.cfop = ri.cfop and r2.cst = ri.cst and r2.tipo_operacao = ri.tipo_operacao
                      ))
                  ))
                  or (i.tipo = 'cst_regra_ncm' and i.cst = ri.cst and (
                      i.ncm = ri.ncm
                      or (i.ncm is null and not exists (
                          select 1 from cst_regra_ncm_pc r2
                          where r2.ncm = ri.ncm and r2.cst = ri.cst and r2.tipo_operacao = ri.tipo_operacao
                      ))
                  ))
                  or (i.tipo = 'cst_regra_alerta' and i.cst = ri.cst)
                  or (i.tipo = 'cst_nao_mapeado' and i.cst = ri.cst)
                  or (i.tipo = 'cfop_sem_grupo' and i.cfop = ri.cfop)
              )
        ) inc on true
        where {where_sql}
        order by ri.cfop, ri.id
        limit :limite
    """), params).mappings().all()

    # `pd.DataFrame(rows, columns=[...])` com `rows` vindo de `.mappings().all()` seleciona por NOME de
    # chave em cada linha (é um dict-like), não por posição — por isso esta lista precisa citar TODA coluna
    # que a query SELECT devolve (inclusive "cst"), não só as editáveis, senão a coluna some do DataFrame
    # (achado ao validar esta função com um harness antes de entregar: faltava "cst" aqui e explodia com
    # `KeyError` mais na frente, em `df[COLUNAS_TODAS]`).
    df = pd.DataFrame(rows, columns=["id", "empresa_id", "filial", "produto_codigo", "ncm", "cst", "cfop",
                                      "quantidade", "valor_contabil", "valor_desconto", "valor_itens",
                                      "valor_tributado", "aliq_pis", "valor_pis", "aliq_cofins",
                                      "valor_cofins", "valor_nao_tributado", "tipos_pendentes"])
    df["inconsistencia"] = df["tipos_pendentes"].apply(_formatar_inconsistencia) if not df.empty else []
    return df[COLUNAS_TODAS], total


def carregar_totalizador(session, competencia_id, tipo_operacao, empresa_ids, cfop_filtro=None, ncm_filtro=None,
                          cfops_permitidos=None):
    """Visão SINTÉTICA — totaliza por Filial + Código do Produto + CST, em vez de item a item (equivalente
    à visão "UF + Código do Produto + Alíquota" do ICMS Normal; aqui o CST faz esse papel de agrupador
    tributário, já que o PIS/COFINS não varia por UF).

    `cfops_permitidos` (opcional) restringe a uma lista fechada de CFOPs — ver `_clausula_cfops_permitidos`."""
    params = {"cid": competencia_id, "tipo": tipo_operacao}
    where = ["ri.competencia_id = :cid", "ri.tipo_operacao = :tipo", _where_empresas(empresa_ids, "ri", params, "eid")]
    clausula_permitidos = _clausula_cfops_permitidos(cfops_permitidos, "ri", params)
    if clausula_permitidos:
        where.append(clausula_permitidos)
    if cfop_filtro:
        where.append("ri.cfop = :cfop")
        params["cfop"] = cfop_filtro
    if ncm_filtro:
        where.append("ri.ncm ilike :ncm_filtro")
        params["ncm_filtro"] = f"{ncm_filtro.strip()}%"
    where_sql = " and ".join(where)

    rows = session.execute(text(f"""
        select coalesce(e.filial_winthor, '(não identificada)') as filial, ri.produto_codigo, ri.cst,
               count(*) as n_itens, sum(ri.valor_contabil) as valor_contabil,
               sum(ri.valor_tributado) as valor_tributado, sum(ri.valor_pis) as valor_pis,
               sum(ri.valor_cofins) as valor_cofins
        from relatorio_pc_itens ri
        left join empresas e on e.id = ri.empresa_id
        where {where_sql}
        group by e.filial_winthor, ri.produto_codigo, ri.cst
        order by filial, ri.produto_codigo, ri.cst
    """), params).mappings().all()
    return pd.DataFrame(rows, columns=["filial", "produto_codigo", "cst", "n_itens", "valor_contabil",
                                        "valor_tributado", "valor_pis", "valor_cofins"])


def _para_tipo_nativo(v):
    """Mesmo achado do módulo ICMS Normal (`lib/planilha.py::_para_tipo_nativo`, 06/08/2026): o psycopg2 não
    adapta escalares numpy (numpy.int64/float64/bool_) como parâmetro de bind — converte para o tipo nativo
    do Python equivalente antes de gravar."""
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v


def salvar_itens_editados(session, df_original, df_editado, competencia_id, tipo_operacao, usuario=None):
    """Compara linha a linha (pela coluna id) e só grava no banco o que realmente mudou — mesmo padrão do
    módulo ICMS Normal (`lib/planilha.py::salvar_itens_editados`). Grava histórico em `auditoria_edicoes_pc`
    (uma linha por CAMPO alterado). NÃO recalcula inconsistências sozinha — quem chama esta função decide
    quando recalcular (ver `recalcular_inconsistencias_apos_edicao` mais abaixo), porque recalcular é uma
    operação por filial e esta função não sabe quais filiais tiveram itens alterados até terminar o loop.
    Retorna (n_atualizados, {empresa_ids que tiveram pelo menos um item alterado})."""
    if df_original.empty:
        return 0, set()
    orig = df_original.set_index("id")
    edit = df_editado.set_index("id")
    campos = [c for c in COLUNAS_EDITAVEIS if c != "id"]

    atualizados = 0
    empresas_afetadas = set()
    auditoria = []
    for item_id in orig.index:
        if item_id not in edit.index:
            continue  # linha apagada na grade — não propaga exclusão aqui, por segurança
        mudou = False
        valores = {}
        for campo in campos:
            v_orig, v_edit = orig.loc[item_id, campo], edit.loc[item_id, campo]
            if pd.isna(v_orig) and pd.isna(v_edit):
                continue
            if v_orig != v_edit:
                mudou = True
                auditoria.append({
                    "item_id": _para_tipo_nativo(item_id),
                    "competencia_id": competencia_id,
                    "tipo_operacao": tipo_operacao,
                    "campo": campo,
                    "valor_anterior": None if pd.isna(v_orig) else str(v_orig),
                    "valor_novo": None if pd.isna(v_edit) else str(v_edit),
                    "editado_por": (usuario or {}).get("id"),
                    "editado_por_email": (usuario or {}).get("email"),
                })
            valores[campo] = None if pd.isna(v_edit) else _para_tipo_nativo(v_edit)
        if mudou:
            session.execute(text("""
                update relatorio_pc_itens
                set produto_codigo=:produto_codigo, ncm=:ncm, cfop=:cfop, quantidade=:quantidade,
                    valor_contabil=:valor_contabil, valor_desconto=:valor_desconto,
                    valor_itens=:valor_itens, valor_tributado=:valor_tributado, aliq_pis=:aliq_pis,
                    valor_pis=:valor_pis, aliq_cofins=:aliq_cofins, valor_cofins=:valor_cofins,
                    valor_nao_tributado=:valor_nao_tributado
                where id=:id
            """), {**valores, "id": _para_tipo_nativo(item_id)})
            atualizados += 1
            empresas_afetadas.add(_para_tipo_nativo(orig.loc[item_id].get("empresa_id"))
                                   if "empresa_id" in orig.columns else None)
    if atualizados:
        if auditoria:
            pd.DataFrame(auditoria).to_sql("auditoria_edicoes_pc", session.bind, if_exists="append", index=False)
        session.commit()
    empresas_afetadas.discard(None)
    return atualizados, empresas_afetadas


def recalcular_inconsistencias_apos_edicao(session, competencia_id, empresas_afetadas):
    """Chama `cst_regras_pc.registrar_inconsistencias_cst_regras` para cada filial que teve pelo menos um
    item editado na grade — reflete a edição nas inconsistências de CST × CFOP/NCM (aba Inconsistências e
    coluna "⚠️ Inconsistência" da própria grade) sem precisar reimportar o 1096. Import local (não no topo
    do arquivo) para evitar import circular, já que cst_regras_pc não importa nada deste módulo."""
    from lib.cst_regras_pc import registrar_inconsistencias_cst_regras
    for empresa_id in empresas_afetadas:
        registrar_inconsistencias_cst_regras(session, competencia_id, empresa_id)


def carregar_historico_edicoes(session, competencia_id, tipo_operacao, limite=200):
    """Lista os ajustes manuais feitos na grade desta competência/tipo_operacao, mais recentes primeiro —
    mesmo padrão do módulo ICMS Normal."""
    rows = session.execute(text("""
        select a.id, a.item_id, ri.produto_codigo, ri.cfop, a.campo, a.valor_anterior, a.valor_novo,
               a.editado_por_email, a.editado_em
        from auditoria_edicoes_pc a
        left join relatorio_pc_itens ri on ri.id = a.item_id
        where a.competencia_id = :cid and a.tipo_operacao = :tipo
        order by a.editado_em desc
        limit :limite
    """), {"cid": competencia_id, "tipo": tipo_operacao, "limite": limite}).mappings().all()
    return pd.DataFrame(rows, columns=["id", "item_id", "produto_codigo", "cfop", "campo", "valor_anterior",
                                        "valor_novo", "editado_por_email", "editado_em"])
