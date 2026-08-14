import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from lib.auth import require_login, logout_button
from lib.db import get_session
from sqlalchemy import text

st.set_page_config(page_title="CFOP/CST — PIS/COFINS", layout="wide")
require_login()
logout_button()
st.title("CFOP × CST — Referência (PIS/COFINS)")

session = get_session()
aba_cfop, aba_cst = st.tabs(["CFOP por linha da apuração", "CST de PIS/COFINS"])

with aba_cfop:
    st.caption(
        "Classifica cada CFOP na linha da apuração em que ele entra (1.1/1.2/1.4/1.6 no débito, "
        "5.1/5.5/5.7/5.8 no crédito). `grupo_ajuste` sobrepõe o padrão quando preenchido — mesmo padrão do "
        "ajuste manual de CFOP do módulo ICMS. CFOP fora desta tabela aparece como inconsistência na "
        "apuração e fica de fora do cálculo até ser cadastrado aqui."
    )
    df_cfop = session.execute(text("""
        select codigo, descricao, direcao, grupo_padrao, grupo_ajuste, observacao
        from cfop_pis_cofins order by direcao, codigo
    """)).mappings().all()
    st.dataframe(df_cfop, use_container_width=True, hide_index=True)

    with st.expander("Cadastrar / ajustar CFOP"):
        with st.form("cfop_pc_form"):
            c1, c2, c3 = st.columns(3)
            codigo = c1.number_input("Código CFOP", min_value=1000, max_value=7999, step=1)
            direcao = c2.selectbox("Direção", ["entrada", "saida"])
            grupo = c3.selectbox("Grupo (padrão ou ajuste)", [
                "1.1", "1.2", "1.4", "1.6", "5.1", "5.5", "5.7", "5.8",
            ])
            descricao = st.text_input("Descrição")
            observacao = st.text_input("Observação (opcional)")
            if st.form_submit_button("Salvar", type="primary"):
                session.execute(text("""
                    insert into cfop_pis_cofins (codigo, descricao, direcao, grupo_padrao, observacao)
                    values (:codigo, :descricao, :direcao, :grupo, :obs)
                    on conflict (codigo) do update
                        set grupo_ajuste = :grupo, descricao = excluded.descricao,
                            observacao = excluded.observacao, updated_at = now()
                """), {"codigo": codigo, "descricao": descricao or None, "direcao": direcao, "grupo": grupo,
                       "obs": observacao or None})
                session.commit()
                st.success(f"CFOP {codigo} salvo/ajustado.")
                st.rerun()

with aba_cst:
    st.caption(
        "Tabela oficial da Receita Federal para CST de PIS/COFINS. `ajuste_manual` sobrepõe o padrão quando "
        "a empresa trata um CST diferente do previsto (raro) — mesmo padrão do `is_st_ajuste` do módulo "
        "ICMS. CST fora desta tabela aparece como inconsistência na apuração."
    )
    df_cst = session.execute(text("""
        select codigo, descricao, direcao, gera_direito_credito, gera_debito, ajuste_manual, observacao
        from cst_pis_cofins order by direcao, codigo
    """)).mappings().all()
    st.dataframe(df_cst, use_container_width=True, hide_index=True)
