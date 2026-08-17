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
    select c.cnpj_raiz,
           coalesce(
               (select e2.razao_social from empresas e2
                where e2.cnpj_raiz = c.cnpj_raiz and e2.razao_social ilike '%matriz%'
                order by e2.razao_social limit 1),
               (select min(e3.razao_social) from empresas e3 where e3.cnpj_raiz = c.cnpj_raiz)
           ) as nome_grupo,
           c.ano, c.mes, c.status,
           (select count(distinct empresa_id) from resumo_1024_pc r where r.competencia_id = c.id) as n_filiais_1024,
           (select count(*) from relatorio_pc_itens r where r.competencia_id = c.id) as n_itens_1096,
           (select count(*) from inconsistencias_pc i where i.competencia_id = c.id and i.status = 'pendente') as n_pendentes
    from competencias c
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
        column_order=["nome_grupo", "ano", "mes", "status", "situação", "n_filiais_1024", "n_itens_1096",
                       "n_pendentes"],
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
