import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from lib.auth import require_login, logout_button
from lib.db import get_session
from lib.formatacao import rotulo_empresa
from lib import importacao_pc
from lib.importar_1024_pc import importar_1024

st.set_page_config(page_title="Importar Relatórios", layout="wide")
require_login()
logout_button()
st.title("Importar Relatórios — PIS/COFINS")
st.caption(
    "A apuração é feita por **grupo** (CNPJ raiz — matriz + filiais consolidadas). Para cada filial do "
    "grupo, importe a **Rotina 1024** (Livro RAICMS Modelo P9, .pdf — fonte usada no cálculo) e, se quiser "
    "conferir, o **Relatório 1096** (\"Relatório por combinação de CFOP, CST, NCM e alíquota - Analítico\", "
    "aba 'Report', .xlsx — usado só para comparação por CFOP, não entra mais direto na apuração)."
)

session = get_session()
grupos = importacao_pc.listar_grupos(session)
if not grupos:
    st.warning("Nenhuma empresa em regime Lucro Real cadastrada ainda. Cadastre/ajuste o regime em "
               "**Empresas** antes de importar.")
    st.stop()

col1, col2, col3 = st.columns(3)
grupo = col1.selectbox(
    "Grupo (CNPJ raiz)", grupos,
    format_func=lambda g: f"{g['nome_grupo']} — {g['n_filiais']} filial(is)",
)
ano = col2.number_input("Ano", min_value=2020, max_value=2100, value=2026, step=1)
mes = col3.number_input("Mês", min_value=1, max_value=12, value=7, step=1)

status_filiais, competencia_id = importacao_pc.status_filiais_grupo(session, grupo["cnpj_raiz"], ano, mes)

st.markdown("---")
st.subheader("Status das filiais do grupo neste período")
df_status = pd.DataFrame(status_filiais)
if not df_status.empty:
    df_status = df_status.rename(columns={
        "filial_winthor": "Filial Winthor", "razao_social": "Razão Social", "cnpj": "CNPJ",
        "cfops_1024": "CFOPs (Rotina 1024)", "itens_1096_entrada": "Itens 1096 Entrada",
        "itens_1096_saida": "Itens 1096 Saída",
    })
    st.dataframe(
        df_status[["Filial Winthor", "Razão Social", "CNPJ", "CFOPs (Rotina 1024)", "Itens 1096 Entrada",
                   "Itens 1096 Saída"]],
        use_container_width=True, hide_index=True,
    )
    n_sem_1024 = sum(1 for f in status_filiais if f["cfops_1024"] == 0)
    if n_sem_1024:
        st.warning(f"{n_sem_1024} filial(is) do grupo ainda sem Rotina 1024 importada neste período — a "
                   f"apuração consolidada só fica completa depois que todas tiverem.")

st.markdown("---")
st.subheader("Importar para uma filial")
filiais = importacao_pc.listar_filiais_grupo(session, grupo["cnpj_raiz"])
filial = st.selectbox("Filial", filiais, format_func=rotulo_empresa)

aba_1024, aba_1096 = st.tabs(["Rotina 1024 (usado no cálculo)", "Relatório 1096 (só conferência)"])

with aba_1024:
    st.caption("PDF do Livro Registro de Apuração do ICMS (RAICMS Modelo P9) desta filial, com as seções "
               "Entradas e Saídas — o mesmo arquivo que já vai para o módulo ICMS.")
    arq_1024 = st.file_uploader("Rotina 1024 (.pdf)", type=["pdf"], key="arq_1024")

    ja_tem_1024 = any(f["id"] == filial["id"] and f["cfops_1024"] > 0 for f in status_filiais)
    substituir_1024 = st.checkbox(
        "Substituir Rotina 1024 já importada desta filial neste período", value=False,
        disabled=not ja_tem_1024, key="sub_1024",
    )
    if ja_tem_1024 and not substituir_1024:
        st.info("Esta filial já tem Rotina 1024 importada neste período — marque 'substituir' para "
                "reimportar (PDF corrigido).")

    if st.button("Importar Rotina 1024", type="primary", disabled=not arq_1024):
        with st.spinner("Lendo PDF..."):
            try:
                cid = importacao_pc.get_or_create_competencia_grupo(session, grupo["cnpj_raiz"], ano, mes)
                resultado = importar_1024(session, filial["id"], cid, arq_1024, substituir_1024)
                st.success(resultado)
                st.rerun()
            except ValueError as e:
                st.error(str(e))

with aba_1096:
    st.caption("Aba 'Report' do Relatório 1096, sem cabeçalho, .xlsx — usado só para comparar por CFOP com "
               "o resultado da Rotina 1024 (aba Apuração → Conferência) e para checar CST fora da tabela "
               "oficial. Não é mais somado direto na apuração.")
    c1, c2 = st.columns(2)
    arq_entrada = c1.file_uploader("Relatório 1096 — Entrada (.xlsx)", type=["xlsx"], key="arq_1096_entrada")
    arq_saida = c2.file_uploader("Relatório 1096 — Saída (.xlsx)", type=["xlsx"], key="arq_1096_saida")

    n_entrada = next((f["itens_1096_entrada"] for f in status_filiais if f["id"] == filial["id"]), 0)
    n_saida = next((f["itens_1096_saida"] for f in status_filiais if f["id"] == filial["id"]), 0)
    ja_tem_1096 = (arq_entrada and n_entrada) or (arq_saida and n_saida)
    if ja_tem_1096:
        st.warning("Esta filial já tem itens importados do tipo que você está enviando agora — marque "
                   "'substituir' para reimportar (relatório corrigido) sem duplicar.")
    substituir_1096 = st.checkbox(
        "Substituir Relatório 1096 já importado desta filial (só do(s) arquivo(s) enviados agora)",
        value=False, disabled=not ja_tem_1096, key="sub_1096",
    )

    if st.button("Importar Relatório 1096", type="primary", disabled=not (arq_entrada or arq_saida)):
        with st.spinner("Importando..."):
            try:
                cid = importacao_pc.get_or_create_competencia_grupo(session, grupo["cnpj_raiz"], ano, mes)
                resultado = importacao_pc.importar_1096(
                    session, filial["id"], cid, arq_entrada, arq_saida, substituir_1096,
                )
                st.success(resultado)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
