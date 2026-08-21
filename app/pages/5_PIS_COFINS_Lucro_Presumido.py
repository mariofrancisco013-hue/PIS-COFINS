"""
PIS/COFINS — Lucro Presumido (regime cumulativo). Construída em 19/08/2026, primeira versão — reaproveita a
MESMA infraestrutura de importação do Lucro Real (ver `1_Importar_Relatorios.py`, seletor de "Módulo") e as
mesmas tabelas (`resumo_1024_pc`, `relatorio_pc_itens`, `apuracao_pc_linhas`), já que `competencias.modulo`
distingue os dois desde o schema inicial (14/08/2026). O motor de cálculo está em
`lib/calculo_pis_cofins_lucro_presumido.py` — leia a docstring de lá antes de mexer aqui (ela documenta as
diferenças de metodologia em relação ao Lucro Real e os pontos em aberto).

Escopo inicial (19/08/2026): só Apuração + Conferência 1024×1096 — extensível depois, seguindo o mesmo
padrão de arquivos.

REGRAS DE CST / CFOPS SEM CHECAGEM / INCONSISTÊNCIAS (20/08/2026): as 3 tabelas de regra (`cst_regra_cfop_
pc`, `cst_regra_ncm_pc`, `cst_regra_alerta_pc`, migração `sql/004_regras_cst_pc.sql`) e a checagem
automática (`cst_regras_pc.registrar_inconsistencias_cst_regras`) são GLOBAIS/compartilhadas entre os dois
regimes — `importacao_pc.importar_1096` já roda essa checagem pra toda importação, Presumido incluído, desde
sempre. Só não havia TELA aqui pra ver/gerenciar isso (só existia em `2_PIS_COFINS_Lucro_Real.py`). Pedido
do usuário em 20/08/2026 ("criar uma aba dentro do lucro presumido com ela", depois "paridade completa com
o Lucro Real"): as 3 abas — 🔖 Regras de CST, 🚫 CFOPs sem Checagem de CST, ⚠️ Inconsistências — foram
portadas para cá, reaproveitando 100% do backend já existente em `lib/cst_regras_pc.py` (nenhuma função de
lá é específica de regime) e `lib/resumo_pc.py`/`lib/planilha_pc.LABELS_INCONSISTENCIA`. As funções de UI
(`_card_inconsistencia`, `_resumo_por_tipo`, `_mostrar_resumo_por_tipo`, `_aba_regras_cst`,
`_aba_cfops_sem_checagem`) são cópias adaptadas das mesmas funções em `2_PIS_COFINS_Lucro_Real.py` — o
Lucro Real NÃO foi tocado nesta mudança (arquivo em produção, já validado; risco desnecessário refatorar
pra extrair um módulo compartilhado só por causa desta adição).

GRADE EDITÁVEL ENTRADA/SAÍDA (sessão de continuação, 20/08/2026): pedido do usuário ("ainda não colocou a
aba para que eu valide as inconsistencias da 1096", esclarecido como a grade item a item do Relatório 1096,
que só o Lucro Real tinha até aqui). Abas 📥 Entrada / 📤 Saída, cópia adaptada de
`2_PIS_COFINS_Lucro_Real.py::_aba_planilha_pc` — `lib/planilha_pc.py` já é 100% regime-agnóstico, não
precisou de nenhuma mudança de backend. Confirmado com o usuário: na direção Entrada, só a Devolução de
Venda (linha "1.2") é relevante para este regime cumulativo (sem crédito de entrada) — é normal a grade só
trazer os CFOPs 1202/1411/2202/2411/3202; na direção Saída, a grade traz TODOS os CFOPs do Relatório 1096,
sem restringir aos grupos "1.1"/"1.4" da apuração (mesmo comportamento do Lucro Real).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy import text

from lib.auth import require_login, logout_button, usuario_atual
from lib.db import get_session
from lib import theme_sodine
from lib.formatacao import formatar_moeda, rotulo_empresa
from lib.status_apuracao_pc import status_competencia
from lib import importacao_pc, resumo_pc, planilha_pc
from lib.calculo_pis_cofins_lucro_presumido import (
    calcular_apuracao_pc_presumido, salvar_apuracao_pc_presumido, ordenar_linhas_para_exibicao,
    LAYOUT_LINHAS, conferencia_1024_x_1096_presumido, detalhar_cfop_presumido, CFOPS_1_2_DEVOLUCAO_VENDA,
)
from lib.cst_regras_pc import (
    registrar_ajuste_cst, aplicar_ajuste_cst, escopo_ajuste_seguro, carregar_historico_ajustes, TIPOS_REGRA,
    registrar_revisao, carregar_excecoes, definir_excecao_ativa, listar_cfops_sem_checagem,
    salvar_cfops_sem_checagem, listar_regras_cfop, salvar_regras_cfop, listar_regras_ncm, salvar_regras_ncm,
    listar_regras_alerta, salvar_regras_alerta, registrar_inconsistencias_cst_regras,
    adicionar_regra_cfop, adicionar_regra_ncm,
)
from lib import lancamentos_manuais_pc as lmpc

MODULO = "pis_cofins_lucro_presumido"
REGIME_LIKE = "Lucro Presumido%"

# Tipos de inconsistência que carregam um CST passível de ajuste manual (mesmo conjunto do Lucro Real — ver
# lib/cst_regras_pc.py; cfop_sem_grupo não tem CST associado, fica de fora). Desde 20/08/2026, o ajuste
# aplica de verdade (aplicar_ajuste_cst) quando o escopo é inequívoco — ver escopo_ajuste_seguro — mesmo
# comportamento novo do Lucro Real.
TIPOS_COM_CST_AJUSTAVEL = {"cst_nao_mapeado", "cst_regra_cfop", "cst_regra_ncm", "cst_regra_alerta"}

# Cache de leitura — mesmo padrão/motivo do Lucro Real (ver docstring de _cache_* em 2_PIS_COFINS_Lucro_
# Real.py: st.tabs() não evita reexecução, então sem cache toda consulta rodaria de novo a cada clique em
# QUALQUER aba). TTL é só rede de segurança — invalidação de verdade é .clear() explícito após cada gravação.
_TTL_ESTATICO = 300
_TTL_LEITURA = 30


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_inconsistencias(_session, competencia_id):
    return resumo_pc.carregar_inconsistencias(_session, competencia_id)


@st.cache_data(ttl=_TTL_ESTATICO, show_spinner=False)
def _cache_csts_disponiveis(_session):
    rows = _session.execute(text("select codigo, descricao from cst_pis_cofins order by codigo")).mappings().all()
    return [dict(r) for r in rows]


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
def _cache_excecoes(_session, empresa_ids):
    return [dict(r) for r in carregar_excecoes(_session, empresa_ids)]


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_historico_ajustes(_session, competencia_id):
    return [dict(r) for r in carregar_historico_ajustes(_session, competencia_id)]


# Novos em 20/08/2026 (sessão de continuação — pedido do usuário: "ainda não colocou a aba para que eu
# valide as inconsistencias da 1096" → esclarecido que faltava especificamente a grade editável Entrada/
# Saída, não a aba ⚠️ Inconsistências consolidada, que já existia). Mesmas funções (mesmo nome/assinatura) de
# `2_PIS_COFINS_Lucro_Real.py` — `lib/planilha_pc.py` e `lib/resumo_pc.py` já são 100% regime-agnósticos
# (só dependem de competencia_id/tipo_operacao/empresa_ids), não precisaram de nenhuma mudança.
#
# `cfops_permitidos` (ainda em 20/08/2026, segunda parte do pedido — "na entrada considerar somente CFOP de
# devolução", confirmado com o usuário que também vale pra grade/resumos, não só pra geração automática de
# inconsistências, ver cst_regras_pc.clausula_entrada_permitida_presumido): parâmetro NOVO, opcional,
# `None` por padrão — só quem chama (a função _aba_planilha_pc abaixo) decide passar
# `CFOPS_1_2_DEVOLUCAO_VENDA` quando `tipo_operacao == "entrada"`. Recebe uma TUPLE (não um frozenset/set) —
# st.cache_data precisa de um argumento hashable E com repr estável para a chave de cache; tuple ordenada
# cumpre os dois, frozenset também seria hashable mas sem ordem estável entre execuções.
@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_resumo_1024_por_cfop(_session, competencia_id, tipo_operacao, cfops_permitidos=None):
    return resumo_pc.resumo_1024_por_cfop(_session, competencia_id, tipo_operacao, cfops_permitidos)


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_resumo_por_cfop(_session, competencia_id, tipo_operacao, cfops_permitidos=None):
    return resumo_pc.resumo_por_cfop(_session, competencia_id, tipo_operacao, cfops_permitidos)


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_resumo_por_cst(_session, competencia_id, tipo_operacao, cfops_permitidos=None):
    return resumo_pc.resumo_por_cst(_session, competencia_id, tipo_operacao, cfops_permitidos)


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_itens_editavel(_session, competencia_id, tipo_operacao, empresa_ids, cfop_filtro, ncm_filtro,
                           busca, tipos_inc, limite, cfops_permitidos=None):
    return planilha_pc.carregar_itens_editavel(
        _session, competencia_id, tipo_operacao, empresa_ids, cfop_filtro, ncm_filtro, busca, tipos_inc,
        limite, cfops_permitidos,
    )


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_totalizador(_session, competencia_id, tipo_operacao, empresa_ids, cfop_filtro, ncm_filtro,
                        cfops_permitidos=None):
    return planilha_pc.carregar_totalizador(
        _session, competencia_id, tipo_operacao, empresa_ids, cfop_filtro, ncm_filtro, cfops_permitidos,
    )


@st.cache_data(ttl=_TTL_LEITURA, show_spinner=False)
def _cache_historico_edicoes(_session, competencia_id, tipo_operacao):
    return planilha_pc.carregar_historico_edicoes(_session, competencia_id, tipo_operacao)


def _card_inconsistencia(session, row, csts_disponiveis, key_prefix, competencia_id=None, empresa_ids=None):
    """Card de inconsistência — cópia adaptada de `2_PIS_COFINS_Lucro_Real.py::_card_inconsistencia` (ver lá
    a docstring completa sobre o motivo do `key_prefix`: a mesma inconsistência pode, em tese, aparecer em
    mais de uma seção da tela no mesmo run do Streamlit, e sem prefixo os widgets colidem
    — `StreamlitDuplicateElementKey`, bug real já visto em produção no Lucro Real em 18/08/2026).

    `empresa_ids` (novo, sessão de continuação de 21/08/2026): só usado pelo botão "➕ Cadastrar como regra"
    — ver mais abaixo — para recalcular as inconsistências do grupo/competência logo depois de cadastrar."""
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

        # ➕ Cadastrar como regra permanente (sessão de continuação, 21/08/2026) — pedido do usuário: "crie
        # uma forma de eu informar que aquele NCM deve ser adicionado a aba Regras de CST". Só aparece nos
        # casos "caso 1" de `_checar_regra_cfop`/`_checar_regra_ncm` (o achado já tem um CFOP ou NCM
        # específico, não o alerta consolidado por CST — ver `cst_regras_pc._inserir_grupo`/`_checar_regra_*`,
        # mesmo raciocínio de "escopo seguro" já usado no ajuste de CST). Usa o CST que já está no item como o
        # CST esperado da regra nova — decisão do usuário: um clique, sem digitar nada.
        if row["tipo"] == "cst_regra_cfop" and pd.notna(row.get("cfop")) and pd.notna(row.get("cst")):
            if st.button(
                f"➕ Cadastrar regra: CFOP {int(row['cfop'])} × CST {int(row['cst'])} ({row['tipo_operacao']})",
                key=f"{key_prefix}_add_regra_cfop_{row['id']}",
                help="Cadastra esta combinação na aba 🔖 Regras de CST → Por CFOP, assumindo que o CST atual "
                     "deste item está certo. Recalcula as inconsistências desta competência na hora.",
            ):
                adicionar_regra_cfop(
                    session, int(row["cst"]), int(row["cfop"]), row["tipo_operacao"],
                    observacao=f"Cadastrada a partir da inconsistência #{row['id']} (aba ⚠️ Inconsistências).",
                )
                if competencia_id is not None and empresa_ids:
                    with st.spinner("Recalculando inconsistências..."):
                        _recalcular_regras_cst_grupo(session, competencia_id, empresa_ids)
                _cache_regras_cfop.clear()
                _cache_inconsistencias.clear()
                _cache_itens_editavel.clear()
                st.success("Regra de CFOP cadastrada — inconsistências desta competência já recalculadas.")
                st.rerun()
        elif row["tipo"] == "cst_regra_ncm" and pd.notna(row.get("ncm")) and pd.notna(row.get("cst")):
            if st.button(
                f"➕ Cadastrar regra: NCM {row['ncm']} × CST {int(row['cst'])} ({row['tipo_operacao']})",
                key=f"{key_prefix}_add_regra_ncm_{row['id']}",
                help="Cadastra esta combinação na aba 🔖 Regras de CST → Por NCM, assumindo que o CST atual "
                     "deste item está certo. Recalcula as inconsistências desta competência na hora.",
            ):
                adicionar_regra_ncm(
                    session, int(row["cst"]), row["ncm"], row["tipo_operacao"],
                    observacao=f"Cadastrada a partir da inconsistência #{row['id']} (aba ⚠️ Inconsistências).",
                )
                if competencia_id is not None and empresa_ids:
                    with st.spinner("Recalculando inconsistências..."):
                        _recalcular_regras_cst_grupo(session, competencia_id, empresa_ids)
                _cache_regras_ncm.clear()
                _cache_inconsistencias.clear()
                _cache_itens_editavel.clear()
                st.success("Regra de NCM cadastrada — inconsistências desta competência já recalculadas.")
                st.rerun()

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
            seguro = escopo_ajuste_seguro(row)
            if seguro:
                st.caption(
                    "Registre qual CST deveria ter sido usado — desde 20/08/2026, isso CORRIGE de verdade o "
                    "CST em relatorio_pc_itens (mantendo o CST original no histórico) e recalcula a apuração "
                    "desta competência na hora:"
                )
            else:
                st.caption(
                    "Este CST aparece em itens de origens diferentes (sem um único CFOP/NCM associado) — "
                    "não dá pra corrigir automaticamente sem risco de mudar itens que talvez precisassem de "
                    "um CST diferente entre si. Registre aqui só como histórico/checklist do que precisa ser "
                    "corrigido na origem (Winthor); para aplicar de verdade, corrija item a item na grade "
                    "ou cadastre uma Regra de CST × CFOP/NCM (aba 🔖) para a próxima importação."
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
            rotulo_botao = "✅ Aplicar CST corrigido e recalcular" if seguro else "Registrar ajuste (só histórico)"
            if st.button(rotulo_botao, key=f"{key_prefix}_ajustar_{row['id']}"):
                if seguro:
                    resultado = aplicar_ajuste_cst(
                        session, row["id"], cst_corrigido, observacao_ajuste or None, usuario_atual(),
                    )
                    if competencia_id is not None:
                        linhas_recalc = calcular_apuracao_pc_presumido(session, competencia_id)
                        salvar_apuracao_pc_presumido(session, competencia_id, linhas_recalc)
                    _cache_inconsistencias.clear()
                    _cache_historico_ajustes.clear()
                    st.success(
                        f"CST corrigido em {resultado['n_itens_corrigidos']} item(ns) — apuração recalculada."
                    )
                else:
                    registrar_ajuste_cst(
                        session, row["id"], cst_corrigido,
                        observacao_ajuste or None, usuario_atual(),
                    )
                    _cache_inconsistencias.clear()
                    _cache_historico_ajustes.clear()
                st.rerun()


def _resumo_por_tipo(df):
    """Cópia de `2_PIS_COFINS_Lucro_Real.py::_resumo_por_tipo` — consolida inconsistências (já filtradas) numa
    linha por tipo (grupos/itens/pendentes)."""
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


def _secao_inconsistencias_operacao(session, df_inc, tipo_operacao, csts_disponiveis, key_prefix,
                                     competencia_id=None, empresa_ids=None):
    """Cópia de `2_PIS_COFINS_Lucro_Real.py::_secao_inconsistencias_operacao` — bloco de inconsistências +
    ajuste de CST, filtrado por operação (saida/entrada), usado nas abas Entrada/Saída (20/08/2026, sessão
    de continuação)."""
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
        _card_inconsistencia(session, row, csts_disponiveis, key_prefix, competencia_id, empresa_ids)


def _aba_planilha_pc(session, competencia_id, tipo_operacao, empresa_ids, df_inc, csts_disponiveis):
    """Cópia adaptada de `2_PIS_COFINS_Lucro_Real.py::_aba_planilha_pc` (20/08/2026, sessão de continuação —
    pedido do usuário: "ainda não colocou a aba para que eu valide as inconsistencias da 1096", esclarecido
    como a grade editável Entrada/Saída, que o Presumido nunca teve). `lib/planilha_pc.py` já é 100%
    regime-agnóstico (só filtra por competencia_id/tipo_operacao/empresa_ids) — nenhuma mudança de backend
    foi necessária, só esta função de UI (cópia, não extraída para módulo compartilhado — mesma decisão de
    arquitetura já tomada para `_card_inconsistencia`/`_aba_regras_cst`/`_aba_cfops_sem_checagem`: não tocar
    `2_PIS_COFINS_Lucro_Real.py`, arquivo em produção já validado).

    NOTA ESPECÍFICA DO PRESUMIDO (confirmada com o usuário): na direção **Entrada**, a única movimentação que
    entra na apuração deste regime é a Devolução de Venda (linha "1.2", CFOPs 1202/1411/2202/2411/3202 — ver
    `CFOPS_1_2_DEVOLUCAO_VENDA` em `calculo_pis_cofins_lucro_presumido.py`) — não há crédito de entrada
    (regime cumulativo). Na direção **Saída**, a grade mostra TODOS os CFOPs que aparecem no Relatório 1096,
    sem restringir aos grupos "1.1"/"1.4" da apuração — mesmo comportamento já usado no Lucro Real (a grade
    é sobre o 1096, que pode ter CFOPs fora dos grupos classificados, e a conferência/inconsistência precisa
    enxergar todos eles, não só os que a apuração usa).

    AVISO CRÍTICO, mostrado também na tela: editar aqui NUNCA muda a Apuração (que roda 100% sobre a Rotina
    1024) — só recalcula as inconsistências de CST × CFOP/NCM e a Conferência 1024×1096. Ver docstring de
    lib/planilha_pc.py para o raciocínio completo."""
    # Entrada do Lucro Presumido = só Devolução de Venda (sessão de continuação, 20/08/2026 — "na entrada
    # considerar somente CFOP de devolução", confirmado com o usuário que isso restringe também esta grade e
    # os resumos por CFOP/CST dela, não só a geração automática de inconsistências — ver
    # planilha_pc._clausula_cfops_permitidos / resumo_pc._clausula_cfops_permitidos). Tuple ordenada (não
    # set/frozenset) — argumento passa por st.cache_data, precisa de repr estável pra chave de cache.
    cfops_permitidos = tuple(sorted(CFOPS_1_2_DEVOLUCAO_VENDA)) if tipo_operacao == "entrada" else None

    st.info(
        "⚠️ Esta grade edita o **Relatório 1096** (conferência) — os valores da **Apuração** (linhas "
        "1.x-7.3, aba Apuração) continuam vindo 100% da **Rotina 1024** e NÃO mudam com uma edição aqui. "
        "O que muda ao salvar: as ⚠️ Inconsistências de CST × CFOP/NCM desta filial são recalculadas na hora, "
        "e a Conferência 1024×1096 reflete o novo valor na próxima vez que você abrir aquela aba."
    )
    if tipo_operacao == "entrada":
        st.caption(
            "Neste regime (cumulativo), só a Devolução de Venda (linha \"1.2\") vem do lado Entrada — não "
            "há crédito de entrada. Esta grade e os resumos abaixo já filtram só os CFOPs de devolução "
            "(1202/1411/2202/2411/3202); os demais CFOPs de entrada do 1096 (compras) não aparecem aqui "
            "porque não influenciam em nada a apuração do Presumido."
        )
    else:
        st.caption(
            "Ajuste diretamente na grade (igual planilha) se algum código de produto, NCM, CFOP ou valor "
            "estiver errado no relatório original. O CST não é editável aqui de propósito — use os cards de "
            "'Inconsistências desta operação', mais abaixo, ou a aba ⚠️ Inconsistências (fluxo com "
            "justificativa/histórico dedicado para CST)."
        )

    visao = st.radio(
        "Visão", ["Analítica (item a item)", "Sintética (totalizada por Filial, Produto e CST)"],
        horizontal=True, key=f"pres_visao_{tipo_operacao}",
    )
    sintetica = visao.startswith("Sintética")

    c1, c_ncm, c2, c3 = st.columns([2, 2, 3, 2])
    resumo_1096_cfop = _cache_resumo_por_cfop(session, competencia_id, tipo_operacao, cfops_permitidos)
    cfops_disponiveis = (["(todos)"] + sorted(resumo_1096_cfop["cfop"].tolist())) if not resumo_1096_cfop.empty else ["(todos)"]
    cfop_sel = c1.selectbox("Filtrar por CFOP", cfops_disponiveis, key=f"pres_cfop_{tipo_operacao}")
    cfop_filtro = None if cfop_sel == "(todos)" else int(cfop_sel)
    ncm_filtro = c_ncm.text_input(
        "Filtrar por NCM", key=f"pres_ncm_{tipo_operacao}", placeholder="ex: 8213 ou 82130000",
        help="Filtra por prefixo — '8213' pega qualquer NCM que comece com 8213, não só o código exato.",
    )

    if sintetica:
        limite = c3.number_input("Máx. linhas na tela", min_value=50, max_value=5000, value=500, step=50,
                                  key=f"pres_limite_{tipo_operacao}")
        tot = _cache_totalizador(session, competencia_id, tipo_operacao, empresa_ids,
                                  cfop_filtro, ncm_filtro or None, cfops_permitidos)
        st.caption(f"{len(tot)} combinação(ões) de Filial + Produto + CST"
                   f"{' para este CFOP/NCM' if (cfop_filtro or ncm_filtro) else ''}.")
        st.dataframe(
            tot.head(limite), use_container_width=True, height=420, hide_index=True,
            column_config={
                "filial": st.column_config.TextColumn("Filial"),
                "produto_codigo": st.column_config.TextColumn("Código Produto"),
                "cst": st.column_config.NumberColumn("CST"),
                "n_itens": st.column_config.NumberColumn("Nº itens"),
                "valor_contabil": st.column_config.NumberColumn("Valor Contábil", format="R$ %.2f"),
                "valor_tributado": st.column_config.NumberColumn("Valor Tributado", format="R$ %.2f"),
                "valor_pis": st.column_config.NumberColumn("Valor PIS", format="R$ %.2f"),
                "valor_cofins": st.column_config.NumberColumn("Valor COFINS", format="R$ %.2f"),
            },
        )
    else:
        busca = c2.text_input("Buscar por código do produto", key=f"pres_busca_{tipo_operacao}",
                               help="Nem o 1096 nem a Rotina 1024 trazem número de NF ou nome do "
                                    "fornecedor/cliente — a busca aqui é só pelo código do produto.")
        limite = c3.number_input("Máx. linhas na tela", min_value=50, max_value=5000, value=500, step=50,
                                  key=f"pres_limite_{tipo_operacao}")
        tipos_inc_sel = st.multiselect(
            "⚠️ Filtrar por tipo de inconsistência pendente",
            options=list(planilha_pc.LABELS_INCONSISTENCIA.keys()),
            format_func=lambda t: planilha_pc.LABELS_INCONSISTENCIA[t],
            key=f"pres_tipos_inc_{tipo_operacao}",
            help="Deixe vazio para mostrar todos os itens. Escolha um ou mais tipos para ver só os itens "
                 "com aquele erro específico pendente.",
        )

        df, total = _cache_itens_editavel(
            session, competencia_id, tipo_operacao, empresa_ids, cfop_filtro, ncm_filtro or None,
            busca or None, tipos_inc_sel or None, limite, cfops_permitidos,
        )

        if total > len(df):
            st.warning(f"Mostrando {len(df)} de {total} itens (refine o filtro ou aumente o limite acima — "
                       f"grades muito grandes deixam o navegador lento).")
        else:
            st.caption(f"{total} itens.")

        editado = st.data_editor(
            df, use_container_width=True, height=420, num_rows="fixed", key=f"pres_editor_pc_{tipo_operacao}",
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
                "valor_contabil": st.column_config.NumberColumn("Valor Contábil", format="R$ %.2f"),
                "valor_desconto": st.column_config.NumberColumn("Valor Desconto", format="R$ %.2f"),
                "valor_itens": st.column_config.NumberColumn("Valor Itens", format="R$ %.2f"),
                "valor_tributado": st.column_config.NumberColumn("Valor Tributado", format="R$ %.2f"),
                "aliq_pis": st.column_config.NumberColumn("Alíq. PIS %", format="%.4f"),
                "valor_pis": st.column_config.NumberColumn("Valor PIS", format="R$ %.2f"),
                "aliq_cofins": st.column_config.NumberColumn("Alíq. COFINS %", format="%.4f"),
                "valor_cofins": st.column_config.NumberColumn("Valor COFINS", format="R$ %.2f"),
                "valor_nao_tributado": st.column_config.NumberColumn("Valor Não Tributado", format="R$ %.2f"),
            },
        )
        if st.button("💾 Salvar alterações", key=f"pres_salvar_pc_{tipo_operacao}"):
            n, empresas_afetadas = planilha_pc.salvar_itens_editados(
                session, df, editado, competencia_id=competencia_id, tipo_operacao=tipo_operacao,
                usuario=usuario_atual(),
            )
            if n:
                with st.spinner("Recalculando inconsistências..."):
                    planilha_pc.recalcular_inconsistencias_apos_edicao(session, competencia_id, empresas_afetadas)
                _cache_itens_editavel.clear()
                _cache_totalizador.clear()
                _cache_resumo_por_cfop.clear()
                _cache_resumo_por_cst.clear()
                _cache_historico_edicoes.clear()
                _cache_inconsistencias.clear()
                st.success(
                    f"{n} linha(s) atualizada(s), {len(empresas_afetadas)} filial(is) recalculada(s) — o "
                    f"que foi corrigido já some da coluna ⚠️ Inconsistência aqui na grade e da aba "
                    f"Inconsistências. A Apuração (Rotina 1024) não foi alterada."
                )
            else:
                st.info("Nenhuma mudança detectada.")
            st.rerun()

        with st.expander("➕ Cadastrar regra de CST a partir desta grade"):
            st.caption(
                "Atalho para quando você já está olhando a grade e percebe que um CFOP ou NCM inteiro "
                "deveria ter uma regra fixa de CST (aba 🔖 Regras de CST). Usa o CST que já está nos itens "
                "abaixo — recalcula as inconsistências desta competência na hora, igual ao botão da aba "
                "⚠️ Inconsistências (pedido do usuário: \"crie uma forma de eu informar que aquele NCM deve "
                "ser adicionado a aba REGRAS DE CST\", 21/08/2026, sessão de continuação)."
            )
            col_cfop, col_ncm = st.columns(2)

            with col_cfop:
                st.markdown("**Por CFOP**")
                if cfop_filtro is None:
                    st.caption("Selecione um CFOP específico no filtro acima para cadastrar por CFOP.")
                elif df.empty:
                    st.caption("Nenhum item nesta grade para derivar o CST.")
                else:
                    csts_do_cfop = sorted(df["cst"].dropna().unique().tolist())
                    if len(csts_do_cfop) == 1:
                        cst_cfop_sel = int(csts_do_cfop[0])
                        st.caption(f"CST único encontrado nos itens deste CFOP: **{cst_cfop_sel}**.")
                    else:
                        cst_cfop_sel = st.selectbox(
                            "CST a cadastrar", [int(c) for c in csts_do_cfop],
                            key=f"pres_grade_regra_cfop_cst_{tipo_operacao}",
                            help="Este CFOP tem mais de um CST nos itens carregados — escolha qual vira regra.",
                        )
                    if st.button(
                        f"➕ Cadastrar CFOP {cfop_filtro} × CST {cst_cfop_sel} ({tipo_operacao})",
                        key=f"pres_grade_add_regra_cfop_{tipo_operacao}",
                    ):
                        adicionar_regra_cfop(
                            session, cst_cfop_sel, cfop_filtro, tipo_operacao,
                            observacao=f"Cadastrada a partir da grade editável ({tipo_operacao}), competência "
                                       f"{competencia_id}.",
                        )
                        with st.spinner("Recalculando inconsistências..."):
                            _recalcular_regras_cst_grupo(session, competencia_id, empresa_ids)
                        _cache_regras_cfop.clear()
                        _cache_inconsistencias.clear()
                        _cache_itens_editavel.clear()
                        st.success("Regra de CFOP cadastrada — inconsistências desta competência já recalculadas.")
                        st.rerun()

            with col_ncm:
                st.markdown("**Por NCM**")
                if df.empty:
                    st.caption("Nenhum item nesta grade para derivar o CST.")
                else:
                    ncms_disp = sorted(df["ncm"].dropna().unique().tolist())
                    if not ncms_disp:
                        st.caption("Nenhum NCM nos itens carregados.")
                    else:
                        ncm_sel = st.selectbox(
                            "NCM", ncms_disp, key=f"pres_grade_regra_ncm_{tipo_operacao}",
                            help="O filtro de NCM acima é por prefixo — escolha aqui o NCM exato que vai virar regra.",
                        )
                        csts_do_ncm = sorted(df.loc[df["ncm"] == ncm_sel, "cst"].dropna().unique().tolist())
                        if len(csts_do_ncm) == 1:
                            cst_ncm_sel = int(csts_do_ncm[0])
                            st.caption(f"CST único encontrado nos itens deste NCM: **{cst_ncm_sel}**.")
                        else:
                            cst_ncm_sel = st.selectbox(
                                "CST a cadastrar", [int(c) for c in csts_do_ncm],
                                key=f"pres_grade_regra_ncm_cst_{tipo_operacao}",
                                help="Este NCM tem mais de um CST nos itens carregados — escolha qual vira regra.",
                            )
                        if st.button(
                            f"➕ Cadastrar NCM {ncm_sel} × CST {cst_ncm_sel} ({tipo_operacao})",
                            key=f"pres_grade_add_regra_ncm_{tipo_operacao}",
                        ):
                            adicionar_regra_ncm(
                                session, cst_ncm_sel, ncm_sel, tipo_operacao,
                                observacao=f"Cadastrada a partir da grade editável ({tipo_operacao}), competência "
                                           f"{competencia_id}.",
                            )
                            with st.spinner("Recalculando inconsistências..."):
                                _recalcular_regras_cst_grupo(session, competencia_id, empresa_ids)
                            _cache_regras_ncm.clear()
                            _cache_inconsistencias.clear()
                            _cache_itens_editavel.clear()
                            st.success("Regra de NCM cadastrada — inconsistências desta competência já recalculadas.")
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
        resumo_1024_cfop = _cache_resumo_1024_por_cfop(session, competencia_id, tipo_operacao, cfops_permitidos)
        st.dataframe(resumo_1024_cfop, use_container_width=True, hide_index=True)
    with c_res2:
        st.subheader("Resumo por CST — Relatório 1096")
        st.dataframe(_cache_resumo_por_cst(session, competencia_id, tipo_operacao, cfops_permitidos),
                     use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Inconsistências desta operação (regras de CST do 1096)")
    st.caption(
        "Revisão com justificativa — para uma correção rápida e óbvia de CFOP/NCM/valor, use a grade "
        "editável acima em vez de vir até aqui."
    )
    _secao_inconsistencias_operacao(session, df_inc, tipo_operacao, csts_disponiveis, f"pres_inc_{tipo_operacao}",
                                     competencia_id, empresa_ids)


def _recalcular_regras_cst_grupo(session, competencia_id, empresa_ids):
    """Roda `registrar_inconsistencias_cst_regras` para cada filial do grupo NESTA competência — chamada
    logo após salvar uma regra em `_aba_regras_cst` (sessão de continuação, 21/08/2026: usuário cadastrou uma
    regra CFOP 5102/saída ↔ CST 6 e a inconsistência "CST × CFOP divergente" já existente na grade não
    sumiu — investigação: `salvar_regras_cfop`/`_ncm`/`_alerta` NUNCA recalculavam nada, de propósito, porque
    as regras são GLOBAIS e recalcular para TODO o sistema a cada salvamento seria caro; a tela só avisava
    "recalcula no próximo reimport do 1096", o que deixa a inconsistência velha na tela até lá — confuso,
    parecia bug). Como recalcular só as filiais da competência ABERTA na tela é barato (mesma operação que já
    roda a cada edição da grade Entrada/Saída, ver `planilha_pc.recalcular_inconsistencias_apos_edicao`),
    passou a rodar automaticamente ao salvar — a tela refletir a regra nova na hora, sem precisar reimportar
    nada. Continua sendo necessário reimportar o 1096 para competências FECHADAS/outras que não estejam
    abertas nesta tela — isso não mudou, só o caso comum (a competência que você está olhando agora) ficou
    imediato. `empresa_ids` vazio (grupo sem filial) não faz nada."""
    for empresa_id in empresa_ids:
        registrar_inconsistencias_cst_regras(session, competencia_id, empresa_id)


def _aba_regras_cst(session, competencia_id, empresa_ids):
    """Cópia de `2_PIS_COFINS_Lucro_Real.py::_aba_regras_cst` — as 3 tabelas de regra são globais
    (compartilhadas entre Presumido e Real), então editar aqui também vale para o Lucro Real e vice-versa.

    `competencia_id`/`empresa_ids` (novos parâmetros, sessão de continuação de 21/08/2026): só usados para
    recalcular as inconsistências desta competência/grupo logo após salvar uma regra — ver
    `_recalcular_regras_cst_grupo`. As regras em si continuam globais (afetam qualquer competência/regime que
    usar aquele CFOP/NCM/CST), só o recálculo imediato é escopado à competência aberta na tela."""
    st.markdown(
        "**Para que serve esta aba:** cadastro das regras de CST × CFOP/NCM usadas pela checagem automática "
        "do Relatório 1096 (ver aba ⚠️ Inconsistências) — mesmas 3 tabelas já usadas pelo Lucro Real "
        "(`cst_regra_cfop_pc`/`cst_regra_ncm_pc`/`cst_regra_alerta_pc`, globais entre os dois regimes). "
        "Regras são **globais** (valem para todas as filiais de todos os grupos, dos dois regimes), "
        "diferente da aba 🚫 CFOPs sem Checagem de CST, que é por filial."
    )
    st.warning(
        "Ao salvar, as inconsistências desta competência (a que você está vendo agora) são recalculadas na "
        "hora — outras competências (fechadas ou de outros grupos) só refletem a mudança na próxima vez que "
        "o Relatório 1096 delas for reimportado."
    )

    sub_cfop, sub_ncm, sub_alerta = st.tabs(["Por CFOP", "Por NCM", "Sempre-alerta (por CST)"])

    with sub_cfop:
        st.caption("CST esperado quando este CFOP aparecer no Relatório 1096, nesta direção (entrada/saída).")
        df_cfop = pd.DataFrame(_cache_regras_cfop(session))
        if df_cfop.empty:
            df_cfop = pd.DataFrame(columns=["id", "cst", "cfop", "tipo_operacao", "observacao", "created_at"])
        df_cfop_editado = st.data_editor(
            df_cfop, use_container_width=True, num_rows="dynamic", key="pres_editor_regras_cfop",
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
        if st.button("💾 Salvar regras por CFOP", key="pres_salvar_regras_cfop"):
            resultado = salvar_regras_cfop(session, df_cfop, df_cfop_editado)
            _cache_regras_cfop.clear()
            with st.spinner("Recalculando inconsistências desta competência..."):
                _recalcular_regras_cst_grupo(session, competencia_id, empresa_ids)
            _cache_inconsistencias.clear()
            _cache_itens_editavel.clear()
            st.success(f"{resultado['incluidos']} incluída(s), {resultado['atualizados']} atualizada(s), "
                       f"{resultado['removidos']} removida(s) — inconsistências desta competência já "
                       f"recalculadas.")
            st.rerun()

    with sub_ncm:
        st.caption("CST esperado quando este NCM aparecer no Relatório 1096, nesta direção (entrada/saída).")
        df_ncm = pd.DataFrame(_cache_regras_ncm(session))
        if df_ncm.empty:
            df_ncm = pd.DataFrame(columns=["id", "cst", "ncm", "tipo_operacao", "observacao", "created_at"])
        df_ncm_editado = st.data_editor(
            df_ncm, use_container_width=True, num_rows="dynamic", key="pres_editor_regras_ncm",
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
        if st.button("💾 Salvar regras por NCM", key="pres_salvar_regras_ncm"):
            resultado = salvar_regras_ncm(session, df_ncm, df_ncm_editado)
            _cache_regras_ncm.clear()
            with st.spinner("Recalculando inconsistências desta competência..."):
                _recalcular_regras_cst_grupo(session, competencia_id, empresa_ids)
            _cache_inconsistencias.clear()
            _cache_itens_editavel.clear()
            st.success(f"{resultado['incluidos']} incluída(s), {resultado['atualizados']} atualizada(s), "
                       f"{resultado['removidos']} removida(s) — inconsistências desta competência já "
                       f"recalculadas.")
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
            df_alerta, use_container_width=True, num_rows="dynamic", key="pres_editor_regras_alerta",
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
        if st.button("💾 Salvar regras sempre-alerta", key="pres_salvar_regras_alerta"):
            resultado = salvar_regras_alerta(session, df_alerta, df_alerta_editado)
            _cache_regras_alerta.clear()
            with st.spinner("Recalculando inconsistências desta competência..."):
                _recalcular_regras_cst_grupo(session, competencia_id, empresa_ids)
            _cache_inconsistencias.clear()
            _cache_itens_editavel.clear()
            st.success(f"{resultado['incluidos']} incluída(s), {resultado['atualizados']} atualizada(s), "
                       f"{resultado['removidos']} removida(s) — inconsistências desta competência já "
                       f"recalculadas.")
            st.rerun()


def _aba_cfops_sem_checagem(session, filiais_grupo):
    """Cópia de `2_PIS_COFINS_Lucro_Real.py::_aba_cfops_sem_checagem`."""
    st.markdown(
        "**Para que serve esta aba:** se um CFOP dispara inconsistência de CST recorrente por um motivo que "
        "você já conhece e não é erro de verdade, marque ele aqui em vez de justificar a mesma inconsistência "
        "todo mês — igual à aba equivalente do Lucro Real (e do módulo ICMS Normal)."
    )
    st.caption(
        "Itens desse CFOP deixam de entrar nas 3 checagens automáticas (regra por CFOP, regra por NCM, "
        "sempre-alerta) para esta filial, tanto nesta competência quanto nas futuras, até você remover o "
        "cadastro. Não afeta a Apuração, só as checagens automáticas. Cadastro por filial — diferente da "
        "aba 🔖 Regras de CST, que é global."
    )
    if not filiais_grupo:
        st.info("Nenhuma filial cadastrada para este grupo.")
        return
    filial_sel = st.selectbox("Filial", filiais_grupo, format_func=rotulo_empresa, key="pres_cfop_sv_filial")
    empresa_id = filial_sel["id"]

    df_sv = pd.DataFrame(_cache_cfops_sem_checagem(session, empresa_id))
    if df_sv.empty:
        df_sv = pd.DataFrame(columns=["id", "cfop", "descricao", "motivo", "criado_por_email", "created_at"])
    st.caption(f"{len(df_sv)} CFOP(s) marcado(s) como sem checagem para esta filial.")
    df_sv_editado = st.data_editor(
        df_sv, use_container_width=True, num_rows="dynamic", key=f"pres_editor_cfop_sv_{empresa_id}",
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
    if st.button("💾 Salvar CFOPs sem checagem", key=f"pres_salvar_cfop_sv_{empresa_id}"):
        resultado = salvar_cfops_sem_checagem(session, empresa_id, df_sv, df_sv_editado, usuario_atual())
        _cache_cfops_sem_checagem.clear()
        st.success(f"{resultado['incluidos']} incluído(s), {resultado['removidos']} removido(s). Reimporte "
                   f"o Relatório 1096 desta filial (ou aguarde a próxima importação) para as checagens "
                   f"refletirem a mudança.")
        st.rerun()

st.set_page_config(page_title="PIS/COFINS Lucro Presumido", layout="wide")
require_login()
logout_button()
theme_sodine.inject_main_theme()
st.title("PIS/COFINS — Lucro Presumido")
st.caption(
    "Regime cumulativo (Lei 9.718/1998) — PIS 0,65% / COFINS 3,00% sobre a Base de Cálculo, sem crédito de "
    "entrada. Base = Rotina 1024 (só Saída) − Devolução de Venda − ICMS destacado − CST 6/7 (isentos). "
    "Desde 20/08/2026, a linha \"3.1\" soma uma incidência residual (PIS 0,0650% / COFINS 0,30% — Lei "
    "Complementar 224/2025) sobre os itens CST 6/7 de 10 NCMs específicos, mesmo esses itens já estando "
    "dentro da exclusão \"2.1\". Use **Importar Relatórios** (módulo \"Lucro Presumido\") para subir a "
    "Rotina 1024 e o Relatório 1096 antes de calcular aqui."
)

session = get_session()
grupos = importacao_pc.listar_grupos(session, regime_like=REGIME_LIKE)
if not grupos:
    st.warning("Nenhuma empresa em regime Lucro Presumido cadastrada ainda.")
    st.stop()

col1, col2, col3 = st.columns(3)
grupo = col1.selectbox(
    "Grupo (CNPJ raiz)", grupos,
    format_func=lambda g: f"{g['nome_grupo']} — {g['n_filiais']} filial(is)",
)
ano = col2.number_input("Ano", min_value=2020, max_value=2100, value=2026, step=1)
mes = col3.number_input("Mês", min_value=1, max_value=12, value=7, step=1)

competencia_id = importacao_pc.buscar_competencia_grupo(session, grupo["cnpj_raiz"], ano, mes, modulo=MODULO)
if not competencia_id:
    st.info("Nenhum dado importado para este grupo/período ainda. Use **Importar Relatórios** (módulo "
            "\"Lucro Presumido\").")
    st.stop()

comp_row = session.execute(
    text("select status from competencias where id = :id"), {"id": competencia_id}
).mappings().first()
status = status_competencia(session, competencia_id, comp_row["status"])
getattr(st, status["nivel"])(status["texto"])

filiais_grupo = importacao_pc.listar_filiais_grupo(session, grupo["cnpj_raiz"])
empresa_ids_grupo = [f["id"] for f in filiais_grupo]

# Carregados uma vez, usados na aba Inconsistências — mesmo padrão do Lucro Real.
df_inc = _cache_inconsistencias(session, competencia_id)
csts_disponiveis = _cache_csts_disponiveis(session)


# Ordem das abas revista em 20/08/2026 (sessão de continuação — pedido do usuário: "ainda não colocou a aba
# para que eu valide as inconsistencias da 1096", esclarecido como a grade editável Entrada/Saída). Entrada/
# Saída entraram na frente, mesma posição/ordem de `2_PIS_COFINS_Lucro_Real.py` ("dado bruto primeiro,
# cadastros de regra depois, resultado por último") — paridade completa de ordem com o Real agora, não só de
# conteúdo (ver docstring do módulo, seção "🔖 Paridade com o Lucro Real").
(aba_entrada, aba_saida, aba_regras_cst, aba_cfop_sem_checagem, aba_ajustes, aba_apuracao, aba_conferencia,
 aba_inconsist) = st.tabs([
    "📥 Entrada", "📤 Saída", "🔖 Regras de CST", "🚫 CFOPs sem Checagem de CST", "🧮 Ajustes Manuais",
    "📋 Apuração", "📎 Conferência 1024×1096", "⚠️ Inconsistências",
])

with aba_entrada:
    _aba_planilha_pc(session, competencia_id, "entrada", empresa_ids_grupo, df_inc, csts_disponiveis)

with aba_saida:
    _aba_planilha_pc(session, competencia_id, "saida", empresa_ids_grupo, df_inc, csts_disponiveis)

# ---------------------------------------------------------------------------------------------- Ajustes Manuais
# Nova em 20/08/2026 (sessão de continuação — pedido do usuário: "criar lançamento manual para todas" as
# linhas que ficavam ⏳ pendente). Regime Presumido não tinha NENHUM lançamento manual até aqui (diferente
# do Lucro Real, que já tinha Aluguéis/Depreciação desde 14/08/2026) — mesmo padrão de formulário genérico
# do Real (ver lib/lancamentos_manuais_pc.py), só que com TIPOS_PRESUMIDO e as alíquotas do regime cumulativo
# (PIS 0,65% / COFINS 3,00%).
with aba_ajustes:
    st.caption(
        "Receitas/exclusões de PIS/COFINS que não vêm da Rotina 1024/Relatório 1096 — linhas 1.3 (Serviços), "
        "1.5 (Aluguel recebido), 1.6 (Demais Receitas), 2.2 (Monofásica) e 2.6 (Exportação) da apuração. "
        "Informe a base do mês — só a base entra no cálculo (neste regime, PIS e COFINS são apurados uma "
        "vez só, em cima da Base de Cálculo final \"3\"); o PIS (0,65%) e o COFINS (3,00%) mostrados abaixo "
        "são só de referência, calculados nesta mesma base."
    )
    with st.form("novo_lancamento_pc_presumido"):
        c1, c2 = st.columns(2)
        tipo_lanc = c1.selectbox("Tipo", list(lmpc.TIPOS_PRESUMIDO.keys()),
                                  format_func=lambda t: lmpc.TIPOS_PRESUMIDO[t])
        base_valor = c2.number_input("Base do mês (R$)", min_value=0.0, step=100.0, format="%.2f")
        descricao_lanc = st.text_input("Descrição", placeholder="ex: Serviço de instalação — julho/2026")
        if st.form_submit_button("Adicionar", type="primary"):
            if not descricao_lanc.strip():
                st.error("Informe uma descrição.")
            elif base_valor <= 0:
                st.error("Informe uma base maior que zero.")
            else:
                resultado = lmpc.adicionar(
                    session, competencia_id, tipo_lanc, descricao_lanc.strip(), base_valor, usuario_atual(),
                    aliq_pis=lmpc.ALIQ_PIS_PRESUMIDO, aliq_cofins=lmpc.ALIQ_COFINS_PRESUMIDO,
                )
                st.success(f"Lançamento adicionado — PIS {formatar_moeda(resultado['valor_pis'])}, "
                           f"COFINS {formatar_moeda(resultado['valor_cofins'])} (referência).")
                st.rerun()

    st.markdown("---")
    st.subheader("Lançamentos desta competência")
    lancamentos_presumido = lmpc.listar(session, competencia_id)
    lancamentos_presumido = [l for l in lancamentos_presumido if l["tipo"] in lmpc.TIPOS_PRESUMIDO]
    if not lancamentos_presumido:
        st.info("Nenhum lançamento manual ainda.")
    else:
        df_original_lanc = pd.DataFrame(lancamentos_presumido)
        df_original_lanc["tipo"] = df_original_lanc["tipo"].map(lmpc.TIPOS_PRESUMIDO)
        df_editado_lanc = st.data_editor(
            df_original_lanc, use_container_width=True, hide_index=True, num_rows="dynamic",
            disabled=["id", "tipo", "descricao", "base_valor", "valor_pis", "valor_cofins", "created_at"],
            column_config={
                "base_valor": st.column_config.NumberColumn("Base", format="R$ %.2f"),
                "valor_pis": st.column_config.NumberColumn("PIS (referência)", format="R$ %.2f"),
                "valor_cofins": st.column_config.NumberColumn("COFINS (referência)", format="R$ %.2f"),
            },
            key="grade_lancamentos_pc_presumido",
        )
        removidos_lanc = lmpc.excluir_removidos(session, df_original_lanc, df_editado_lanc)
        if removidos_lanc:
            st.success(f"{removidos_lanc} lançamento(s) excluído(s).")
            st.rerun()

    st.caption(
        "Depois de adicionar/remover um lançamento, clique em **🔄 Calcular apuração** (aba 📋 Apuração) "
        "para refletir na Base de Cálculo e no resultado final."
    )

# ---------------------------------------------------------------------------------------------- Apuração
with aba_apuracao:
    if st.button("🔄 Calcular apuração", type="primary"):
        linhas = calcular_apuracao_pc_presumido(session, competencia_id)
        salvar_apuracao_pc_presumido(session, competencia_id, linhas)
        st.success("Apuração calculada.")
        st.rerun()

    linhas_salvas = session.execute(text("""
        select linha, descricao, valor_pis, valor_cofins, manual, detalhe
        from apuracao_pc_linhas where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()

    if not linhas_salvas:
        st.info("Ainda não calculada — clique em 'Calcular apuração'.")
    else:
        def _base_da_linha(detalhe):
            if not detalhe or "base_total" not in detalhe:
                return None
            try:
                return Decimal(str(detalhe["base_total"]))
            except Exception:
                return None

        linhas_ordenadas = ordenar_linhas_para_exibicao(linhas_salvas)
        totais = {r["linha"]: r for r in linhas_salvas}

        cab = st.columns([5, 2, 1.5, 1.5, 1.3])
        cab[0].markdown("**Linha**")
        cab[1].markdown("**Base**")
        cab[2].markdown("**PIS**")
        cab[3].markdown("**COFINS**")
        cab[4].markdown("**Situação**")

        secao_atual = None
        for r in linhas_ordenadas:
            secao, _ordem, nivel = LAYOUT_LINHAS.get(r["linha"], ("Outras linhas", 999, 1))
            if secao != secao_atual:
                st.markdown(f"##### {secao}")
                secao_atual = secao
            destaque = nivel == 0
            indent = "&nbsp;&nbsp;&nbsp;&nbsp;" if not destaque else ""
            abre, fecha = ("**", "**") if destaque else ("", "")
            base = _base_da_linha(r["detalhe"])
            base_txt = formatar_moeda(base) if base is not None else "—"
            tem_tributo = bool(r["valor_pis"] or r["valor_cofins"])
            pis_txt = formatar_moeda(r["valor_pis"]) if tem_tributo else "—"
            cofins_txt = formatar_moeda(r["valor_cofins"]) if tem_tributo else "—"
            linha_cols = st.columns([5, 2, 1.5, 1.5, 1.3])
            linha_cols[0].markdown(f"{indent}{abre}{r['linha']} — {r['descricao']}{fecha}",
                                    unsafe_allow_html=True)
            linha_cols[1].markdown(f"{abre}{base_txt}{fecha}")
            linha_cols[2].markdown(f"{abre}{pis_txt}{fecha}")
            linha_cols[3].markdown(f"{abre}{cofins_txt}{fecha}")
            linha_cols[4].markdown("⏳ pendente" if r["manual"] else "✅")

        st.markdown("---")
        if "7.3" in totais:
            pagar_pis = totais["7.3"]["valor_pis"]
            pagar_cofins = totais["7.3"]["valor_cofins"]
            st.markdown(f"""
<div style="border-left: 6px solid #16a34a; background: rgba(148,163,184,0.08); border-radius: 10px;
            padding: 18px 24px; margin: 6px 0 22px 0; text-align:center;">
  <span style="font-size:0.85rem; opacity:0.7; text-transform:uppercase; letter-spacing:.04em;">
    Resultado da Apuração — Líquido a pagar em DARF</span><br>
  <span style="font-size:2rem; font-weight:800; color:#16a34a;">
    {formatar_moeda(pagar_pis + pagar_cofins)}</span><br>
  <span style="font-size:0.85rem; opacity:0.7;">
    PIS (DARF 8109): {formatar_moeda(pagar_pis)} • COFINS (DARF 2172): {formatar_moeda(pagar_cofins)}</span>
</div>
""", unsafe_allow_html=True)

        n_pendentes_manual = sum(1 for r in linhas_salvas if r["manual"])
        if n_pendentes_manual:
            st.warning(
                f"{n_pendentes_manual} linha(s) desta apuração ainda são manuais/pendentes (valor zerado) — "
                f"ex.: Prestação de Serviços, Aluguel de Bens, Demais Receitas, Contribuição Monofásica, "
                f"Exportação, PERD/COMP. Se algum desses valores existir neste período, considere isso ao "
                f"ler o resultado final."
            )

# ---------------------------------------------------------------------------------------------- Conferência
with aba_conferencia:
    st.caption(
        "Comparação por CFOP (só Saída) entre o resultado da Rotina 1024 (usado na apuração) e a soma direta "
        "de valor_pis/valor_cofins do Relatório 1096 — só leitura, não muda nenhum valor calculado. "
        "Diferenças acima de R$ 1,00 aparecem como 'Divergente'. **Correção de 20/08/2026, confirmada com o "
        "usuário conferindo item a item contra um 3º relatório do Winthor ('Relatório de conferência PIS/"
        "COFINS e ICMS'): o Relatório 1096 já está correto — ele exclui o ICMS destacado item a item "
        "certinho. A causa real de divergência é a fórmula da Rotina 1024 (`Vl.Contábil − Vl.ICMS do CFOP "
        "inteiro − Vl.Contábil dos itens CST 6/7`) descontar duas vezes o ICMS que pertence aos itens "
        "isentos (uma vez embutido no ICMS agregado do CFOP, outra vez porque o valor contábil inteiro "
        "desses itens já foi zerado à parte).** Causa provável \"ICMS destacado nos itens isentos\" = a "
        "razão diff_cofins ÷ diff_pis bate com 3% ÷ 0,65% (4,615) — a assinatura matemática desse duplo "
        "desconto; 'icms_isento_implicito' é o valor em R$ que esse duplo desconto está tirando da base, "
        "estimado a partir do próprio diff (a Rotina 1024 não separa ICMS por CST de PIS/COFINS, então não "
        "dá pra medir esse valor direto sem importar aquele 3º relatório). Só vale abrir o 'Detalhar um "
        "CFOP' abaixo pras linhas com causa 'Outra causa'."
    )
    linhas_conf = conferencia_1024_x_1096_presumido(session, competencia_id)
    if not linhas_conf:
        st.info("Nenhum dado de Rotina 1024 nem de Relatório 1096 (saída) importado ainda para este grupo/período.")
    else:
        import pandas as pd

        fc1, fc2 = st.columns([1.7, 1.5])
        situacoes_disponiveis = sorted({l["situacao"] for l in linhas_conf})
        f_situacao = fc1.multiselect("Situação", situacoes_disponiveis, default=situacoes_disponiveis,
                                      key="conf_pres_f_situacao")
        f_cfop = fc2.text_input("Filtrar por CFOP", key="conf_pres_f_cfop")

        linhas_filtradas = [
            l for l in linhas_conf
            if l["situacao"] in f_situacao and (not f_cfop.strip() or str(l["cfop"]).startswith(f_cfop.strip()))
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
            # "Causa provável" (corrigido em 20/08/2026 — ver docstring de `_linha_conferencia`): pra CFOPs
            # "Divergente", testa se a razão diff_cofins/diff_pis bate com 3%/0,65% (assinatura de ICMS
            # descontado 2x nos itens isentos pela fórmula do 1024). "icms_1024" é o ICMS agregado do CFOP
            # inteiro (só contexto, NÃO é a causa da divergência — é ~25x maior que ela na prática).
            # "icms_isento_implicito" é a estimativa (via diff) do ICMS só dos itens isentos, a causa real.
            df_conf = df_conf.rename(columns={"icms_1024": "icms_1024_num",
                                               "icms_isento_implicito": "icms_isento_implicito_num"})
            for col in ("pis_1024", "cofins_1024", "pis_1096", "cofins_1096", "diff_pis", "diff_cofins"):
                df_conf[col] = df_conf[col].apply(lambda v: formatar_moeda(v) if v is not None else "—")
            df_conf["icms_1024"] = df_conf["icms_1024_num"].apply(
                lambda v: formatar_moeda(v) if v is not None else "—")
            df_conf["icms_isento_implicito"] = df_conf["icms_isento_implicito_num"].apply(
                lambda v: formatar_moeda(v) if v is not None else "—")
            df_conf["causa_provavel"] = df_conf["causa_provavel"].fillna("—")
            colunas_exibir = ["cfop", "tipo_operacao", "pis_1024", "cofins_1024", "pis_1096", "cofins_1096",
                               "diff_pis", "diff_cofins", "icms_1024", "icms_isento_implicito", "situacao",
                               "causa_provavel"]
            st.dataframe(df_conf[colunas_exibir], use_container_width=True, hide_index=True)

        # -------------------------------------------------------------------------------------- Detalhar um CFOP
        st.markdown("---")
        st.subheader("🔍 Detalhar um CFOP")
        st.caption(
            "Mostra o insumo bruto por trás da linha acima: o que a Rotina 1024 trouxe por filial (lado "
            "\"1024\") e os itens do Relatório 1096 agrupados por CST, com a faixa de alíquota de PIS/COFINS "
            "usada em cada um (lado \"1096\"). Causa mais comum de divergência: a Rotina 1024 soma o CFOP "
            "inteiro e aplica uma alíquota só (0,65%/3%), mas o 1096 respeita a alíquota de cada item — se "
            "aparecer um CST com aliq_pis/aliq_cofins diferente de 0,65%/3% aqui embaixo (ex.: monofásica, "
            "ST, alíquota zero), é ele que está puxando a diferença."
        )
        cfops_disponiveis = sorted({l["cfop"] for l in linhas_conf})
        cfops_divergentes = sorted({l["cfop"] for l in linhas_conf if l["situacao"] != "OK"})
        cfop_detalhe = st.selectbox(
            "CFOP", cfops_disponiveis,
            index=cfops_disponiveis.index(cfops_divergentes[0]) if cfops_divergentes else 0,
            key="conf_pres_cfop_detalhe",
        )
        detalhe = detalhar_cfop_presumido(session, competencia_id, cfop_detalhe)

        dc1, dc2 = st.columns(2)
        with dc1:
            st.markdown("**Rotina 1024 — por filial**")
            if not detalhe["1024_por_filial"]:
                st.info("Nenhuma linha da Rotina 1024 para este CFOP nesta competência.")
            else:
                df_1024 = pd.DataFrame(detalhe["1024_por_filial"])
                df_1024["valor_contabil"] = df_1024["valor_contabil"].apply(formatar_moeda)
                df_1024["valor_icms"] = df_1024["valor_icms"].apply(formatar_moeda)
                st.dataframe(df_1024, use_container_width=True, hide_index=True)
        with dc2:
            st.markdown("**Relatório 1096 — por CST**")
            if not detalhe["1096_por_cst"]:
                st.info("Nenhum item do Relatório 1096 (saída) para este CFOP nesta competência.")
            else:
                df_1096 = pd.DataFrame(detalhe["1096_por_cst"])
                for col in ("valor_contabil", "valor_pis", "valor_cofins"):
                    df_1096[col] = df_1096[col].apply(formatar_moeda)
                df_1096["aliq_pis"] = df_1096.apply(
                    lambda r: f"{r['aliq_pis_min']:.4%}" if r["aliq_pis_min"] == r["aliq_pis_max"]
                    else f"{r['aliq_pis_min']:.4%} a {r['aliq_pis_max']:.4%}", axis=1,
                )
                df_1096["aliq_cofins"] = df_1096.apply(
                    lambda r: f"{r['aliq_cofins_min']:.4%}" if r["aliq_cofins_min"] == r["aliq_cofins_max"]
                    else f"{r['aliq_cofins_min']:.4%} a {r['aliq_cofins_max']:.4%}", axis=1,
                )
                st.dataframe(
                    df_1096[["cst", "cst_descricao", "n_itens", "valor_contabil", "aliq_pis", "valor_pis",
                              "aliq_cofins", "valor_cofins"]],
                    use_container_width=True, hide_index=True,
                )

# ---------------------------------------------------------------------------------------------- Regras de CST
with aba_regras_cst:
    _aba_regras_cst(session, competencia_id, empresa_ids_grupo)

# --------------------------------------------------------------------------------- CFOPs sem Checagem de CST
with aba_cfop_sem_checagem:
    _aba_cfops_sem_checagem(session, filiais_grupo)

# ------------------------------------------------------------------------------------------- Inconsistências
with aba_inconsist:
    if df_inc.empty:
        st.success("Nenhuma inconsistência registrada.")
    else:
        pendentes = df_inc[df_inc["status"] == "pendente"]
        st.caption(f"{len(pendentes)} pendente(s) de {len(df_inc)} no total.")

        fi1, fi2, fi3, fi4, fi5 = st.columns(5)
        status_disp = sorted(df_inc["status"].unique())
        f_status = fi1.multiselect("Status", status_disp, default=["pendente"] if "pendente" in status_disp
                                    else status_disp, key="pres_inc_f_status")
        tipo_disp = sorted(df_inc["tipo"].unique())
        # A primeira análise costuma ser só com base nas regras de CST × CFOP/NCM criadas para o 1096
        # (entrada e saída) — por isso o filtro de Tipo já abre marcado só nesses 3 tipos
        # (cst_regra_cfop/cst_regra_ncm/cst_regra_alerta), se existir algum. cst_nao_mapeado/cfop_sem_grupo
        # continuam disponíveis pra marcar manualmente, só não vêm pré-selecionados aqui.
        tipos_regra_presentes = [t for t in tipo_disp if t in TIPOS_REGRA]
        default_tipo = tipos_regra_presentes if tipos_regra_presentes else tipo_disp
        f_tipo = fi2.multiselect("Tipo", tipo_disp, default=default_tipo, key="pres_inc_f_tipo",
                                  help="Por padrão mostra só as regras de CST × CFOP/NCM criadas para o "
                                       "1096 (entrada/saída) — marque os outros tipos se quiser ver "
                                       "cst_nao_mapeado/cfop_sem_grupo também.")
        operacao_disp = sorted(v for v in df_inc["tipo_operacao"].unique() if v)
        f_operacao = fi3.multiselect("Operação", operacao_disp, default=operacao_disp, key="pres_inc_f_operacao")
        fonte_disp = sorted(df_inc["fonte"].unique())
        f_fonte = fi4.multiselect("Fonte", fonte_disp, default=fonte_disp, key="pres_inc_f_fonte",
                                   help="rotina_1024 = bloqueia o CFOP na apuração • relatorio_1096 = só "
                                        "conferência, não afeta o valor calculado.")
        filial_disp = sorted(df_inc["filial"].unique())
        f_filial = fi5.multiselect("Filial", filial_disp, default=filial_disp, key="pres_inc_f_filial")

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
            _mostrar_resumo_por_tipo(df_filtrado, "pres_inc_geral")
            st.divider()
            for _, row in df_filtrado.iterrows():
                _card_inconsistencia(session, row, csts_disponiveis, "pres_inc_geral", competencia_id,
                                      empresa_ids_grupo)

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
            file_name=f"ajustes_cst_pc_presumido_{competencia_id}.csv",
            mime="text/csv",
            key="pres_download_historico_ajustes",
        )

    st.divider()
    # Estrutura igual ao Lucro Real: lista de exceções "aprendidas" (marcadas com 'replicar' num card acima)
    # — o analista pode desativar aqui se a situação mudar e quiser voltar a ser avisado sobre aquele mesmo
    # caso. Exceções são compartilhadas entre os dois regimes (mesma tabela `excecoes_inconsistencia_pc`,
    # escopada por filial/tipo/chave_agrupamento, não por regime).
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
                    if st.button("Desativar (voltar a sinalizar este caso)", key=f"pres_desativar_exc_{exc['id']}"):
                        definir_excecao_ativa(session, exc["id"], False)
                        _cache_excecoes.clear()
                        st.rerun()
                else:
                    if st.button("Reativar", key=f"pres_reativar_exc_{exc['id']}"):
                        definir_excecao_ativa(session, exc["id"], True)
                        _cache_excecoes.clear()
                        st.rerun()
