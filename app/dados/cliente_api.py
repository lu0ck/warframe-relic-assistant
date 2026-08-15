"""
Cliente da API do warframe.market — v2.

A v1 foi oficialmente desativada (os endpoints de itens retornam 404 e os de
ordens retornam 403 "Deprecated"), então este cliente usa a API nova:

- GET /v2/items                       -> data[] {id, slug, tags, i18n.en.name, ...}
- GET /v2/orders/item/{slug}          -> data[] de ordens {type, platinum, visible, ...}
- GET /v2/items/{slug}                -> data {slug, ducats, ...}  (ducats fixo por item)

O `slug` da v2 tem o mesmo formato do `url_name` da v1 (ex.: fang_prime_blade),
então reaproveitamos a coluna `url_name` do banco pra guardar o slug.

Nota: a v2 só devolve nomes em inglês (i18n.en). O matching assume que o jogo
está em inglês — quem joga em outro idioma precisa de uma camada de tradução
antes do fuzzy matching (fora do escopo atual).
"""
import asyncio
import time
from dataclasses import dataclass

import httpx

BASE_URL = "https://api.warframe.market/v2"
REQS_POR_SEGUNDO = 3
USER_AGENT = "warframe-relic-assistant/0.2 (Linux)"


@dataclass
class ItemMercado:
    slug: str
    nome: str
    preco_plata: float | None  # None se não encontrou nenhuma ordem de venda visível
    ducados: int | None        # None se ainda não foi buscado (item conhecido)


class CancelamentoAtualizacao(Exception):
    """Lançado internamente quando o usuário pede pra cancelar a atualização."""


class LimitadorDeTaxa:
    """Garante no máximo N requisições por segundo, mesmo com chamadas concorrentes."""

    def __init__(self, requisicoes_por_segundo: int):
        self._intervalo_minimo = 1.0 / requisicoes_por_segundo
        self._lock = asyncio.Lock()
        self._ultima_chamada = 0.0

    async def esperar_vez(self):
        async with self._lock:
            agora = time.monotonic()
            espera = self._ultima_chamada + self._intervalo_minimo - agora
            if espera > 0:
                await asyncio.sleep(espera)
            self._ultima_chamada = time.monotonic()


limitador = LimitadorDeTaxa(REQS_POR_SEGUNDO)


def _eh_item_prime(item: dict) -> bool:
    """Peça Prime comercializável (recompensa de relíquia). Exclui bundles 'set'."""
    tags = item.get("tags", [])
    return "prime" in tags and "set" not in tags


def _eh_item_mod(item: dict) -> bool:
    """Mod comercializável do jogo (tag 'mod' da API v2)."""
    tags = item.get("tags", [])
    return "mod" in tags


def _nome_do_item(item: dict) -> str:
    return item.get("i18n", {}).get("en", {}).get("name") or item.get("slug", "")


async def _obter_json(cliente: httpx.AsyncClient, url: str):
    await limitador.esperar_vez()
    resposta = await cliente.get(url)
    resposta.raise_for_status()
    return resposta.json()["data"]


async def listar_itens_prime(cliente: httpx.AsyncClient) -> list[dict]:
    """Busca a lista completa de itens e filtra só as peças Prime relevantes."""
    dados = await _obter_json(cliente, f"{BASE_URL}/items")
    return [item for item in dados if _eh_item_prime(item)]


async def listar_itens_mods(cliente: httpx.AsyncClient) -> list[dict]:
    """Busca a lista completa de itens e filtra só os mods."""
    dados = await _obter_json(cliente, f"{BASE_URL}/items")
    return [item for item in dados if _eh_item_mod(item)]


# Prioridade do status do vendedor: preferimos quem tá in-game agora,
# depois só online, e só por último offline (que costuma ter preço defasado,
# de anos atrás, que polui o cache).
_PRIORIDADE_STATUS = {"ingame": 0, "online": 1, "offline": 2}


async def buscar_menor_preco_venda(cliente: httpx.AsyncClient, slug: str) -> float | None:
    """Busca o menor preço de venda visível, priorizando vendedores ativos.

    Ordena por (status_prioridade, platinum) e pega o menor preço entre os
    vendedores mais ativos (ingame > online > offline). Sem vendedor visível,
    devolve None.
    """
    dados = await _obter_json(cliente, f"{BASE_URL}/orders/item/{slug}")
    ordens = [
        ordem for ordem in dados
        if ordem.get("type") == "sell" and ordem.get("visible", False)
        and isinstance(ordem.get("platinum"), (int, float))
    ]
    if not ordens:
        return None
    ordens.sort(key=lambda o: (
        _PRIORIDADE_STATUS.get((o.get("user") or {}).get("status", "offline"), 3),
        o["platinum"],
    ))
    return ordens[0]["platinum"]


async def buscar_ducados(cliente: httpx.AsyncClient, slug: str) -> int | None:
    """Busca o valor fixo em ducados do item (vem do detalhe do item na v2)."""
    dados = await _obter_json(cliente, f"{BASE_URL}/items/{slug}")
    return dados.get("ducats")


async def atualizar_todos_os_precos(
    callback_progresso=None,
    slugs_com_ducados: set[str] | None = None,
    deve_parar=None,
) -> list[ItemMercado]:
    """
    Rotina principal: busca todas as peças Prime e o menor preço de venda de
    cada uma. Para itens que ainda não têm ducados no cache local, busca
    também o valor de ducados (uma única vez — quando aparecerem peças novas).

    slugs_com_ducados: conjunto de slugs que JÁ têm ducados no banco; esses
    são pulados pra economizar requests (o ducado é fixo por item).
    callback_progresso(feito, total) é chamado a cada item, se fornecido.
    deve_parar: callable() opcional; quando devolve True, a atualização é
    interrompida (levanta CancelamentoAtualizacao) e o cache anterior fica
    intacto.
    """
    if slugs_com_ducados is None:
        slugs_com_ducados = set()

    resultado: list[ItemMercado] = []

    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": USER_AGENT}) as cliente:
        itens_prime = await listar_itens_prime(cliente)
        total = len(itens_prime)

        # Processa em sequência controlada pelo limitador (não usar gather sem
        # controle, senão estoura o limite de 3 req/s da API).
        for indice, item in enumerate(itens_prime):
            if deve_parar is not None and deve_parar():
                raise CancelamentoAtualizacao()
            slug = item["slug"]
            preco = await buscar_menor_preco_venda(cliente, slug)
            ducados = None
            if slug not in slugs_com_ducados:
                ducados = await buscar_ducados(cliente, slug)
            resultado.append(ItemMercado(
                slug=slug,
                nome=_nome_do_item(item),
                preco_plata=preco,
                ducados=ducados,
            ))
            if callback_progresso:
                callback_progresso(indice + 1, total)

    return resultado


async def atualizar_tudo(
    callback_progresso=None,
    slugs_com_ducados: set[str] | None = None,
    deve_parar=None,
) -> tuple[list[ItemMercado], list[ItemMercado]]:
    """Rotina diária completa: peças Prime E mods.

    Faz UMA única chamada de /items (filtra por tag) e processa Prime primeiro,
    depois Mods, emitindo progresso sobre o total conjunto (prime + mods). Mods
    não têm ducados — só o preço de venda é buscado.

    Devolve (itens_prime, itens_mods): dois lotes separados pra serem salvos
    nas tabelas próprias (itens_cache / mods_cache).
    """
    if slugs_com_ducados is None:
        slugs_com_ducados = set()

    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": USER_AGENT}) as cliente:
        dados = await _obter_json(cliente, f"{BASE_URL}/items")
        itens_prime = [item for item in dados if _eh_item_prime(item)]
        itens_mods = [item for item in dados if _eh_item_mod(item)]
        total = len(itens_prime) + len(itens_mods)
        feito = 0

        resultado_prime: list[ItemMercado] = []
        for item in itens_prime:
            if deve_parar is not None and deve_parar():
                raise CancelamentoAtualizacao()
            slug = item["slug"]
            preco = await buscar_menor_preco_venda(cliente, slug)
            ducados = None
            if slug not in slugs_com_ducados:
                ducados = await buscar_ducados(cliente, slug)
            resultado_prime.append(ItemMercado(
                slug=slug,
                nome=_nome_do_item(item),
                preco_plata=preco,
                ducados=ducados,
            ))
            feito += 1
            if callback_progresso:
                callback_progresso(feito, total)

        resultado_mods: list[ItemMercado] = []
        for item in itens_mods:
            if deve_parar is not None and deve_parar():
                raise CancelamentoAtualizacao()
            slug = item["slug"]
            preco = await buscar_menor_preco_venda(cliente, slug)
            resultado_mods.append(ItemMercado(
                slug=slug,
                nome=_nome_do_item(item),
                preco_plata=preco,
                ducados=None,
            ))
            feito += 1
            if callback_progresso:
                callback_progresso(feito, total)

    return resultado_prime, resultado_mods
