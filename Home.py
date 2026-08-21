import streamlit as st
from lib.auth import require_login, logout_button
from lib.db import get_session
from lib.status_apuracao_pc import classificar_status
from lib.theme_sodine import inject_main_theme, kpi_card, section_title, badge
from sqlalchemy import text

st.set_page_config(page_title="Apuração PIS/COFINS", layout="wide")
require_login()
logout_button()
inject_main_theme()

st.title("Apuração PIS/COFINS")
st.caption("Grupo Sodine — Painel Consolidado (Lucro Real e Lucro Presumido)")

session = get_session()
resumo = session.execute(text("""
    select c.cnpj_raiz,
           coalesce(
               (select e2.razao_social from empresas e2
                where e2.cnpj_raiz = c.cnpj_raiz and e2.razao_social ilike '%matriz%'
                order by e2.razao_social limit 1),
               (select min(e3.razao_social) from empresas e3 where e3.cnpj_raiz = c.cnpj_raiz)
           ) as nome_grupo,
           c.ano, c.mes, c.status, c.modulo,
           (select count(distinct empresa_id) from resumo_1024_pc r where r.competencia_id = c.id) as n_filiais_1024,
           (select count(*) from relatorio_pc_itens r where r.competencia_id = c.id) as n_itens_1096,
           (select count(*) from inconsistencias_pc i where i.competencia_id = c.id and i.status = 'pendente') as n_pendentes
    from competencias c
    where c.modulo in ('pis_cofins_lucro_real', 'pis_cofins_lucro_presumido')
    order by c.ano desc, c.mes desc
""")).mappings().all()

# --- Cards de KPI (Painel Consolidado) --------------------------------------------------------------
# Reaproveita só os dados que a query acima já traz (contagens/status) — nenhum cálculo de apuração novo
# é rodado aqui. Uma Home com totais financeiros (Base/Débitos/Créditos/DARF, como no mockup) exigiria
# rodar a apuração completa de toda competência a cada carregamento da página; isso é escopo de dado/
# performance novo, não de identidade visual, e ficou de fora dessa rodada (ver nota em theme_sodine.py).
linhas = [dict(r) for r in resumo]
n_competencias = len(linhas)
n_calculadas = sum(1 for r in linhas if r["status"] == "calculada")
n_pendentes_total = sum(r["n_pendentes"] for r in linhas)
n_real = sum(1 for r in linhas if r["modulo"] == "pis_cofins_lucro_real")
n_presumido = sum(1 for r in linhas if r["modulo"] == "pis_cofins_lucro_presumido")

col1, col2, col3, col4 = st.columns(4)
kpi_card(col1, "Competências Importadas", str(n_competencias),
         f"{n_real} Lucro Real · {n_presumido} Lucro Presumido")
kpi_card(col2, "Apurações Calculadas", str(n_calculadas),
         f"{n_competencias - n_calculadas} aguardando cálculo" if n_competencias else "—")
kpi_card(col3, "Inconsistências Pendentes", str(n_pendentes_total),
         "revisar na aba Inconsistências de cada apuração" if n_pendentes_total else "nenhuma pendência")
kpi_card(col4, "Situação Geral", "OK" if n_pendentes_total == 0 and n_competencias else "Atenção",
         "sem pendências em aberto" if n_pendentes_total == 0 and n_competencias else "há itens a revisar",
         variante="dark")

st.markdown("")

# --- Atalhos rápidos ----------------------------------------------------------------------------------
section_title("🧭", "Atalhos")
a1, a2, a3, a4 = st.columns(4)
with a1:
    st.page_link("pages/1_Importar_Relatorios.py", label="Importar Relatórios", icon="📥")
with a2:
    st.page_link("pages/2_PIS_COFINS_Lucro_Real.py", label="PIS/COFINS Lucro Real", icon="🧮")
with a3:
    st.page_link("pages/5_PIS_COFINS_Lucro_Presumido.py", label="PIS/COFINS Lucro Presumido", icon="🧮")
with a4:
    st.page_link("pages/4_CFOP_CST.py", label="CFOP/CST", icon="🔖")

st.markdown("")

# --- Tabela de competências, com badge de status no padrão da identidade visual ------------------------
section_title("📋", "Competências", badge_texto=f"{n_competencias}" if n_competencias else None)
if not resumo:
    st.info("Nenhuma competência importada ainda. Use o atalho **Importar Relatórios** acima.")
else:
    rotulo_modulo = {"pis_cofins_lucro_real": "Lucro Real", "pis_cofins_lucro_presumido": "Lucro Presumido"}
    for r in linhas:
        situacao = classificar_status(r["status"], r["n_pendentes"])
        variante = {"success": "success", "warning": "warning", "info": "neutral"}.get(situacao["nivel"], "neutral")
        with st.container(border=True):
            c_nome, c_mod, c_filiais, c_itens, c_status = st.columns([3, 2, 1.4, 1.4, 2.2])
            c_nome.markdown(f"**{r['nome_grupo'] or r['cnpj_raiz']}** — {r['mes']:02d}/{r['ano']}")
            c_mod.markdown(rotulo_modulo.get(r["modulo"], r["modulo"]))
            c_filiais.markdown(f"{r['n_filiais_1024']} filiais (1024)")
            c_itens.markdown(f"{r['n_itens_1096']} itens (1096)")
            with c_status:
                badge(situacao["texto"] if situacao["nivel"] != "warning" else f"{r['n_pendentes']} pendência(s)",
                      variante)

st.markdown("---")
st.markdown(
    "Use o menu à esquerda: **Importar Relatórios** (Relatório 1096 de Entrada/Saída e Rotina 1024), "
    "**PIS/COFINS Lucro Real** e **PIS/COFINS Lucro Presumido** (resumo por CFOP/CST, ajustes manuais, a "
    "apuração final e a revisão de inconsistências — tudo em abas dentro de cada página), **Empresas** "
    "(cadastro do grupo — o campo Regime decide em qual módulo cada empresa aparece) e **CFOP/CST** "
    "(tabelas de referência e exceções)."
)
st.caption("Metodologia completa documentada no projeto Claude \"PIS/COFINS\".")
