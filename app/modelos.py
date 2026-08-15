"""Estruturas de dados usadas em várias camadas (matching, UI, histórico)."""
from dataclasses import dataclass


@dataclass
class OpcaoRecompensa:
    """Uma das 4 opções mostradas na tela de recompensa de relíquia."""
    nome: str
    preco_plata: float | None
    ducados: int | None
    e_melhor: bool = False
    slug: str | None = None


@dataclass
class ItemCache:
    """Uma linha do cache local (itens_cache)."""
    nome: str
    preco_plata: float | None
    ducados: int | None
    slug: str
