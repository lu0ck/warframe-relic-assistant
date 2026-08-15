"""
Modelo de dados do inventário varrido na tela "Inventory/Sell".

Uma `LinhaInventario` é uma peça (ex.: "Soma Prime Receiver") com quantidade.
Sem selo azul de quantidade a peça vale 1; com selo, o número lido. O nome
chega como saiu do OCR e o preço/slug é resolvido por fuzzy matching contra o
cache local (app/matching/comparador.py).

O agrupamento por conjunto usa a parte do nome até (incluindo) "Prime" — a
tela de inventário só tem itens Prime, então "Soma Prime Receiver" e
"Soma Prime Barrel" pertencem ao mesmo conjunto "Soma Prime".
"""
import re
from dataclasses import dataclass

# Conjunto = tudo até+incluindo "Prime" (case-insensitive). Nomes sem "Prime"
# (ex.: "Forma Blueprint") ficam no próprio nome, como conjunto isolado.
PADRAO_PRIME = re.compile(r"\bPrime\b", re.IGNORECASE)


def nome_do_conjunto(nome: str) -> str:
    """Devolve o conjunto de um item: tudo até+incluindo 'Prime'."""
    if not nome:
        return nome
    marcador = PADRAO_PRIME.search(nome)
    if marcador:
        return nome[: marcador.end()]
    return nome.strip()


@dataclass
class LinhaInventario:
    nome: str
    quantidade: int = 1
    preco_plata: float | None = None
    slug: str | None = None
    ducados: int | None = None

    @property
    def conjunto(self) -> str:
        return nome_do_conjunto(self.nome)

    @property
    def subtotal(self) -> float | None:
        if self.preco_plata is None:
            return None
        return self.preco_plata * self.quantidade

    @property
    def total_ducados(self) -> int | None:
        if self.ducados is None:
            return None
        return self.ducados * self.quantidade


@dataclass
class ResumoConjunto:
    conjunto: str
    quantidade: int
    subtotal: float | None
    total_ducados: int | None


def calcular_resumo(linhas: list[LinhaInventario]) -> list[ResumoConjunto]:
    """Subtotais (platina + ducados) por conjunto, na ordem de primeiro aparecimento."""
    por_conjunto: dict[str, list[LinhaInventario]] = {}
    for linha in linhas:
        por_conjunto.setdefault(linha.conjunto, []).append(linha)
    resumo = []
    for conjunto, itens in por_conjunto.items():
        quantidade = sum(item.quantidade for item in itens)
        subtotais = [item.subtotal for item in itens if item.subtotal is not None]
        subtotal = sum(subtotais) if subtotais else None
        ducados = [item.total_ducados for item in itens if item.total_ducados is not None]
        total_ducados = sum(ducados) if ducados else None
        resumo.append(
            ResumoConjunto(
                conjunto=conjunto,
                quantidade=quantidade,
                subtotal=subtotal,
                total_ducados=total_ducados,
            )
        )
    return resumo


def total_geral(linhas: list[LinhaInventario]) -> float | None:
    """Total de todos os subtotais; None se nenhuma linha tiver preço."""
    subtotais = [item.subtotal for item in linhas if item.subtotal is not None]
    return sum(subtotais) if subtotais else None


def total_geral_ducados(linhas: list[LinhaInventario]) -> int | None:
    """Total de ducados de todas as linhas; None se nenhuma tiver ducados."""
    ducados = [item.total_ducados for item in linhas if item.total_ducados is not None]
    return sum(ducados) if ducados else None


def resolver_preco(nome: str) -> LinhaInventario:
    """Resolve preço/slug/ducados de um nome (que pode ter saído do OCR) no cache.

    Usa o mesmo fuzzy matching do overlay; sem match confiável, o item fica
    sem preço (a UI mostra '—' e o subtotal fica em aberto, pros itens sem
    página no mercado ou ainda não lidos).
    """
    if not nome or not nome.strip():
        return LinhaInventario(nome=nome.strip(), quantidade=1)
    from app.matching.comparador import encontrar_melhor_correspondencia

    resultado = encontrar_melhor_correspondencia(nome)
    return LinhaInventario(
        nome=nome.strip(),
        quantidade=1,
        preco_plata=resultado.preco_plata,
        slug=resultado.slug,
        ducados=resultado.ducados,
    )


def chave_de_dedup(nome: str, slug: str | None = None) -> str:
    """Identidade de um item pra dedup na varredura.

    O slug (quando existe) é a identidade canônica — o mesmo item lido de
    formas diferentes pelo OCR deduplica. Sem slug (item sem match no banco),
    usa o nome normalizado (sem espaços, minúsculas), igual ao fuzzy do
    matching. O prefixo evita colisão entre as duas formas.
    """
    if slug:
        return f"slug:{slug}"
    return "nome:" + "".join(nome.split()).casefold()
