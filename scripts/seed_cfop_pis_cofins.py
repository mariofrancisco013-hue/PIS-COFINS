"""
Carrega a tabela CFOP × PIS/COFINS (data/cfop_pis_cofins.csv) no banco — classifica cada CFOP na linha da
apuração em que ele entra (ver metodologia no projeto Claude "PIS/COFINS").

Uso:
    python scripts/seed_cfop_pis_cofins.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.lib.db import get_session  # noqa: E402
from sqlalchemy import text  # noqa: E402

DATA_CSV = Path(__file__).resolve().parent.parent / "data" / "cfop_pis_cofins.csv"


def main():
    with DATA_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    session = get_session()
    for r in rows:
        session.execute(text("""
            insert into cfop_pis_cofins (codigo, descricao, direcao, grupo_padrao)
            values (:codigo, :descricao, :direcao, :grupo)
            on conflict (codigo) do update
                set descricao = excluded.descricao, direcao = excluded.direcao,
                    grupo_padrao = excluded.grupo_padrao, updated_at = now()
        """), {
            "codigo": int(r["codigo"]), "descricao": r["descricao"] or None,
            "direcao": r["direcao"], "grupo": r["grupo_padrao"],
        })
    session.commit()
    print(f"{len(rows)} CFOPs carregados/atualizados.")


if __name__ == "__main__":
    main()
