"""
Leitura automática do PDF da Rotina 1024 (Livro Registro de Apuração do ICMS - RAICMS - Modelo P9) — fonte
PRIMÁRIA da apuração de PIS/COFINS a partir de 14/08/2026 (ver metodologia no projeto Claude "PIS/COFINS").

Este parser (`parse_rotina_1024`) é uma cópia do `app/lib/importar_1024.py` do módulo ICMS — mesmo layout de
PDF, já validado em produção contra dados reais ("bateu exato contra a planilha real da Ultra Comércio em
07/08/2026"). Reaproveitado aqui em vez de escrito do zero para não reintroduzir bugs de parsing de PDF já
resolvidos lá.

Layout do PDF: cada CFOP aparece como uma linha de texto simples nas seções "Entradas" e "Saídas", assim:

    0 1102 4.166,01 4.166,01 833,19 0,00 0,00
    │ │    │        │        │      │     └─ Outras
    │ │    │        │        │      └─ Isentas/Não Tributadas
    │ │    │        │        └─ Imposto Creditado/Debitado (ICMS)
    │ │    │        └─ Base de Cálculo (do ICMS)
    │ │    └─ Valores Contábeis
    │ └─ CFOP ("Fiscal")
    └─ Código "Contabil" (sempre 0 nos arquivos vistos até agora)

Confirmado com o usuário em 14/08/2026: a base do PIS/COFINS por CFOP é `Valores Contábeis − Imposto
Creditado/Debitado (ICMS destacado)`. tipo_operacao (entrada/saída) não vem explícito por linha no texto
extraído — é derivado do próprio CFOP (1xxx-3xxx = entrada, 5xxx-7xxx = saída, convenção padrão da Nota
Técnica de CFOP), a mesma lógica usada em app/lib/calculo_icms_pe.py do módulo ICMS.

NOTA (18/08/2026): entre 14 e 18/08 esta versão chegou a excluir também a coluna "Isentas/Não Tributadas" da
base (5ª coluna numérica da linha, ao lado do ICMS) — tentativa de bater a Conferência 1024×1096 quando
apareceu divergência. O usuário decidiu reverter essa exclusão em 18/08/2026 ("não é necessária"); a base
voltou a ser só Valor Contábil − ICMS destacado.

NOTA (19/08/2026): a coluna "Outras" (6ª e última coluna numérica da linha) volta a ser capturada e gravada
(`valor_outras`, migração `sql/007_exclusoes_e_receitas_financeiras_pc.sql`) — pedido do usuário para
excluí-la da base junto com o ICMS (ver `calculo_pis_cofins_lucro_real.calcular_apuracao_pc`, linhas "2.5"/
"6.7"). "Isentas/Não Tributadas" (5ª coluna) continua descartada — só essa foi revertida em 18/08. O regex
sempre precisou casar as 6 colunas numéricas da linha (senão não bate), então capturar a 6ª é só adicionar
parênteses em volta dela, sem mudar o que o regex reconhece.
"""
import re
from decimal import Decimal

import pdfplumber
from sqlalchemy import text

from lib.cst_regras_pc import clausula_entrada_permitida_presumido

_LINHA_CFOP_RE = re.compile(
    r"^\d+\s+(\d{4})\s+([\d.]+,\d{2})\s+([\d.]+,\d{2})\s+([\d.]+,\d{2})\s+[\d.]+,\d{2}\s+([\d.]+,\d{2})$"
)


def _para_decimal(s: str) -> Decimal:
    return Decimal(s.replace(".", "").replace(",", "."))


def _tipo_operacao(cfop: int) -> str:
    primeiro_digito = cfop // 1000
    if primeiro_digito in (1, 2, 3):
        return "entrada"
    if primeiro_digito in (5, 6, 7):
        return "saida"
    raise ValueError(f"CFOP {cfop} fora da faixa conhecida (1000-7999) — não dá para saber se é entrada/saída.")


def parse_rotina_1024(arquivo) -> list[dict]:
    """`arquivo` é um caminho ou um buffer tipo st.file_uploader (PDF do RAICMS Modelo P9). Devolve uma
    lista de dicts {cfop, tipo_operacao, valor_contabil, valor_base_icms, valor_icms, valor_outras} — um por
    CFOP encontrado nas seções de Entradas e Saídas (ignora linhas de "Sub Totais"/"Totais"). Lança
    ValueError se nenhuma linha reconhecível for encontrada (arquivo no layout errado)."""
    resultado = []
    with pdfplumber.open(arquivo) as pdf:
        for page in pdf.pages:
            texto = page.extract_text() or ""
            for linha in texto.split("\n"):
                m = _LINHA_CFOP_RE.match(linha.strip())
                if not m:
                    continue
                cfop = int(m.group(1))
                if not (1000 <= cfop <= 7999):
                    continue
                resultado.append({
                    "cfop": cfop,
                    "tipo_operacao": _tipo_operacao(cfop),
                    "valor_contabil": _para_decimal(m.group(2)),
                    "valor_base_icms": _para_decimal(m.group(3)),
                    "valor_icms": _para_decimal(m.group(4)),
                    "valor_outras": _para_decimal(m.group(5)),
                })
    if not resultado:
        raise ValueError(
            "Não encontrei nenhuma linha de CFOP reconhecível neste PDF. Confira se é o arquivo certo "
            "(Livro Registro de Apuração do ICMS - RAICMS - Modelo P9) — o layout esperado é uma linha de "
            "texto por CFOP nas seções Entradas/Saídas, como '0 1102 4.166,01 4.166,01 833,19 0,00 0,00'."
        )
    return resultado


def checar_duplicacao_1024(session, competencia_id, empresa_id, substituir):
    """Mesmo padrão do 1096: bloqueia reimportação acidental a menos que 'substituir' esteja marcado —
    escopado por filial (empresa_id), já que múltiplas filiais convivem na mesma competência (grupo)."""
    n = session.execute(text("""
        select count(*) from resumo_1024_pc where competencia_id = :cid and empresa_id = :eid
    """), {"cid": competencia_id, "eid": empresa_id}).scalar()
    if n and not substituir:
        raise ValueError(
            f"Esta filial já tem {n} CFOPs importados da Rotina 1024 nesta competência. Marque 'substituir' "
            f"se este é um PDF corrigido (evita duplicar)."
        )
    if n and substituir:
        session.execute(
            text("delete from resumo_1024_pc where competencia_id = :cid and empresa_id = :eid"),
            {"cid": competencia_id, "eid": empresa_id},
        )
        session.execute(text("""
            delete from inconsistencias_pc
            where competencia_id = :cid and empresa_id = :eid and fonte = 'rotina_1024'
        """), {"cid": competencia_id, "eid": empresa_id})
        session.execute(text("delete from apuracao_pc_linhas where competencia_id = :cid"), {"cid": competencia_id})
        session.commit()
    return n or 0


def importar_1024(session, empresa_id, competencia_id, arquivo_pdf, substituir=False):
    """Fluxo completo pra uma filial: lê o PDF, checa duplicação, grava em resumo_1024_pc, sinaliza CFOP
    sem grupo cadastrado. Devolve uma mensagem curta pra tela."""
    linhas = parse_rotina_1024(arquivo_pdf)
    removidos = checar_duplicacao_1024(session, competencia_id, empresa_id, substituir)

    for l in linhas:
        session.execute(text("""
            insert into resumo_1024_pc
                (competencia_id, empresa_id, tipo_operacao, cfop, valor_contabil, valor_base_icms, valor_icms,
                 valor_outras)
            values (:cid, :eid, :tipo, :cfop, :vc, :vb, :vi, :vo)
            on conflict (competencia_id, empresa_id, cfop) do update
                set tipo_operacao = excluded.tipo_operacao, valor_contabil = excluded.valor_contabil,
                    valor_base_icms = excluded.valor_base_icms, valor_icms = excluded.valor_icms,
                    valor_outras = excluded.valor_outras, importado_em = now()
        """), {
            "cid": competencia_id, "eid": empresa_id, "tipo": l["tipo_operacao"], "cfop": l["cfop"],
            "vc": str(l["valor_contabil"]), "vb": str(l["valor_base_icms"]), "vi": str(l["valor_icms"]),
            "vo": str(l["valor_outras"]),
        })

    # Entrada do Lucro Presumido = só Devolução de Venda (sessão de continuação, 20/08/2026, "os outros não
    # precisa validar na presumido") — ver clausula_entrada_permitida_presumido em cst_regras_pc.py. Esta é a
    # checagem MAIS importante das 4 (Rotina 1024 é a fonte de que o cálculo do Presumido realmente lê, ver
    # calculo_pis_cofins_lucro_presumido._soma_bruta). Vazio (sem filtro) para o Lucro Real.
    params_cfop = {"cid": competencia_id, "eid": empresa_id}
    clausula_entrada = clausula_entrada_permitida_presumido(session, competencia_id, "r", params_cfop)
    cfops_ruins = session.execute(text(f"""
        select distinct r.cfop, r.tipo_operacao
        from resumo_1024_pc r
        left join cfop_pis_cofins cp on cp.codigo = r.cfop
        where r.competencia_id = :cid and r.empresa_id = :eid and cp.codigo is null
          {clausula_entrada}
    """), params_cfop).mappings().all()
    for r in cfops_ruins:
        session.execute(text("""
            insert into inconsistencias_pc (competencia_id, empresa_id, tipo, cfop, tipo_operacao, descricao, fonte)
            values (:cid, :eid, 'cfop_sem_grupo', :cfop, :tipo,
                    'CFOP ' || :cfop || ' (Rotina 1024) não está cadastrado em nenhum grupo da apuração '
                    || '(1.1/1.2/1.4/1.6 ou 5.1/5.2/5.5/5.7/5.8) — os valores desse CFOP ficam de fora do '
                    || 'cálculo até ser cadastrado em CFOP × PIS/COFINS.', 'rotina_1024')
        """), {"cid": competencia_id, "eid": empresa_id, "cfop": r["cfop"], "tipo": r["tipo_operacao"]})

    session.execute(text("update competencias set status = 'importada' where id = :cid"), {"cid": competencia_id})
    session.commit()

    partes = []
    if removidos:
        partes.append(f"{removidos} CFOPs antigos desta filial removidos (substituição).")
    partes.append(f"{len(linhas)} CFOPs importados da Rotina 1024.")
    if cfops_ruins:
        partes.append(f"{len(cfops_ruins)} CFOP(s) sem grupo cadastrado — ver Inconsistências.")
    return " ".join(partes)
