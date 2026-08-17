"""
Importa o Relatório 1096 de Entrada e/ou Saída (.xlsx, aba "Report") de UMA FILIAL para a competência do
GRUPO (CNPJ raiz) dela — ano + mês. Wrapper de linha de comando sobre app/lib/importacao_pc.py (a mesma
lógica também é usada pela página Streamlit "Importar Relatórios"). Desde a v2 (14/08/2026), isso alimenta
só a CONFERÊNCIA — quem alimenta a apuração é a Rotina 1024, importada pela tela Streamlit (não tem CLI
ainda, o PDF é lido com pdfplumber via app/lib/importar_1024_pc.py).

Uso:
    python scripts/import_relatorios.py --empresa-cnpj 07.342.785/0001-20 --ano 2026 --mes 7 \
        --entrada "1096 - Entradas.xlsx" --saida "1096 - saidas.xlsx" [--substituir]
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.lib.db import get_session  # noqa: E402
from app.lib.importacao_pc import get_or_create_competencia_grupo, importar_1096  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--empresa-cnpj", required=True, help="CNPJ completo da FILIAL (não o CNPJ raiz)")
    p.add_argument("--ano", type=int, required=True)
    p.add_argument("--mes", type=int, required=True)
    p.add_argument("--entrada", help="caminho do Relatório 1096 de Entrada (.xlsx)")
    p.add_argument("--saida", help="caminho do Relatório 1096 de Saída (.xlsx)")
    p.add_argument("--substituir", action="store_true")
    args = p.parse_args()

    session = get_session()
    empresa = session.execute(
        text("select id, cnpj_raiz from empresas where cnpj = :cnpj"), {"cnpj": args.empresa_cnpj}
    ).mappings().first()
    if not empresa:
        raise SystemExit(f"Empresa com CNPJ {args.empresa_cnpj} não encontrada.")

    competencia_id = get_or_create_competencia_grupo(session, empresa["cnpj_raiz"], args.ano, args.mes)
    try:
        resultado = importar_1096(session, empresa["id"], competencia_id, args.entrada, args.saida,
                                   args.substituir)
    except ValueError as e:
        raise SystemExit(str(e))
    print(resultado)


if __name__ == "__main__":
    main()
