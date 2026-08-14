import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from sqlalchemy import text

from lib.auth import require_login, logout_button, usuario_atual
from lib.db import get_session
from lib.formatacao import rotulo_empresa, formatar_moeda, coluna_moeda
from lib.status_apuracao_pc import status_competencia
from lib import importacao_pc, resumo_pc, lancamentos_manuais_pc as lmpc
from lib.calculo_pis_cofins_lucro_real import (
    calcular_apuracao_pc, salvar_apuracao_pc, ordenar_linhas_para_exibicao, LAYOUT_LINHAS, ORDEM_SECOES,
)

st.set_page_config(page_title="PIS/COFINS Lucro Real", layout="wide")
require_login()
logout_button()
st.title("PIS/COFINS — Lucro Real")

session = get_session()
empresas = session.execute(text("""
    select id, filial_winthor, razao_social, cnpj, regime from empresas
    where regime ilike 'Lucro Real%'
    order by filial_winthor, razao_social
""")).mappings().all()
if not empresas:
    st.warning("Nenhuma empresa em regime Lucro Real cadastrada ainda.")
    st.stop()

col1, col2, col3 = st.columns(3)
empresa = col1.selectbox("Empresa", empresas, format_func=rotulo_empresa)
ano = col2.number_input("Ano", min_value=2020, max_value=2100, value=2026, step=1)
mes = col3.number_input("Mês", min_value=1, max_value=12, value=7, step=1)

competencia_id = importacao_pc.buscar_competencia(session, empresa["cnpj"], ano, mes)
if not competencia_id:
    st.info("Nenhum dado importado para esta empresa/período ainda. Use **Importar Relatórios**.")
    st.stop()

comp_row = session.execute(text("select status from competencias where id = :id"), {"id": competencia_id}).mappings().first()
status = status_competencia(session, competencia_id, comp_row["status"])
getattr(st, status["nivel"])(status["texto"])

aba_saida, aba_entrada, aba_ajustes, aba_apuracao, aba_inconsist = st.tabs(
    ["Saída (Débito)", "Entrada (Crédito)", "Ajustes Manuais", "Apuração", "Inconsistências"]
)

# ---------------------------------------------------------------------------------------------- Saída
with aba_saida:
    st.subheader("Resumo por CFOP — Saída")
    df_cfop = resumo_pc.resumo_por_cfop(session, competencia_id, "saida")
    st.dataframe(df_cfop, use_container_width=True, hide_index=True)
    if (df_cfop["grupo"] == "(sem grupo)").any():
        st.warning("Há CFOPs de Saída sem grupo cadastrado (ficam de fora do cálculo) — veja a aba "
                   "Inconsistências ou cadastre em CFOP/CST.")

    st.subheader("Resumo por CST — Saída")
    st.dataframe(resumo_pc.resumo_por_cst(session, competencia_id, "saida"), use_container_width=True,
                 hide_index=True)

    with st.expander("Ver itens (analítico)"):
        c1, c2 = st.columns(2)
        cfop_f = c1.text_input("Filtrar por CFOP", key="cfop_saida")
        ncm_f = c2.text_input("Filtrar por prefixo de NCM", key="ncm_saida")
        df_itens, total = resumo_pc.carregar_itens(
            session, competencia_id, "saida",
            cfop_filtro=int(cfop_f) if cfop_f.strip().isdigit() else None,
            ncm_filtro=ncm_f or None,
        )
        if total > len(df_itens):
            st.caption(f"Mostrando {len(df_itens)} de {total} itens — refine o filtro para ver o restante.")
        st.dataframe(df_itens, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------------------------- Entrada
with aba_entrada:
    st.subheader("Resumo por CFOP — Entrada")
    df_cfop_e = resumo_pc.resumo_por_cfop(session, competencia_id, "entrada")
    st.dataframe(df_cfop_e, use_container_width=True, hide_index=True)
    if (df_cfop_e["grupo"] == "(sem grupo)").any():
        st.warning("Há CFOPs de Entrada sem grupo cadastrado (ficam de fora do cálculo) — veja a aba "
                   "Inconsistências ou cadastre em CFOP/CST.")

    st.subheader("Resumo por CST — Entrada")
    st.dataframe(resumo_pc.resumo_por_cst(session, competencia_id, "entrada"), use_container_width=True,
                 hide_index=True)

    with st.expander("Ver itens (analítico)"):
        c1, c2 = st.columns(2)
        cfop_f = c1.text_input("Filtrar por CFOP", key="cfop_entrada")
        ncm_f = c2.text_input("Filtrar por prefixo de NCM", key="ncm_entrada")
        df_itens_e, total_e = resumo_pc.carregar_itens(
            session, competencia_id, "entrada",
            cfop_filtro=int(cfop_f) if cfop_f.strip().isdigit() else None,
            ncm_filtro=ncm_f or None,
        )
        if total_e > len(df_itens_e):
            st.caption(f"Mostrando {len(df_itens_e)} de {total_e} itens — refine o filtro para ver o restante.")
        st.dataframe(df_itens_e, use_container_width=True, hide_index=True)

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

# ---------------------------------------------------------------------------------------------- Apuração
with aba_apuracao:
    if st.button("🔄 Calcular apuração", type="primary"):
        linhas = calcular_apuracao_pc(session, competencia_id)
        salvar_apuracao_pc(session, competencia_id, linhas)
        st.success("Apuração calculada.")
        st.rerun()

    linhas_salvas = session.execute(text("""
        select linha, descricao, valor_pis, valor_cofins, manual
        from apuracao_pc_linhas where competencia_id = :cid
    """), {"cid": competencia_id}).mappings().all()

    if not linhas_salvas:
        st.info("Ainda não calculado — clique em **Calcular apuração**.")
    else:
        # Mesma sequência/seções da planilha original (aba "PC") — ver LAYOUT_LINHAS no motor de cálculo.
        # Não usa st.dataframe aqui de propósito: precisamos de indentação e negrito por linha (sub-item
        # vs. total), que uma grade não faz — por isso a renderização é linha a linha com st.columns.
        linhas_ordenadas = ordenar_linhas_para_exibicao(linhas_salvas)
        totais = {r["linha"]: r for r in linhas_salvas}

        cab = st.columns([5, 2, 2, 1.3])
        cab[0].markdown("**Linha**")
        cab[1].markdown("**PIS**")
        cab[2].markdown("**COFINS**")
        cab[3].markdown("**Situação**")

        secao_atual = None
        for r in linhas_ordenadas:
            secao, _ordem, nivel = LAYOUT_LINHAS.get(r["linha"], ("Outras linhas", 999, 1))
            if secao != secao_atual:
                st.markdown(f"##### {secao}")
                secao_atual = secao
            destaque = nivel == 0  # linha de total da seção — negrito, sem indentação
            indent = "&nbsp;&nbsp;&nbsp;&nbsp;" if not destaque else ""
            abre, fecha = ("**", "**") if destaque else ("", "")
            linha_cols = st.columns([5, 2, 2, 1.3])
            linha_cols[0].markdown(f"{indent}{abre}{r['linha']} — {r['descricao']}{fecha}",
                                    unsafe_allow_html=True)
            linha_cols[1].markdown(f"{abre}{formatar_moeda(r['valor_pis'])}{fecha}")
            linha_cols[2].markdown(f"{abre}{formatar_moeda(r['valor_cofins'])}{fecha}")
            linha_cols[3].markdown("⏳ pendente" if r["manual"] else "✅")

        st.markdown("---")
        if "11.3" in totais:
            c1, c2, c3 = st.columns(3)
            c1.metric("Líquido a pagar — PIS", formatar_moeda(totais["11.1"]["valor_pis"]))
            c2.metric("Líquido a pagar — COFINS", formatar_moeda(totais["11.2"]["valor_cofins"]))
            c3.metric("Total DARF", formatar_moeda(
                totais["11.3"]["valor_pis"] + totais["11.3"]["valor_cofins"]
            ))

        n_pendentes_manual = sum(1 for r in linhas_salvas if r["manual"])
        if n_pendentes_manual:
            st.warning(
                f"{n_pendentes_manual} linha(s) desta apuração ainda são manuais/pendentes (valor zerado) — "
                f"ver 'Pontos em aberto' na metodologia do projeto. Se algum desses valores existir neste "
                f"período (ex: receita de aluguel recebido, energia elétrica, receitas financeiras), "
                f"considere isso ao ler o resultado final."
            )

# ---------------------------------------------------------------------------------------------- Inconsistências
with aba_inconsist:
    df_inc = resumo_pc.carregar_inconsistencias(session, competencia_id)
    if df_inc.empty:
        st.success("Nenhuma inconsistência registrada.")
    else:
        pendentes = df_inc[df_inc["status"] == "pendente"]
        st.caption(f"{len(pendentes)} pendente(s) de {len(df_inc)} no total.")
        for _, row in df_inc.iterrows():
            with st.container(border=True):
                c1, c2 = st.columns([4, 1])
                c1.markdown(f"**{row['descricao']}**")
                c1.caption(f"Tipo: {row['tipo']} • Operação: {row['tipo_operacao'] or '-'} • Status: {row['status']}")
                if row["status"] == "pendente":
                    if c2.button("Marcar revisado", key=f"rev_{row['id']}"):
                        resumo_pc.marcar_inconsistencia(session, row["id"], "revisado", usuario_atual())
                        st.rerun()
