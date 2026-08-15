"""Modelo de dados do inventário de Mods (Fase Mods).

Uma `LinhaMod` é um mod (ex.: "Vitality") com a quantidade que o usuário tem
empilhada. O preço/slug é resolvido por fuzzy matching contra o cache local de
mods (mods_cache) — sem match confiável o mod fica "Sem preço" e conta como 0
no total (não inventamos preço pra itens sem página no warframe.market).
"""
from dataclasses import dataclass


@dataclass
class LinhaMod:
    nome: str
    quantidade: int = 1
    preco_plata: float | None = None
    slug: str | None = None

    @property
    def subtotal(self) -> float | None:
        if self.preco_plata is None:
            return None
        return self.preco_plata * self.quantidade


@dataclass
class ResumoMods:
    total_com_preco: float
    quantidade_sem_preco: int


@dataclass
class ResumoMod:
    """Um mod agrupado na visão resumida (todas as linhas dele somadas)."""

    nome: str
    quantidade: int
    preco_plata: float | None
    subtotal: float | None


def resumo_por_mod(linhas: list[LinhaMod]) -> list[ResumoMod]:
    """Agrupa as linhas por mod (mesmo slug/nome) e soma quantidade e valor.

    Usa a mesma identidade da deduplicação da varredura — o mesmo mod vindo de
    linhas diferentes (OCR repetido, rank 0 e rank max) junta numa entrada só.
    Ordena do mais valioso pro menos; mods sem preço ficam no fim.
    """
    agrupado: dict[str, ResumoMod] = {}
    for linha in linhas:
        chave = chave_de_dedup_mod(linha.nome, linha.slug)
        resumo = agrupado.get(chave)
        if resumo is None:
            resumo = ResumoMod(
                nome=linha.nome,
                quantidade=0,
                preco_plata=linha.preco_plata,
                subtotal=0.0 if linha.preco_plata is not None else None,
            )
            agrupado[chave] = resumo
        resumo.quantidade += linha.quantidade
        if linha.subtotal is not None:
            if resumo.preco_plata is None:
                resumo.preco_plata = linha.preco_plata
                resumo.subtotal = 0.0
            resumo.subtotal += linha.subtotal
    return sorted(
        agrupado.values(),
        key=lambda r: (r.subtotal is None, -(r.subtotal or 0.0)),
    )


def top_mods(linhas: list[LinhaMod], limite: int = 5) -> list[ResumoMod]:
    """Os `limite` mods mais valiosos do inventário (None = sem preço, fora)."""
    return [r for r in resumo_por_mod(linhas) if r.subtotal is not None][:limite]


def calcular_resumo_mods(linhas: list[LinhaMod]) -> ResumoMods:
    """Soma de platina dos mods com preço e quantos mods ainda não têm preço.

    Mods sem preço valem 0 no total e são contados à parte — o usuário vê de
    cara quantos faltam precificar sem o valor total ser poluído.
    """
    subtotais = [linha.subtotal for linha in linhas if linha.subtotal is not None]
    total = sum(subtotais) if subtotais else 0.0
    sem_preco = sum(1 for linha in linhas if linha.preco_plata is None)
    return ResumoMods(total_com_preco=total, quantidade_sem_preco=sem_preco)


def total_mods(linhas: list[LinhaMod]) -> float:
    """Total de platina do inventário (mods sem preço valem 0)."""
    return calcular_resumo_mods(linhas).total_com_preco


def chave_de_dedup_mod(nome: str, slug: str | None = None) -> str:
    """Identidade de um mod pra dedup na varredura.

    O slug (quando existe) é a identidade canônica — o mesmo mod lido de formas
    diferentes pelo OCR deduplica. Sem slug, usa o nome normalizado (sem
    espaços, minúsculas). O prefixo evita colisão entre as duas formas.
    """
    if slug:
        return f"slug:{slug}"
    return "nome:" + "".join(nome.split()).casefold()


def resolver_preco_mod(nome: str) -> LinhaMod:
    """Resolve preço/slug de um mod (do OCR ou digitado) no cache local de mods.

    Usa o mesmo fuzzy matching do overlay, restrito aos candidatos de mods
    (mods_cache) — mods têm nomes de 1 palavra (Vitality, Flow...), então o
    candidato certo precisa vir dessa lista, não do cache de peças Prime.
    """
    if not nome or not nome.strip():
        return LinhaMod(nome=nome.strip(), quantidade=1)
    from app.dados import cache as cache_dados
    from app.matching.comparador import encontrar_melhor_correspondencia

    candidatos = cache_dados.listar_mods_candidatos()
    resultado = encontrar_melhor_correspondencia(nome, candidatos=candidatos)
    return LinhaMod(
        nome=nome.strip(),
        quantidade=1,
        preco_plata=resultado.preco_plata,
        slug=resultado.slug,
    )
