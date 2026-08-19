import sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from sqlalchemy import text

from lib.auth import require_login, logout_button, usuario_atual
from lib.db import get_session
from lib.formatacao import rotulo_empresa, formatar_moeda, coluna_moeda
from lib.status_apuracao_pc import status_competencia
from lib import importacao_pc, resumo_pc, planilha_pc, lancamentos_manuais_pc as lmpc
from lib.receitas_financeiras_pc import (
    TIPOS_RECEITA_FINANCEIRA, carregar_receitas_financeiras, salvar_receitas_financeiras,
    calcular_pis_cofins as calcular_pis_cofins_financeiras,
)
from lib.calculo_pis_cofins_lucro_real import (
    calcular_apuracao_pc, salvar_apuracao_pc, ordenar_linhas_para_exibicao, LAYOUT_LINHAS, ORDEM_SECOES,
    conferencia_1024_x_1096, SECAO_DEBITO, SECAO_EXCLUSOES_DEBITO, SECAO_FINANCEIRAS, SECAO_CREDITO,
    SECAO_EXCLUSOES_CREDITO, SECAO_SALDO_ANTERIOR, SECAO_RESULTADO,
)
from lib.cst_regras_pc import (
    registrar_ajuste_cst, carregar_historico_ajustes, TIPOS_REGRA, registrar_revisao, carregar_excecoes,
    definir_excecao_ativa, listar_cfops_sem_checagem, salvar_cfops_sem_checagem, listar_regras_cfop,
    salvar_regras_cfop, listar_regras_ncm, salvar_regras_ncm, listar_regras_alerta, salvar_regras_alerta,
)

# Tipos de inconsistência que carregam um CST passível de ajuste manual (log-only — ver
# cst_regras_pc.registrar_ajuste_cst). cfop_sem_grupo não tem CST associado, então fica de fora.
TIPOS_COM_CST_AJUSTAVEL = {"cst_nao_mapeado", "cst_regra_cfop", "cst_regra_ncm", "cst_regra_alerta"}

# ================================================================================================
# Cache de leitura (18/08/2026, mais tarde — pedido do usuário: "está muito lento, consegue ajustar o
# código para dar mais agilidade").
#
# Causa raiz: st.tabs() não evita execução — o Streamlit roda o script inteiro de cima a baixo a cada
# interação (clicar em QUALQUER filtro/botão/checkbox em QUALQUER aba), então toda consulta usada para
# montar as 8 abas rodava de novo a cada clique, mesmo nas abas que a pessoa nem estava olhando: as duas
# grades de Entrada E Saída (cada uma com uma consulta LEFT JOIN LATERAL de até 500 linhas), mais os 3
# resumos de cada uma, mais as 3 grades de "Regras de CST", mais Conferência 1024×1096 — tudo de novo a
# cada clique, em série (uma consulta de rede por vez).
#
# Sem tocar a lógica de negócio (as funções em lib/ continuam iguais, sem depender de Streamlit, testáveis
# fora dele igual antes), as consultas somente-leitura mais pesadas/repetidas passam por st.cache_data
# aqui na página. Duas coisas para quem for mexer aqui de novo:
# 1) O primeiro parâmetro leva "_" (convenção do Streamlit para "não tenta gerar hash disto") porque uma
#    Session do SQLAlchemy não é um objeto hasheável de forma estável.
# 2) TTL é só uma rede de segurança (contra esquecer de limpar em algum canto) — a invalidação de verdade
#    é explícita: toda ação que grava (salvar grade, salvar regra, revisar inconsistência, ajustar CST,
#    marcar CFOP sem checagem, ativar/desativar exceção) chama .clear() na(s) função(ões) cacheada(s)
#    certa(s) logo depois de gravar, antes do st.rerun(). Adicionar uma nova escrita nesta página sem
#    também limpar o cache correspondente é o jeito mais fácil de reintroduzir dado desatualizado na tela.
_TTL_ESTATICO = 300  # grupos/filiais/tabela de CST — não muda durante a sessão de trabalho
_TTL_LEITURA = 30    # resumos/grades/listas de regra — invalidados explicitamente ao salvar; TTL é reforço


@st.cache_data(ttl=_TTL_ESTATICO, show_spinner=False)
def _cache_listar_grupos(_session):
    return importacao_pc.listar_grupos(_session)


@st.cache_data(ttl=_TTL_ESTATICO, show_spinner=False)
def _cache_listar_filiais_grupo(_session, cnpj_raiz):
    return importacao_pc.listar_filiais_grupo(_session, cnpj_raiz)


@st.cache_data(ttl=_TTL_ESTATICO, show_spinner=False)
def _cache_csts_disponiveis(_session):
    rows = _session.execute(text("select codigo, descricao from cst_pis_cofins order by codigo")).mappings().all()
    return [dict(r) for r in rows]


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_inconsistencias(_session, competencia_id):
    return resumo_pc.carregar_inconsistencias(_session, competencia_id)


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_resumo_1024_por_cfop(_session, competencia_id, tipo_operacao):
    return resumo_pc.resumo_1024_por_cfop(_session, competencia_id, tipo_operacao)


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_resumo_por_cfop(_session, competencia_id, tipo_operacao):
    return resumo_pc.resumo_por_cfop(_session, competencia_id, tipo_operacao)


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_resumo_por_cst(_session, competencia_id, tipo_operacao):
    return resumo_pc.resumo_por_cst(_session, competencia_id, tipo_operacao)


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_itens_editavel(_session, competencia_id, tipo_operacao, empresa_ids, cfop_filtro, ncm_filtro,
                           busca, tipos_inc, limite):
    return planilha_pc.carregar_itens_editavel(
        _session, competencia_id, tipo_operacao, empresa_ids, cfop_filtro, ncm_filtro, busca, tipos_inc,
        limite,
    )


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_totalizador(_session, competencia_id, tipo_operacao, empresa_ids, cfop_filtro, ncm_filtro):
    return planilha_pc.carregar_totalizador(
        _session, competencia_id, tipo_operacao, empresa_ids, cfop_filtro, ncm_filtro,
    )


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_historico_edicoes(_session, competencia_id, tipo_operacao):
    return planilha_pc.carregar_historico_edicoes(_session, competencia_id, tipo_operacao)


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_regras_cfop(_session):
    return [dict(r) for r in listar_regras_cfop(_session)]


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_regras_ncm(_session):
    return [dict(r) for r in listar_regras_ncm(_session)]


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_regras_alerta(_session):
    return [dict(r) for r in listar_regras_alerta(_session)]


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_cfops_sem_checagem(_session, empresa_id):
    return [dict(r) for r in listar_cfops_sem_checagem(_session, empresa_id)]


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_conferencia(_session, competencia_id):
    return conferencia_1024_x_1096(_session, competencia_id)


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_excecoes(_session, empresa_ids):
    return [dict(r) for r in carregar_excecoes(_session, empresa_ids)]


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_historico_ajustes(_session, competencia_id):
    return [dict(r) for r in carregar_historico_ajustes(_session, competencia_id)]


def _card_inconsistencia(session, row, csts_disponiveis, key_prefix):
    """Card de inconsistência — estrutura equivalente à do módulo ICMS normal (pedido do usuário em
    18/08/2026): título com selo de quantidade (grupo = mesmo erro repetido N vezes), badge 🔁 quando
    resolvido automaticamente por uma exceção aprendida, formulário de Revisar/Ignorar/Só salvar
    justificativa com opção "replicar nas próximas apurações" (grava em excecoes_inconsistencia_pc — ver
    cst_regras_pc.registrar_revisao). Além disso, mantém a ação 'Ajustar CST' (log-only, específica do
    PIS/COFINS — não existe equivalente no ICMS) para quem quiser registrar direto qual seria o CST certo.
    Este card é para revisão que precisa de JULGAMENTO (justificar, decidir se replica) — para uma correção
    rápida e óbvia de CFOP/NCM/valor errado, use a grade editável nas abas Entrada/Saída (mais rápido,
    menos passos, mas sem justificativa nem "replicar").

    `key_prefix` (achado em produção em 18/08/2026, mais tarde: StreamlitDuplicateElementKey) — a mesma
    inconsistência (mesmo `row['id']`) pode aparecer em mais de uma seção da tela ao mesmo tempo: na aba
    Entrada OU Saída ("Inconsistências desta operação", filtro padrão inclui pendentes) E na aba
    Inconsistências geral (filtro padrão também inclui pendentes) — e como o Streamlit roda o script inteiro
    a cada interação (ver seção de cache no topo do arquivo), as duas seções renderizam no mesmo run. Sem um
    prefixo diferente por seção, as duas cópias do card geravam a mesma `key` de widget (ex.: `rev_123` duas
    vezes) e o Streamlit derrubava a página inteira com `StreamlitDuplicateElementKey`. Cada chamador passa
    um prefixo próprio (`f"inc_{tipo_operacao}"` nas abas Entrada/Saída, `"inc_geral"` na aba
    Inconsistências) para que os widgets do mesmo `row['id']` em seções diferentes tenham `key`s distintas."""
    tem_grupo = pd.notna(row.get("chave_agrupamento")) and row.get("chave_agrupamento")
    qtd = int(row["quantidade"]) if pd.notna(row.get("quantidade")) else 1
    selo = f"{qtd}× " if qtd > 1 else ""
    marca_auto = " 🔁" if row.get("aplicada_por_excecao") else ""
    descricao_curta = row["descricao"] if len(row["descricao"]) <= 90 else row["descricao"][:90] + "..."
    titulo = f"{selo}[{row['tipo']}] {descricao_curta}{marca_auto}"

    with st.expander(titulo):
        st.write(row["descricao"])
        legenda = (
            f"Operação: {row['tipo_operacao'] or '-'} • Fonte: {row['fonte']} • Filial: {row['filial']} • "
            f"Status: {row['status']}"
        )
        if row["ncm"]:
            legenda += f" • NCM: {row['ncm']}"
        st.caption(legenda)
        if qtd > 1:
            st.caption(
                f"Esse mesmo erro se repete em {qtd} itens do Relatório 1096 nesta filial/competência "
                f"(agrupado numa linha só) — revisar/ignorar/justificar aqui vale para os {qtd} de uma vez."
            )

        if row.get("aplicada_por_excecao"):
            st.info(
                f"🔁 Aplicado automaticamente — bateu com uma exceção conhecida cadastrada numa competência "
                f"anterior. Justificativa: {row['justificativa']}"
            )
        elif pd.notna(row.get("justificativa")) and row.get("justificativa"):
            st.info(f"Justificativa: {row['justificativa']}")

        if row["status"] == "ajustado" and pd.notna(row["ultimo_ajuste_cst"]):
            obs = f" — {row['ultimo_ajuste_obs']}" if row["ultimo_ajuste_obs"] else ""
            cst_atual = int(row["cst"]) if pd.notna(row["cst"]) else "?"
            st.info(
                f"Ajuste de CST registrado: CST {cst_atual} → **{int(row['ultimo_ajuste_cst'])}** "
                f"em {row['ultimo_ajuste_em']:%d/%m/%Y %H:%M}{obs} "
                f"(só histórico — não altera o cálculo nem o item importado)."
            )

        if tem_grupo:
            with st.form(f"{key_prefix}_form_inc_{row['id']}"):
                justificativa = st.text_area(
                    "Justificativa (opcional, mas obrigatória se marcar 'replicar')",
                    value=row.get("justificativa") or "", key=f"{key_prefix}_just_{row['id']}",
                )
                replicar = st.checkbox(
                    "🔁 Aplicar automaticamente nas próximas apurações desta filial (não perguntar de novo "
                    "este mesmo caso)",
                    key=f"{key_prefix}_replicar_{row['id']}",
                    help="Cria uma regra: da próxima vez que este mesmo grupo (mesmo CFOP/NCM × CST) "
                         "aparecer numa importação futura do 1096 desta filial, a inconsistência já nasce "
                         "revisada com esta justificativa, sem pedir revisão de novo.",
                )
                fc1, fc2, fc3 = st.columns(3)
                revisar = fc1.form_submit_button("✅ Marcar como revisado")
                ignorar = fc2.form_submit_button("🚫 Ignorar")
                salvar_just = fc3.form_submit_button("💾 Só salvar justificativa")

            if revisar or ignorar or salvar_just:
                if replicar and not justificativa.strip():
                    st.error("Para replicar nas próximas apurações, escreva a justificativa antes.")
                else:
                    novo_status = "revisado" if revisar else ("ignorado" if ignorar else None)
                    registrar_revisao(
                        session, row["id"], row["empresa_id"], row["tipo"], row["chave_agrupamento"],
                        row["ncm"], row["cfop"], row["tipo_operacao"], novo_status, justificativa,
                        replicar, usuario_atual(),
                    )
                    _cache_inconsistencias.clear()
                    if replicar:
                        _cache_excecoes.clear()
                    st.rerun()
        elif row["status"] == "pendente":
            if st.button("Marcar revisado", key=f"{key_prefix}_rev_{row['id']}"):
                resumo_pc.marcar_inconsistencia(session, row["id"], "revisado", usuario_atual())
                _cache_inconsistencias.clear()
                st.rerun()

        if row["status"] != "ajustado" and row["tipo"] in TIPOS_COM_CST_AJUSTAVEL:
            st.divider()
            st.caption(
                "Ou, se preferir, registre direto qual CST deveria ter sido usado — isso NÃO recalcula "
                "nada nem altera o item importado, fica só como histórico/checklist do que precisa ser "
                "corrigido na origem (Winthor):"
            )
            opcoes_cst = [c["codigo"] for c in csts_disponiveis]
            cst_corrigido = st.selectbox(
                "CST correto", opcoes_cst,
                format_func=lambda cod: f"{cod} — "
                                         f"{next((c['descricao'] for c in csts_disponiveis if c['codigo'] == cod), '')}",
                key=f"{key_prefix}_cst_novo_{row['id']}",
            )
            observacao_ajuste = st.text_input(
                "Observação (opcional)", key=f"{key_prefix}_obs_ajuste_{row['id']}"
            )
            if st.button("Registrar ajuste de CST", key=f"{key_prefix}_ajustar_{row['id']}"):
                registrar_ajuste_cst(
                    session, row["id"], cst_corrigido,
                    observacao_ajuste or None, usuario_atual(),
                )
                _cache_inconsistencias.clear()
                _cache_historico_ajustes.clear()
                st.rerun()


def _resumo_por_tipo(df):
    """Consolida as inconsistências (já filtradas por Status/Tipo/Filial/Operação) numa linha por tipo —
    grupos (quantas linhas de inconsistencias_pc), itens (soma de `quantidade`, 1 quando não agrupado) e
    quantos ainda estão pendentes. Pedido do usuário em 18/08/2026: "consolidar os erros por tipo, já que
    consigo filtrar na tela de entrada e saída" — como o filtro de Tipo já deixa ver só os cards de um tipo
    específico, esta tabela serve pra dar a visão geral por tipo ANTES de decidir em qual tipo entrar (não
    substitui os cards abaixo, só evita ter que abrir um por um pra saber onde estão concentrados os erros)."""
    if df.empty:
        return pd.DataFrame(columns=["tipo", "descricao", "grupos", "itens", "pendentes"])
    tmp = df.copy()
    tmp["quantidade"] = pd.to_numeric(tmp.get("quantidade"), errors="coerce").fillna(1)
    resumo = tmp.groupby("tipo").agg(
        grupos=("tipo", "size"),
        itens=("quantidade", "sum"),
        pendentes=("status", lambda s: (s == "pendente").sum()),
    ).reset_index()
    resumo["descricao"] = resumo["tipo"].map(planilha_pc.LABELS_INCONSISTENCIA).fillna(resumo["tipo"])
    resumo["itens"] = resumo["itens"].astype(int)
    return resumo[["tipo", "descricao", "grupos", "itens", "pendentes"]].sort_values(
        ["pendentes", "itens"], ascending=False
    ).reset_index(drop=True)


def _mostrar_resumo_por_tipo(df, key_prefix):
    resumo = _resumo_por_tipo(df)
    if resumo.empty:
        return
    st.dataframe(
        resumo, use_container_width=True, hide_index=True, key=f"{key_prefix}_resumo_tipo",
        column_config={
            "tipo": st.column_config.TextColumn("Tipo (código)"),
            "descricao": st.column_config.TextColumn("O que é", width="large"),
            "grupos": st.column_config.NumberColumn("Grupos (linhas)"),
            "itens": st.column_config.NumberColumn("Itens do 1096"),
            "pendentes": st.column_config.NumberColumn("Pendentes"),
        },
    )


def _secao_inconsistencias_operacao(session, df_inc, tipo_operacao, csts_disponiveis, key_prefix):
    """Bloco de inconsistências + ajuste de CST, filtrado por operação (saida/entrada) — usado nas abas
    Entrada/Saída. Filtro igual ao da aba Inconsistências (Status/Tipo/Filial), já pré-filtrado pela
    operação da aba (não precisa repetir Operação aqui)."""
    df_op = df_inc[df_inc["tipo_operacao"] == tipo_operacao]
    if df_op.empty:
        st.caption("Nenhuma inconsistência registrada para esta operação nesta competência.")
        return

    f1, f2, f3 = st.columns(3)
    status_disp = sorted(df_op["status"].unique())
    default_status = [s for s in status_disp if s != "ajustado"] or status_disp
    f_status = f1.multiselect("Status", status_disp, default=default_status, key=f"{key_prefix}_f_status")
    tipo_disp = sorted(df_op["tipo"].unique())
    f_tipo = f2.multiselect("Tipo", tipo_disp, default=tipo_disp, key=f"{key_prefix}_f_tipo")
    filial_disp = sorted(df_op["filial"].unique())
    f_filial = f3.multiselect("Filial", filial_disp, default=filial_disp, key=f"{key_prefix}_f_filial")

    df_filtrado = df_op[
        df_op["status"].isin(f_status) & df_op["tipo"].isin(f_tipo) & df_op["filial"].isin(f_filial)
    ]
    if df_filtrado.empty:
        st.info("Nenhuma inconsistência corresponde aos filtros selecionados.")
        return
    st.caption(f"Mostrando {len(df_filtrado)} de {len(df_op)} inconsistência(s) desta operação.")
    _mostrar_resumo_por_tipo(df_filtrado, key_prefix)
    st.divider()
    for _, row in df_filtrado.iterrows():
        _card_inconsistencia(session, row, csts_disponiveis, key_prefix)


def _aba_planilha_pc(session, competencia_id, tipo_operacao, empresa_ids, df_inc, csts_disponiveis):
    """Aba Entrada/Saída no padrão "planilha" do módulo ICMS Normal (pedido do usuário em 18/08/2026: "quero
    mais ou menos essa estrutura") — grade editável (st.data_editor) sobre os itens do Relatório 1096,
    visão Analítica (item a item) ou Sintética (totalizada por Filial + Produto + CST), filtros de CFOP/NCM/
    busca/tipo de inconsistência, e histórico de edições.

    AVISO CRÍTICO, mostrado também na tela: editar aqui NUNCA muda a Apuração (que roda 100% sobre a Rotina
    1024) — só recalcula as inconsistências de CST × CFOP/NCM e a Conferência 1024×1096. Ver docstring de
    lib/planilha_pc.py para o raciocínio completo."""
    st.info(
        "⚠️ Esta grade edita o **Relatório 1096** (conferência) — os valores da **Apuração** (linhas "
        "1.x-11.x, aba Apuração) continuam vindo 100% da **Rotina 1024** e NÃO mudam com uma edição aqui. "
        "O que muda ao salvar: as ⚠️ Inconsistências de CST × CFOP/NCM desta filial são recalculadas na hora, "
        "e a Conferência 1024×1096 reflete o novo valor na próxima vez que você abrir aquela aba."
    )
    st.caption(
        "Ajuste diretamente na grade (igual planilha) se algum código de produto, NCM, CFOP ou valor "
        "estiver errado no relatório original. O CST não é editável aqui de propósito — use os cards de "
        "'Inconsistências desta operação', mais abaixo, ou a aba ⚠️ Inconsistências (fluxo com "
        "justificativa/histórico dedicado para CST)."
    )

    visao = st.radio(
        "Visão", ["Analítica (item a item)", "Sintética (totalizada por Filial, Produto e CST)"],
        horizontal=True, key=f"visao_{tipo_operacao}",
    )
    sintetica = visao.startswith("Sintética")

    c1, c_ncm, c2, c3 = st.columns([2, 2, 3, 2])
    # O dropdown de filtro é sobre os CFOPs que aparecem no PRÓPRIO Relatório 1096 (o que a grade abaixo
    # mostra) — não sobre os CFOPs da Rotina 1024 (que é o "Resumo por CFOP — Rotina 1024" exibido mais
    # abaixo, uma fonte diferente, com um conjunto de CFOPs que pode não ser idêntico).
    resumo_1096_cfop = _cache_resumo_por_cfop(session, competencia_id, tipo_operacao)
    cfops_disponiveis = (["(todos)"] + sorted(resumo_1096_cfop["cfop"].tolist())) if not resumo_1096_cfop.empty else ["(todos)"]
    cfop_sel = c1.selectbox("Filtrar por CFOP", cfops_disponiveis, key=f"cfop_{tipo_operacao}")
    cfop_filtro = None if cfop_sel == "(todos)" else int(cfop_sel)
    ncm_filtro = c_ncm.text_input(
        "Filtrar por NCM", key=f"ncm_{tipo_operacao}", placeholder="ex: 8213 ou 82130000",
        help="Filtra por prefixo — '8213' pega qualquer NCM que comece com 8213, não só o código exato.",
    )

    if sintetica:
        limite = c3.number_input("Máx. linhas na tela", min_value=50, max_value=5000, value=500, step=50,
                                  key=f"limite_{tipo_operacao}")
        tot = _cache_totalizador(session, competencia_id, tipo_operacao, empresa_ids,
                                  cfop_filtro, ncm_filtro or None)
        st.caption(f"{len(tot)} combinação(ões) de Filial + Produto + CST"
                   f"{' para este CFOP/NCM' if (cfop_filtro or ncm_filtro) else ''}.")
        st.dataframe(
            tot.head(limite), use_container_width=True, height=420, hide_index=True,
            column_config={
                "filial": st.column_config.TextColumn("Filial"),
                "produto_codigo": st.column_config.TextColumn("Código Produto"),
                "cst": st.column_config.NumberColumn("CST"),
                "n_itens": st.column_config.NumberColumn("Nº itens"),
                "valor_contabil": coluna_moeda("Valor Contábil", disabled=True),
                "valor_tributado": coluna_moeda("Valor Tributado", disabled=True),
                "valor_pis": coluna_moeda("Valor PIS", disabled=True),
                "valor_cofins": coluna_moeda("Valor COFINS", disabled=True),
            },
        )
    else:
        busca = c2.text_input("Buscar por código do produto", key=f"busca_{tipo_operacao}",
                               help="Nem o 1096 nem a Rotina 1024 trazem número de NF ou nome do "
                                    "fornecedor/cliente — a busca aqui é só pelo código do produto.")
        limite = c3.number_input("Máx. linhas na tela", min_value=50, max_value=5000, value=500, step=50,
                                  key=f"limite_{tipo_operacao}")
        tipos_inc_sel = st.multiselect(
            "⚠️ Filtrar por tipo de inconsistência pendente",
            options=list(planilha_pc.LABELS_INCONSISTENCIA.keys()),
            format_func=lambda t: planilha_pc.LABELS_INCONSISTENCIA[t],
            key=f"tipos_inc_{tipo_operacao}",
            help="Deixe vazio para mostrar todos os itens. Escolha um ou mais tipos para ver só os itens "
                 "com aquele erro específico pendente.",
        )

        df, total = _cache_itens_editavel(
            session, competencia_id, tipo_operacao, empresa_ids, cfop_filtro, ncm_filtro or None,
            busca or None, tipos_inc_sel or None, limite,
        )

        if total > len(df):
            st.warning(f"Mostrando {len(df)} de {total} itens (refine o filtro ou aumente o limite acima — "
                       f"grades muito grandes deixam o navegador lento).")
        else:
            st.caption(f"{total} itens.")

        editado = st.data_editor(
            df, use_container_width=True, height=420, num_rows="fixed", key=f"editor_pc_{tipo_operacao}",
            column_order=["id", "filial", "inconsistencia", "produto_codigo", "ncm", "cst", "cfop",
                          "quantidade", "valor_contabil", "valor_desconto", "valor_itens", "valor_tributado",
                          "aliq_pis", "valor_pis", "aliq_cofins", "valor_cofins", "valor_nao_tributado"],
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "empresa_id": st.column_config.NumberColumn("Empresa ID", disabled=True),
                "filial": st.column_config.TextColumn("Filial", disabled=True),
                "inconsistencia": st.column_config.TextColumn(
                    "⚠️ Inconsistência", disabled=True, width="medium",
                    help="Sinaliza inconsistência(s) PENDENTE(s) de CST × CFOP/NCM ligada(s) a este item. Em "
                         "branco não é garantia de que está tudo certo — só que nenhuma das checagens "
                         "automáticas pegou nada nesta linha. Descrição completa e opção de "
                         "revisar/ignorar/replicar: seção 'Inconsistências desta operação', mais abaixo."
                ),
                "cst": st.column_config.NumberColumn(
                    "CST", disabled=True,
                    help="Não editável aqui — use os cards de 'Inconsistências desta operação' (mais "
                         "abaixo) ou a aba ⚠️ Inconsistências para corrigir CST, com histórico dedicado."
                ),
                "produto_codigo": st.column_config.TextColumn("Código Produto"),
                "ncm": st.column_config.TextColumn("NCM"),
                "cfop": st.column_config.NumberColumn("CFOP"),
                "quantidade": st.column_config.NumberColumn("Quantidade", format="%.3f"),
                "valor_contabil": coluna_moeda("Valor Contábil"),
                "valor_desconto": coluna_moeda("Valor Desconto"),
                "valor_itens": coluna_moeda("Valor Itens"),
                "valor_tributado": coluna_moeda("Valor Tributado"),
                "aliq_pis": st.column_config.NumberColumn("Alíq. PIS %", format="%.4f"),
                "valor_pis": coluna_moeda("Valor PIS"),
                "aliq_cofins": st.column_config.NumberColumn("Alíq. COFINS %", format="%.4f"),
                "valor_cofins": coluna_moeda("Valor COFINS"),
                "valor_nao_tributado": coluna_moeda("Valor Não Tributado"),
            },
        )
        if st.button("💾 Salvar alterações", key=f"salvar_pc_{tipo_operacao}"):
            n, empresas_afetadas = planilha_pc.salvar_itens_editados(
                session, df, editado, competencia_id=competencia_id, tipo_operacao=tipo_operacao,
                usuario=usuario_atual(),
            )
            if n:
                with st.spinner("Recalculando inconsistências..."):
                    planilha_pc.recalcular_inconsistencias_apos_edicao(session, competencia_id, empresas_afetadas)
                # Edição na grade muda relatorio_pc_itens (cfop/ncm/valores) e as inconsistências CST ×
                # CFOP/NCM daquelas filiais — limpa todo cache derivado desses dados antes do rerun, senão
                # a tela mostraria valor antigo até o TTL expirar (ver bloco de cache no topo do arquivo).
                _cache_itens_editavel.clear()
                _cache_totalizador.clear()
                _cache_resumo_por_cfop.clear()
                _cache_resumo_por_cst.clear()
                _cache_historico_edicoes.clear()
                _cache_inconsistencias.clear()
                _cache_conferencia.clear()
                st.success(
                    f"{n} linha(s) atualizada(s), {len(empresas_afetadas)} filial(is) recalculada(s) — o "
                    f"que foi corrigido já some da coluna ⚠️ Inconsistência aqui na grade e da aba "
                    f"Inconsistências. A Apuração (Rotina 1024) não foi alterada."
                )
            else:
                st.info("Nenhuma mudança detectada.")
            st.rerun()

    with st.expander("📝 Histórico de edições desta grade (mais recentes primeiro)"):
        hist = _cache_historico_edicoes(session, competencia_id, tipo_operacao)
        if hist.empty:
            st.caption("Nenhuma edição registrada ainda nesta grade, para esta competência.")
        else:
            st.dataframe(
                hist, use_container_width=True, height=300, hide_index=True,
                column_order=["item_id", "produto_codigo", "cfop", "campo", "valor_anterior", "valor_novo",
                              "editado_por_email", "editado_em"],
                column_config={
                    "item_id": st.column_config.NumberColumn("ID Item"),
                    "produto_codigo": st.column_config.TextColumn("Código Produto"),
                    "cfop": st.column_config.NumberColumn("CFOP"),
                    "campo": st.column_config.TextColumn("Campo alterado"),
                    "valor_anterior": st.column_config.TextColumn("Valor anterior"),
                    "valor_novo": st.column_config.TextColumn("Valor novo"),
                    "editado_por_email": st.column_config.TextColumn("Editado por"),
                    "editado_em": st.column_config.DatetimeColumn("Quando", format="DD/MM/YYYY HH:mm"),
                },
            )

    st.markdown("---")
    c_res1, c_res2 = st.columns(2)
    with c_res1:
        st.subheader("Resumo por CFOP — Rotina 1024 (usado na Apuração)")
        resumo_1024_cfop = _cache_resumo_1024_por_cfop(session, competencia_id, tipo_operacao)
        st.dataframe(resumo_1024_cfop, use_container_width=True, hide_index=True)
    with c_res2:
        st.subheader("Resumo por CST — Relatório 1096")
        st.dataframe(_cache_resumo_por_cst(session, competencia_id, tipo_operacao), use_container_width=True,
                     hide_index=True)

    st.markdown("---")
    st.subheader("Inconsistências desta operação (regras de CST do 1096)")
    st.caption(
        "Revisão com justificativa — para uma correção rápida e óbvia de CFOP/NCM/valor, use a grade "
        "editável acima em vez de vir até aqui."
    )
    _secao_inconsistencias_operacao(session, df_inc, tipo_operacao, csts_disponiveis, f"inc_{tipo_operacao}")


def _aba_regras_cst(session):
    st.markdown(
        "**Para que serve esta aba:** cadastro das regras de CST × CFOP/NCM usadas pelas 3 checagens "
        "automáticas do Relatório 1096 (ver aba ⚠️ Inconsistências) — antes só dava para incluir com um "
        "`insert` direto no banco (ver `sql/004_regras_cst_pc.sql`); agora dá para gerenciar por aqui. "
        "Regras são **globais** (valem para todas as filiais do grupo), diferente da aba 🚫 CFOPs sem "
        "Checagem de CST, que é por filial."
    )
    st.warning(
        "Depois de incluir, editar ou remover uma regra, as inconsistências só refletem a mudança na "
        "próxima vez que o Relatório 1096 for reimportado, ou quando você salvar qualquer edição na grade "
        "das abas Entrada/Saída (que recalcula as inconsistências daquela filial)."
    )

    sub_cfop, sub_ncm, sub_alerta = st.tabs(["Por CFOP", "Por NCM", "Sempre-alerta (por CST)"])

    with sub_cfop:
        st.caption("CST esperado quando este CFOP aparecer no Relatório 1096, nesta direção (entrada/saída).")
        df_cfop = pd.DataFrame(_cache_regras_cfop(session))
        if df_cfop.empty:
            df_cfop = pd.DataFrame(columns=["id", "cst", "cfop", "tipo_operacao", "observacao", "created_at"])
        df_cfop_editado = st.data_editor(
            df_cfop, use_container_width=True, num_rows="dynamic", key="editor_regras_cfop",
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "cst": st.column_config.NumberColumn("CST esperado", required=True),
                "cfop": st.column_config.NumberColumn("CFOP", required=True),
                "tipo_operacao": st.column_config.SelectboxColumn(
                    "Operação", options=["entrada", "saida"], required=True),
                "observacao": st.column_config.TextColumn("Observação (opcional)", width="large"),
                "created_at": st.column_config.DatetimeColumn("Cadastrado em", disabled=True),
            },
            column_order=["cst", "cfop", "tipo_operacao", "observacao", "created_at", "id"],
        )
        if st.button("💾 Salvar regras por CFOP"):
            resultado = salvar_regras_cfop(session, df_cfop, df_cfop_editado)
            _cache_regras_cfop.clear()
            st.success(f"{resultado['incluidos']} incluída(s), {resultado['atualizados']} atualizada(s), "
                       f"{resultado['removidos']} removida(s).")
            st.rerun()

    with sub_ncm:
        st.caption("CST esperado quando este NCM aparecer no Relatório 1096, nesta direção (entrada/saída).")
        df_ncm = pd.DataFrame(_cache_regras_ncm(session))
        if df_ncm.empty:
            df_ncm = pd.DataFrame(columns=["id", "cst", "ncm", "tipo_operacao", "observacao", "created_at"])
        df_ncm_editado = st.data_editor(
            df_ncm, use_container_width=True, num_rows="dynamic", key="editor_regras_ncm",
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "cst": st.column_config.NumberColumn("CST esperado", required=True),
                "ncm": st.column_config.TextColumn("NCM", required=True),
                "tipo_operacao": st.column_config.SelectboxColumn(
                    "Operação", options=["entrada", "saida"], required=True),
                "observacao": st.column_config.TextColumn("Observação (opcional)", width="large"),
                "created_at": st.column_config.DatetimeColumn("Cadastrado em", disabled=True),
            },
            column_order=["cst", "ncm", "tipo_operacao", "observacao", "created_at", "id"],
        )
        if st.button("💾 Salvar regras por NCM"):
            resultado = salvar_regras_ncm(session, df_ncm, df_ncm_editado)
            _cache_regras_ncm.clear()
            st.success(f"{resultado['incluidos']} incluída(s), {resultado['atualizados']} atualizada(s), "
                       f"{resultado['removidos']} removida(s).")
            st.rerun()

    with sub_alerta:
        st.caption(
            "CST que deve sempre gerar um alerta informativo ao aparecer no Relatório 1096 (nesta direção), "
            "mas nunca bloqueia nada — sem CFOP/NCM associado, é qualquer ocorrência do CST."
        )
        df_alerta = pd.DataFrame(_cache_regras_alerta(session))
        if df_alerta.empty:
            df_alerta = pd.DataFrame(columns=["id", "cst", "tipo_operacao", "observacao", "created_at"])
        df_alerta_editado = st.data_editor(
            df_alerta, use_container_width=True, num_rows="dynamic", key="editor_regras_alerta",
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "cst": st.column_config.NumberColumn("CST", required=True),
                "tipo_operacao": st.column_config.SelectboxColumn(
                    "Operação", options=["entrada", "saida"], required=True),
                "observacao": st.column_config.TextColumn("Observação (opcional)", width="large"),
                "created_at": st.column_config.DatetimeColumn("Cadastrado em", disabled=True),
            },
            column_order=["cst", "tipo_operacao", "observacao", "created_at", "id"],
        )
        if st.button("💾 Salvar regras sempre-alerta"):
            resultado = salvar_regras_alerta(session, df_alerta, df_alerta_editado)
            _cache_regras_alerta.clear()
            st.success(f"{resultado['incluidos']} incluída(s), {resultado['atualizados']} atualizada(s), "
                       f"{resultado['removidos']} removida(s).")
            st.rerun()


def _aba_cfops_sem_checagem(session, filiais_grupo):
    st.markdown(
        "**Para que serve esta aba:** se um CFOP dispara inconsistência de CST recorrente por um motivo que "
        "você já conhece e não é erro de verdade, marque ele aqui em vez de justificar a mesma inconsistência "
        "todo mês — igual à aba 'CFOPs sem Validação' do módulo ICMS Normal."
    )
    st.caption(
        "Itens desse CFOP deixam de entrar nas 3 checagens automáticas (regra por CFOP, regra por NCM, "
        "sempre-alerta) para esta filial, tanto nesta competência quanto nas futuras, até você remover o "
        "cadastro. Não afeta a grade Entrada/Saída nem a Apuração, só as checagens automáticas. Cadastro "
        "por filial — diferente da aba 🔖 Regras de CST, que é global."
    )
    if not filiais_grupo:
        st.info("Nenhuma filial cadastrada para este grupo.")
        return
    filial_sel = st.selectbox("Filial", filiais_grupo, format_func=rotulo_empresa, key="cfop_sv_filial")
    empresa_id = filial_sel["id"]

    df_sv = pd.DataFrame(_cache_cfops_sem_checagem(session, empresa_id))
    if df_sv.empty:
        df_sv = pd.DataFrame(columns=["id", "cfop", "descricao", "motivo", "criado_por_email", "created_at"])
    st.caption(f"{len(df_sv)} CFOP(s) marcado(s) como sem checagem para esta filial.")
    df_sv_editado = st.data_editor(
        df_sv, use_container_width=True, num_rows="dynamic", key=f"editor_cfop_sv_{empresa_id}",
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "cfop": st.column_config.NumberColumn("CFOP", required=True),
            "descricao": st.column_config.TextColumn("Descrição do CFOP", disabled=True, width="large"),
            "motivo": st.column_config.TextColumn("Motivo (opcional)", width="large"),
            "criado_por_email": st.column_config.TextColumn("Cadastrado por", disabled=True),
            "created_at": st.column_config.DatetimeColumn("Cadastrado em", disabled=True),
        },
        column_order=["cfop", "descricao", "motivo", "criado_por_email", "created_at", "id"],
    )
    st.caption("Para incluir: adicione uma linha nova (ícone + no final da grade) e digite o CFOP. Para "
               "remover (volta a checar normalmente): selecione a linha e apague (ícone de lixeira). Depois "
               "clique em Salvar.")
    if st.button("💾 Salvar CFOPs sem checagem", key=f"salvar_cfop_sv_{empresa_id}"):
        resultado = salvar_cfops_sem_checagem(session, empresa_id, df_sv, df_sv_editado, usuario_atual())
        _cache_cfops_sem_checagem.clear()
        st.success(f"{resultado['incluidos']} incluído(s), {resultado['removidos']} removido(s). Salve "
                   f"qualquer edição na grade Entrada/Saída desta filial para as checagens refletirem a "
                   f"mudança.")
        st.rerun()


st.set_page_config(page_title="PIS/COFINS Lucro Real", layout="wide")
require_login()
logout_button()
st.title("PIS/COFINS — Lucro Real")

session = get_session()
grupos = _cache_listar_grupos(session)
if not grupos:
    st.warning("Nenhuma empresa em regime Lucro Real cadastrada ainda.")
    st.stop()

col1, col2, col3 = st.columns(3)
grupo = col1.selectbox(
    "Grupo (CNPJ raiz)", grupos,
    format_func=lambda g: f"{g['nome_grupo']} — {g['n_filiais']} filial(is)",
)
ano = col2.number_input("Ano", min_value=2020, max_value=2100, value=2026, step=1)
mes = col3.number_input("Mês", min_value=1, max_value=12, value=7, step=1)

competencia_id = importacao_pc.buscar_competencia_grupo(session, grupo["cnpj_raiz"], ano, mes)
if not competencia_id:
    st.info("Nenhum dado importado para este grupo/período ainda. Use **Importar Relatórios**.")
    st.stop()

comp_row = session.execute(text("select status from competencias where id = :id"), {"id": competencia_id}).mappings().first()
status = status_competencia(session, competencia_id, comp_row["status"])
getattr(st, status["nivel"])(status["texto"])

filiais_grupo = _cache_listar_filiais_grupo(session, grupo["cnpj_raiz"])
empresa_ids_grupo = [f["id"] for f in filiais_grupo]

# Carregados uma vez, usados na aba Inconsistências e também nas abas Entrada/Saída (os ajustes de CST feitos
# após a análise do 1096 podem ser registrados direto nas abas de Entrada/Saída, junto com o detalhe do 1096,
# não só numa aba separada).
df_inc = _cache_inconsistencias(session, competencia_id)
csts_disponiveis = _cache_csts_disponiveis(session)

# Ordem das abas revista em 18/08/2026 (à noite), a pedido do usuário — "quero mais ou menos essa estrutura"
# mostrando a tela do módulo ICMS Normal inteira (grade editável tipo planilha, abas de cadastro de regra,
# banner de status já existente desde antes). Isso SUBSTITUI a ordem decidida mais cedo no mesmo dia (que
# tinha Inconsistências primeiro — ver histórico no projeto Claude "PIS/COFINS"): Entrada/Saída (a grade)
# primeiro, depois as abas de cadastro/regra, Ajustes Manuais, Apuração, Conferência e Inconsistências por
# último — mesma lógica do ICMS Normal. Isso é só ordem de exibição — não trava nada: calcular a apuração
# continua disponível a qualquer momento, independente do que esteja pendente no 1096 (o 1096 é conferência,
# não bloqueia).
(aba_entrada, aba_saida, aba_regras_cst, aba_cfop_sem_checagem, aba_ajustes, aba_apuracao, aba_conferencia,
 aba_inconsist) = st.tabs([
    "📥 Entrada (Crédito)", "📤 Saída (Débito)", "🔖 Regras de CST", "🚫 CFOPs sem Checagem de CST",
    "🧮 Ajustes Manuais", "📋 Apuração", "📎 Conferência 1024×1096", "⚠️ Inconsistências",
])

with aba_entrada:
    _aba_planilha_pc(session, competencia_id, "entrada", empresa_ids_grupo, df_inc, csts_disponiveis)

with aba_saida:
    _aba_planilha_pc(session, competencia_id, "saida", empresa_ids_grupo, df_inc, csts_disponiveis)

with aba_regras_cst:
    _aba_regras_cst(session)

with aba_cfop_sem_checagem:
    _aba_cfops_sem_checagem(session, filiais_grupo)

# ---------------------------------------------------------------------------------------------- Ajustes Manuais
with aba_ajustes:
    st.caption(
        "Créditos de PIS/COFINS que não vêm do Relatório 1096 — nesta versão, só Aluguéis (Prédios / "
        "Máquinas e Equipamentos) e Depreciação (linhas 5.3, 5.4 e 5.6 da apuração). Informe a base do mês; "
        "o PIS (1,65%) e o COFINS (7,60%) são calculados automaticamente."
    )
    with st.form("novo_lancamento_pc"):
        c1, c2 = st.columns(2)
        tipo = c1.selectbox("Tipo", list(lmpc.TIPOS.keys()), format_func=lambda t: lmpc.TIPOS[t])
        base_valor = c2.number_input("Base do mês (R$)", min_value=0.0, step=100.0, format="%.2f")
        descricao = st.text_input("Descrição", placeholder="ex: Aluguel galpão matriz — julho/2026")
        if st.form_submit_button("Adicionar", type="primary"):
            if not descricao.strip():
                st.error("Informe uma descrição.")
            elif base_valor <= 0:
                st.error("Informe uma base maior que zero.")
            else:
                resultado = lmpc.adicionar(session, competencia_id, tipo, descricao.strip(), base_valor,
                                            usuario_atual())
                st.success(f"Lançamento adicionado — crédito PIS {formatar_moeda(resultado['valor_pis'])}, "
                           f"COFINS {formatar_moeda(resultado['valor_cofins'])}.")
                st.rerun()

    st.markdown("---")
    st.subheader("Lançamentos desta competência")
    lancamentos = lmpc.listar(session, competencia_id)
    if not lancamentos:
        st.info("Nenhum lançamento manual ainda.")
    else:
        df_original = pd.DataFrame(lancamentos)
        df_original["tipo"] = df_original["tipo"].map(lmpc.TIPOS)
        df_editado = st.data_editor(
            df_original, use_container_width=True, hide_index=True, num_rows="dynamic",
            disabled=["id", "tipo", "descricao", "base_valor", "valor_pis", "valor_cofins", "created_at"],
            column_config={
                "base_valor": coluna_moeda("Base"), "valor_pis": coluna_moeda("Crédito PIS"),
                "valor_cofins": coluna_moeda("Crédito COFINS"),
            },
            key="grade_lancamentos_pc",
        )
        removidos = lmpc.excluir_removidos(session, df_original, df_editado)
        if removidos:
            st.success(f"{removidos} lançamento(s) excluído(s).")
            st.rerun()

    st.markdown("---")
    st.subheader("Saldo credor do período anterior")
    st.caption(
        "Enquanto a apuração não encadeia automaticamente entre competências, digite aqui o saldo credor "
        "de PIS/COFINS que sobrou da competência anterior (linhas 8.1/8.2)."
    )
    saldo_atual = lmpc.carregar_saldo_anterior(session, competencia_id)
    c1, c2 = st.columns(2)
    saldo_pis_input = c1.number_input("Saldo Credor de PIS do período anterior", value=float(saldo_atual["saldo_pis"]),
                                       step=10.0, format="%.2f")
    saldo_cofins_input = c2.number_input("Saldo Credor de COFINS do período anterior",
                                          value=float(saldo_atual["saldo_cofins"]), step=10.0, format="%.2f")
    if st.button("Salvar saldo anterior"):
        lmpc.salvar_saldo_anterior(session, competencia_id, saldo_pis_input, saldo_cofins_input)
        st.success("Saldo anterior salvo.")
        st.rerun()

    st.markdown("---")
    st.subheader("Receitas Financeiras (linha 3 — alíquota reduzida 0,65%/4%, Lei 8.426/2015)")
    st.caption(
        "Débito (soma no que se paga, diferente dos créditos acima) — alíquota bem menor que a cheia usada "
        "no resto da apuração (1,65%/7,60%). Mesmos 6 subitens da planilha antiga; a base da linha 3 é a "
        "soma dos 6, calculada de novo toda vez que você clicar em 'Calcular apuração' na aba Apuração — "
        "salvar aqui só grava os valores, não recalcula a apuração sozinho."
    )
    valores_fin_atuais = carregar_receitas_financeiras(session, competencia_id)
    with st.form("form_receitas_financeiras_pc"):
        novos_valores = {}
        for tipo, rotulo in TIPOS_RECEITA_FINANCEIRA.items():
            novos_valores[tipo] = st.number_input(
                rotulo, value=float(valores_fin_atuais[tipo]), step=100.0, format="%.2f",
                key=f"rf_{tipo}",
            )
        salvar_fin = st.form_submit_button("💾 Salvar Receitas Financeiras")
    base_preview = sum((Decimal(str(v)) for v in novos_valores.values()), Decimal("0"))
    pis_preview, cofins_preview = calcular_pis_cofins_financeiras(base_preview)
    st.caption(
        f"Base total: {formatar_moeda(base_preview)} → PIS (0,65%): {formatar_moeda(pis_preview)} • "
        f"COFINS (4%): {formatar_moeda(cofins_preview)}"
    )
    if salvar_fin:
        salvar_receitas_financeiras(session, competencia_id, novos_valores, usuario_atual())
        st.success("Receitas Financeiras salvas — clique em 'Calcular apuração' (aba Apuração) para a "
                    "linha 3 refletir esses valores no resultado final.")
        st.rerun()

# ---------------------------------------------------------------------------------------------- Apuração
with aba_apuracao:
    if st.button("🔄 Calcular apuração", type="primary"):
        linhas = calcular_apuracao_pc(session, competencia_id)
        salvar_apuracao_pc(session, competencia_id, linhas)
        st.success("Apuração calculada.")
        st.rerun()

    linhas_salvas = session.execute(text("""
        select linha, descricao, valor_pis, valor_cofins, manual, detalhe
        from apuracao_pc_linhas where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()

    def _base_da_linha(detalhe):
        # detalhe (jsonb) vem como dict já desserializado. "base_total" existe nos grupos de CFOP (1.1,
        # 1.2, 1.4, 1.6, 5.1, 5.2, 5.5, 5.7, 5.8 — aqui é o valor BRUTO, Valor Contábil, antes de excluir o
        # ICMS), nas linhas 2.3/6.4 (o próprio valor do ICMS destacado excluído), na 2/6 (soma das exclusões
        # já implementadas) e nos totais 1/5 (idem, bruto). Nas demais linhas não há "base" — mostra "—".
        if not detalhe or "base_total" not in detalhe:
            return None
        try:
            return Decimal(str(detalhe["base_total"]))
        except Exception:
            return None

    def _base_liquida_da_linha(detalhe):
        # "base_liquida" só existe nas linhas 1.1-5.8/1/5 — é o bruto já com o ICMS destacado excluído, o
        # valor que de fato multiplica pela alíquota (1,65%/7,60%). Usado só nos cartões de resumo.
        if not detalhe or "base_liquida" not in detalhe:
            return None
        try:
            return Decimal(str(detalhe["base_liquida"]))
        except Exception:
            return None

    def _cartao_totais(titulo, icone, cor, base, pis, cofins):
        """Cartão visual (HTML/CSS inline) para destacar a base final de uma seção e o PIS/COFINS
        calculados a partir dela — pedido do usuário: manter débito/exclusões como já estava, e só depois
        de cada bloco (débito, crédito) mostrar uma linha de resumo com Base/PIS/COFINS, "mais visual".
        `base=None` omite o bloco de Base (usado no cartão de resultado final, que não tem uma base própria)."""
        bloco_base = "" if base is None else f"""
    <div>
      <div style="font-size:0.78rem; opacity:0.65; text-transform:uppercase; letter-spacing:.04em;">
        Base de Cálculo</div>
      <div style="font-size:1.5rem; font-weight:700;">{formatar_moeda(base)}</div>
    </div>"""
        st.markdown(f"""
<div style="border-left: 6px solid {cor}; background: rgba(148,163,184,0.08); border-radius: 10px;
            padding: 18px 24px; margin: 6px 0 22px 0;">
  <div style="font-size: 1.05rem; font-weight: 700; margin-bottom: 12px;">{icone} {titulo}</div>
  <div style="display:flex; gap: 48px; flex-wrap: wrap;">{bloco_base}
    <div>
      <div style="font-size:0.78rem; opacity:0.65; text-transform:uppercase; letter-spacing:.04em;">
        Valor PIS</div>
      <div style="font-size:1.5rem; font-weight:700; color:{cor};">{formatar_moeda(pis)}</div>
    </div>
    <div>
      <div style="font-size:0.78rem; opacity:0.65; text-transform:uppercase; letter-spacing:.04em;">
        Valor COFINS</div>
      <div style="font-size:1.5rem; font-weight:700; color:{cor};">{formatar_moeda(cofins)}</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    COR_DEBITO = "#f87171"    # vermelho — débito (o que a empresa deve)
    COR_CREDITO = "#4ade80"   # verde — crédito (o que abate do débito)
    COR_RESULTADO = "#fbbf24"  # âmbar — resultado final (DARF)

    SECAO_ICONE = {
        SECAO_DEBITO: "📤", SECAO_EXCLUSOES_DEBITO: "➖", SECAO_FINANCEIRAS: "💹",
        SECAO_CREDITO: "📥", SECAO_EXCLUSOES_CREDITO: "➖", SECAO_SALDO_ANTERIOR: "🔄",
        SECAO_RESULTADO: "🧾",
    }

    if not linhas_salvas:
        st.info("Ainda não calculado — clique em **Calcular apuração**.")
    else:
        # Mesma sequência/seções da planilha original (aba "PC") — ver LAYOUT_LINHAS no motor de cálculo.
        # Não usa st.dataframe aqui de propósito: precisamos de indentação e negrito por linha (sub-item
        # vs. total), que uma grade não faz — por isso a renderização é linha a linha com st.columns.
        linhas_ordenadas = ordenar_linhas_para_exibicao(linhas_salvas)
        totais = {r["linha"]: r for r in linhas_salvas}
        base_debito_liquida = _base_liquida_da_linha(totais["1"]["detalhe"]) if "1" in totais else None
        base_credito_liquida = _base_liquida_da_linha(totais["5"]["detalhe"]) if "5" in totais else None

        st.caption(
            "A **Base** de cada linha 1.1 a 1.6 / 5.1 a 5.8 é o Valor Contábil bruto (antes de excluir o "
            "ICMS destacado). A linha 2.3/6.4 mostra o ICMS que sai desse bruto — o cartão logo depois do "
            "Débito e do Crédito mostra a Base de Cálculo já líquida (bruto − ICMS excluído) e o PIS/COFINS "
            "calculados em cima dela."
        )
        cab = st.columns([6, 2, 1.3])
        cab[0].markdown("**Linha**")
        cab[1].markdown("**Base**")
        cab[2].markdown("**Situação**")

        secao_atual = None
        for r in linhas_ordenadas:
            secao, _ordem, nivel = LAYOUT_LINHAS.get(r["linha"], ("Outras linhas", 999, 1))
            if secao != secao_atual:
                if secao_atual == SECAO_EXCLUSOES_DEBITO and "1" in totais:
                    _cartao_totais("Base de Cálculo (líquida) — Débito", "📤", COR_DEBITO, base_debito_liquida,
                                    totais["1"]["valor_pis"], totais["1"]["valor_cofins"])
                elif secao_atual == SECAO_EXCLUSOES_CREDITO and "5" in totais:
                    _cartao_totais("Base de Cálculo (líquida) — Crédito", "📥", COR_CREDITO, base_credito_liquida,
                                    totais["5"]["valor_pis"], totais["5"]["valor_cofins"])
                st.markdown(f"##### {SECAO_ICONE.get(secao, '')} {secao}")
                secao_atual = secao
            destaque = nivel == 0  # linha de total da seção — negrito, sem indentação
            indent = "&nbsp;&nbsp;&nbsp;&nbsp;" if not destaque else ""
            abre, fecha = ("**", "**") if destaque else ("", "")
            base = _base_da_linha(r["detalhe"])
            base_txt = formatar_moeda(base) if base is not None else "—"
            linha_cols = st.columns([6, 2, 1.3])
            linha_cols[0].markdown(f"{indent}{abre}{r['linha']} — {r['descricao']}{fecha}",
                                    unsafe_allow_html=True)
            linha_cols[1].markdown(f"{abre}{base_txt}{fecha}")
            linha_cols[2].markdown("⏳ pendente" if r["manual"] else "✅")

        st.markdown("---")
        if "11.3" in totais:
            pagar_total = totais["11.3"]["valor_pis"] + totais["11.3"]["valor_cofins"]
            _cartao_totais(
                "Resultado da Apuração — Líquido a pagar em DARF", "🧾", COR_RESULTADO,
                None, totais["11.1"]["valor_pis"], totais["11.2"]["valor_cofins"],
            )
            st.markdown(f"""
<div style="text-align:center; margin-top:-10px;">
  <span style="font-size:0.85rem; opacity:0.7;">Total DARF (PIS + COFINS)</span><br>
  <span style="font-size:2rem; font-weight:800; color:{COR_RESULTADO};">{formatar_moeda(pagar_total)}</span>
</div>
""", unsafe_allow_html=True)

        n_pendentes_manual = sum(1 for r in linhas_salvas if r["manual"])
        if n_pendentes_manual:
            st.warning(
                f"{n_pendentes_manual} linha(s) desta apuração ainda são manuais/pendentes (valor zerado) — "
                f"ver 'Pontos em aberto' na metodologia do projeto. Se algum desses valores existir neste "
                f"período (ex: receita de aluguel recebido, ICMS Substituição, Exportação, IPI), considere "
                f"isso ao ler o resultado final."
            )

# ---------------------------------------------------------------------------------------------- Conferência
with aba_conferencia:
    st.caption(
        "Comparação por CFOP entre o resultado da Rotina 1024 (usado na apuração) e a soma direta de "
        "valor_pis/valor_cofins do Relatório 1096 (item a item) — só leitura, não muda nenhum valor "
        "calculado. Diferenças acima de R$ 1,00 aparecem como 'Divergente'; CFOPs que só aparecem em uma "
        "das duas fontes também são sinalizados."
    )
    linhas_conf = _cache_conferencia(session, competencia_id)
    if not linhas_conf:
        st.info("Nenhum dado de Rotina 1024 nem de Relatório 1096 importado ainda para este grupo/período.")
    else:
        fc1, fc2, fc3 = st.columns([1.3, 1.7, 1.5])
        f_operacao = fc1.selectbox("Operação", ["Todas", "entrada", "saida"], key="conf_f_operacao")
        situacoes_disponiveis = sorted({l["situacao"] for l in linhas_conf})
        f_situacao = fc2.multiselect("Situação", situacoes_disponiveis, default=situacoes_disponiveis,
                                      key="conf_f_situacao")
        f_cfop = fc3.text_input("Filtrar por CFOP", key="conf_f_cfop")

        linhas_filtradas = [
            l for l in linhas_conf
            if (f_operacao == "Todas" or l["tipo_operacao"] == f_operacao)
            and l["situacao"] in f_situacao
            and (not f_cfop.strip() or str(l["cfop"]).startswith(f_cfop.strip()))
        ]

        n_div = sum(1 for l in linhas_conf if l["situacao"] not in ("OK",))
        if n_div:
            st.warning(f"{n_div} CFOP(s) com divergência ou presentes em só uma das fontes (no total, sem "
                       f"considerar o filtro acima).")
        else:
            st.success("Todos os CFOPs batem entre Rotina 1024 e Relatório 1096 (dentro da tolerância).")

        if not linhas_filtradas:
            st.info("Nenhum CFOP corresponde aos filtros selecionados.")
        else:
            st.caption(f"Mostrando {len(linhas_filtradas)} de {len(linhas_conf)} CFOP(s).")
            df_conf = pd.DataFrame(linhas_filtradas)
            for col in ("pis_1024", "cofins_1024", "pis_1096", "cofins_1096", "diff_pis", "diff_cofins"):
                df_conf[col] = df_conf[col].apply(lambda v: formatar_moeda(v) if v is not None else "—")
            st.dataframe(df_conf, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------------------------- Inconsistências
with aba_inconsist:
    if df_inc.empty:
        st.success("Nenhuma inconsistência registrada.")
    else:
        pendentes = df_inc[df_inc["status"] == "pendente"]
        st.caption(f"{len(pendentes)} pendente(s) de {len(df_inc)} no total.")

        fi1, fi2, fi3, fi4, fi5 = st.columns(5)
        status_disp = sorted(df_inc["status"].unique())
        f_status = fi1.multiselect("Status", status_disp, default=["pendente"] if "pendente" in status_disp
                                    else status_disp, key="inc_f_status")
        tipo_disp = sorted(df_inc["tipo"].unique())
        # A primeira análise costuma ser só com base nas regras de CST × CFOP/NCM criadas para o 1096
        # (entrada e saída) — por isso o filtro de Tipo já abre marcado só nesses 3 tipos
        # (cst_regra_cfop/cst_regra_ncm/cst_regra_alerta), se existir algum. cst_nao_mapeado/cfop_sem_grupo
        # continuam disponíveis pra marcar manualmente, só não vêm pré-selecionados aqui.
        tipos_regra_presentes = [t for t in tipo_disp if t in TIPOS_REGRA]
        default_tipo = tipos_regra_presentes if tipos_regra_presentes else tipo_disp
        f_tipo = fi2.multiselect("Tipo", tipo_disp, default=default_tipo, key="inc_f_tipo",
                                  help="Por padrão mostra só as regras de CST × CFOP/NCM criadas para o "
                                       "1096 (entrada/saída) — marque os outros tipos se quiser ver "
                                       "cst_nao_mapeado/cfop_sem_grupo também.")
        operacao_disp = sorted(v for v in df_inc["tipo_operacao"].unique() if v)
        f_operacao = fi3.multiselect("Operação", operacao_disp, default=operacao_disp, key="inc_f_operacao")
        fonte_disp = sorted(df_inc["fonte"].unique())
        f_fonte = fi4.multiselect("Fonte", fonte_disp, default=fonte_disp, key="inc_f_fonte",
                                   help="rotina_1024 = bloqueia o CFOP na apuração • relatorio_1096 = só "
                                        "conferência, não afeta o valor calculado.")
        filial_disp = sorted(df_inc["filial"].unique())
        f_filial = fi5.multiselect("Filial", filial_disp, default=filial_disp, key="inc_f_filial")

        df_filtrado = df_inc[
            df_inc["status"].isin(f_status)
            & df_inc["tipo"].isin(f_tipo)
            & (df_inc["tipo_operacao"].isin(f_operacao) | df_inc["tipo_operacao"].isna())
            & df_inc["fonte"].isin(f_fonte)
            & df_inc["filial"].isin(f_filial)
        ]

        if df_filtrado.empty:
            st.info("Nenhuma inconsistência corresponde aos filtros selecionados.")
        else:
            st.caption(f"Mostrando {len(df_filtrado)} de {len(df_inc)} inconsistência(s).")
            _mostrar_resumo_por_tipo(df_filtrado, "inc_geral")
            st.divider()
            for _, row in df_filtrado.iterrows():
                _card_inconsistencia(session, row, csts_disponiveis, "inc_geral")

    st.divider()
    st.subheader("Histórico de ajustes manuais de CST")
    st.caption(
        "Lista de correções registradas nesta tela — use como checklist para corrigir de fato no Winthor. "
        "Registrar aqui não muda nenhum valor calculado."
    )
    historico = _cache_historico_ajustes(session, competencia_id)
    if not historico:
        st.caption("Nenhum ajuste registrado ainda nesta competência.")
    else:
        df_hist = pd.DataFrame(historico, columns=["id", "inconsistencia_id", "cst_original", "cst_corrigido",
                                                     "observacao", "ajustado_em", "cfop", "ncm",
                                                     "tipo_operacao", "descricao", "filial"])
        df_hist = df_hist.drop(columns=["id", "inconsistencia_id"])
        st.dataframe(df_hist, use_container_width=True, hide_index=True)
        st.download_button(
            "Baixar histórico (CSV)",
            df_hist.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"ajustes_cst_pc_{competencia_id}.csv",
            mime="text/csv",
        )

    st.divider()
    # Estrutura igual ao módulo ICMS normal: lista de exceções "aprendidas" (marcadas com 'replicar' num
    # card acima) — o analista pode desativar aqui se a situação mudar e quiser voltar a ser avisado sobre
    # aquele mesmo caso.
    with st.expander("🔁 Exceções conhecidas (regras aplicadas automaticamente nas próximas apurações)"):
        st.caption(
            "Quando você marca 'replicar nas próximas apurações' num card de inconsistência acima, a regra "
            "entra aqui — escopada por filial. Desative se a situação mudar e você quiser voltar a ser "
            "avisado sobre esse mesmo caso."
        )
        excecoes = _cache_excecoes(session, empresa_ids_grupo)
        if not excecoes:
            st.caption("Nenhuma exceção cadastrada ainda para este grupo.")
        # st.container (não st.expander) aqui dentro — expanders não podem ser aninhados no Streamlit, e
        # este bloco já está dentro do expander "Exceções conhecidas" acima.
        for exc in excecoes:
            status_txt = "🟢 ativa" if exc["ativa"] else "⚪ desativada"
            with st.container(border=True):
                st.markdown(f"**[{exc['tipo']}] {exc['chave_agrupamento']}** — {exc['filial']} — {status_txt}")
                st.write(exc["justificativa"])
                st.caption(f"Criada por {exc['criado_por_email'] or '?'} em {exc['created_at']:%d/%m/%Y %H:%M}")
                if exc["ativa"]:
                    if st.button("Desativar (voltar a sinalizar este caso)", key=f"desativar_exc_{exc['id']}"):
                        definir_excecao_ativa(session, exc["id"], False)
                        _cache_excecoes.clear()
                        st.rerun()
                else:
                    if st.button("Reativar", key=f"reativar_exc_{exc['id']}"):
                        definir_excecao_ativa(session, exc["id"], True)
                        _cache_excecoes.clear()
                        st.rerun()
