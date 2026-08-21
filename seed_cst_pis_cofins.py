"""
Carrega a tabela oficial de CST de PIS/COFINS (data/cst_pis_cofins.csv) no banco.

Uso:
    python scripts/seed_cst_pis_cofins.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.lib.db import get_session  # noqa: E402
from sqlalchemy import text  # noqa: E402

DATA_CSV = Path(__file__).resolve().parent.parent / "data" / "cst_pis_cofins.csv"


def _bool(v):
    return True if str(v).strip().lower() == "true" else (False if str(v).strip().lower() == "false" else None)


def main():
    with DATA_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    session = get_session()
    for r in rows:
        session.execute(text("""
            insert into cst_pis_cofins (codigo, descricao, direcao, gera_direito_credito, gera_debito)
            values (:codigo, :descricao, :direcao, :credito, :debito)
            on conflict (codigo) do update
                set descricao = excluded.descricao, direcao = excluded.direcao,
                    gera_direito_credito = excluded.gera_direito_credito,
                    gera_debito = excluded.gera_debito, updated_at = now()
        """), {
            "codigo": int(r["codigo"]), "descricao": r["descricao"], "direcao": r["direcao"],
            "credito": _bool(r["gera_direito_credito"]), "debito": _bool(r["gera_debito"]),
        })
    session.commit()
    print(f"{len(rows)} CSTs carregados/atualizados.")


if __name__ == "__main__":
    main()
