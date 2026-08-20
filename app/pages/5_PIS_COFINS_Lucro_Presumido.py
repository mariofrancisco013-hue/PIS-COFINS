"""
PIS/COFINS — Lucro Presumido (regime cumulativo). Construída em 19/08/2026, primeira versão — reaproveita a
MESMA infraestrutura de importação do Lucro Real (ver `1_Importar_Relatorios.py`, seletor de "Módulo") e as
mesmas tabelas (`resumo_1024_pc`, `relatorio_pc_itens`, `apuracao_pc_linhas`), já que `competencias.modulo`
distingue os dois desde o schema inicial (14/08/2026). O motor de cálculo está em
`lib/calculo_pis_cofins_lucro_presumido.py` — leia a docstring de lá antes de mexer aqui (ela documenta as
diferenças de metodologia em relação ao Lucro Real e os pontos em aberto).

Escopo inicial (19/08/2026): só Apuração + Conferência 1024×1096. Sem "Ajustes Manuais"/grade editável do
Relatório 1096 — extensível depois, seguindo o mesmo padrão de arquivos.

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
pra extrair um módulo compartilhado só por causa desta adição). Continua fora do escopo aqui: a grade
editável (Entrada/Saída) do Relatório 1096 — não foi pedida, e as inconsistências continuam visíveis/
gerenciáveis pela aba ⚠️ Inconsistências sem precisar dela.
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
from lib.formatacao import formatar_moeda, rotulo_empresa
from lib.status_apuracao_pc import status_competencia
from lib import importacao_pc, resumo_pc, planilha_pc
from lib.calculo_pis_cofins_lucro_presumido import (
    calcular_apuracao_pc_presumido, salvar_apuracao_pc_presumido, ordenar_linhas_para_exibicao,
    LAYOUT_LINHAS, conferencia_1024_x_1096_presumido, detalhar_cfop_presumido,
)
from lib.cst_regras_pc import (
    registrar_ajuste_cst, carregar_historico_ajustes, TIPOS_REGRA, registrar_revisao, carregar_excecoes,
    definir_excecao_ativa, listar_cfops_sem_checagem, salvar_cfops_sem_checagem, listar_regras_cfop,
    salvar_regras_cfop, listar_regras_ncm, salvar_regras_ncm, listar_regras_alerta, salvar_regras_alerta,
)

MODULO = "pis_cofins_lucro_presumido"
REGIME_LIKE = "Lucro Presumido%"

# Tipos de inconsistência que carregam um CST passível de ajuste manual (mesmo conjunto do Lucro Real — ver
# lib/cst_regras_pc.py; cfop_sem_grupo não tem CST associado, fica de fora).
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


def _card_inconsistencia(session, row, csts_disponiveis, key_prefix):
    """Card de inconsistência — cópia adaptada de `2_PIS_COFINS_Lucro_Real.py::_card_inconsistencia` (ver lá
    a docstring completa sobre o motivo do `key_prefix`: a mesma inconsistência pode, em tese, aparecer em
    mais de uma seção da tela no mesmo run do Streamlit, e sem prefixo os widgets colidem
    — `StreamlitDuplicateElementKey`, bug real já visto em produção no Lucro Real em 18/08/2026)."""
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


def _aba_regras_cst(session):
    """Cópia de `2_PIS_COFINS_Lucro_Real.py::_aba_regras_cst` — as 3 tabelas de regra são globais
    (compartilhadas entre Presumido e Real), então editar aqui também vale para o Lucro Real e vice-versa."""
    st.markdown(
        "**Para que serve esta aba:** cadastro das regras de CST × CFOP/NCM usadas pela checagem automática "
        "do Relatório 1096 (ver aba ⚠️ Inconsistências) — mesmas 3 tabelas já usadas pelo Lucro Real "
        "(`cst_regra_cfop_pc`/`cst_regra_ncm_pc`/`cst_regra_alerta_pc`, globais entre os dois regimes). "
        "Regras são **globais** (valem para todas as filiais de todos os grupos, dos dois regimes), "
        "diferente da aba 🚫 CFOPs sem Checagem de CST, que é por filial."
    )
    st.warning(
        "Depois de incluir, editar ou remover uma regra, as inconsistências só refletem a mudança na "
        "próxima vez que o Relatório 1096 for reimportado (Presumido ou Real)."
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
            st.success(f"{resultado['incluidos']} incluída(s), {resultado['atualizados']} atualizada(s), "
                       f"{resultado['removidos']} removida(s).")
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
            st.success(f"{resultado['incluidos']} incluída(s), {resultado['atualizados']} atualizada(s), "
                       f"{resultado['removidos']} removida(s).")
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

(aba_apuracao, aba_conferencia, aba_regras_cst, aba_cfop_sem_checagem, aba_inconsist) = st.tabs([
    "📋 Apuração", "📎 Conferência 1024×1096", "🔖 Regras de CST", "🚫 CFOPs sem Checagem de CST",
    "⚠️ Inconsistências",
])

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

        cab = st.columns([5, 2, 2, 1.3])
        cab[0].markdown("**Linha**")
        cab[1].markdown("**Base**")
        cab[2].markdown("**PIS / COFINS**")
        cab[3].markdown("**Situação**")

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
            pis_cofins_txt = "—"
            if r["valor_pis"] or r["valor_cofins"]:
                pis_cofins_txt = f"PIS {formatar_moeda(r['valor_pis'])} / COFINS {formatar_moeda(r['valor_cofins'])}"
            linha_cols = st.columns([5, 2, 2, 1.3])
            linha_cols[0].markdown(f"{indent}{abre}{r['linha']} — {r['descricao']}{fecha}",
                                    unsafe_allow_html=True)
            linha_cols[1].markdown(f"{abre}{base_txt}{fecha}")
            linha_cols[2].markdown(f"{abre}{pis_cofins_txt}{fecha}")
            linha_cols[3].markdown("⏳ pendente" if r["manual"] else "✅")

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
    _aba_regras_cst(session)

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
                _card_inconsistencia(session, row, csts_disponiveis, "pres_inc_geral")

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
