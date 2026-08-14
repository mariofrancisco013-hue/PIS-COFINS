import streamlit as st
from lib.auth import require_login, logout_button
from lib.db import get_session
from lib.status_apuracao_pc import classificar_status
from sqlalchemy import text

st.set_page_config(page_title="Apuração PIS/COFINS", layout="wide")
require_login()
logout_button()

st.title("Apuração PIS/COFINS")
st.caption("Grupo Sodine — módulo Lucro Real (não-cumulativo), construído em 14/08/2026")

session = get_session()
resumo = session.execute(text("""
    select e.razao_social, e.regime, c.ano, c.mes, c.status,
           (select count(*) from relatorio_pc_itens r where r.competencia_id = c.id) as n_itens,
           (select count(*) from inconsistencias_pc i where i.competencia_id = c.id and i.status = 'pendente') as n_pendentes
    from competencias c
    join empresas e on e.id = c.empresa_id
    where c.modulo = 'pis_cofins_lucro_real'
    order by c.ano desc, c.mes desc
""")).mappings().all()

if not resumo:
    st.info("Nenhuma competência importada ainda. Use a página **Importar Relatórios** no menu à esquerda.")
else:
    st.subheader("Competências")
    linhas = []
    for r in resumo:
        r = dict(r)
        r["situação"] = classificar_status(r["status"], r["n_pendentes"])["texto"]
        linhas.append(r)
    st.dataframe(
        linhas, use_container_width=True,
        column_order=["razao_social", "regime", "ano", "mes", "status", "situação", "n_itens", "n_pendentes"],
    )

st.markdown("---")
st.markdown(
    "Use o menu à esquerda: **Importar Relatórios** (Relatório 1096 de Entrada/Saída), **PIS/COFINS Lucro "
    "Real** (resumo por CFOP/CST, ajustes manuais de Aluguéis e Depreciação, a apuração final e a revisão "
    "de inconsistências — tudo em abas dentro dessa página), **Empresas** (cadastro do grupo — o campo "
    "Regime decide quais empresas aparecem aqui) e **CFOP/CST** (tabelas de referência e exceções)."
)
st.caption(
    "Módulo em desenvolvimento: **PIS/COFINS Lucro Real**. Módulo futuro: PIS/COFINS Lucro Presumido "
    "(regime cumulativo). Metodologia completa documentada no projeto Claude \"PIS/COFINS\"."
)
