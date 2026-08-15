"""
Cache local (SQLite) dos preços de platina e ducados.

O valor em ducados vem fixo da API do warframe.market (campo `ducats` do item),
é o mesmo valor que aparece no jogo pela raridade do slot, e não muda entre
execuções — por isso é baixado uma única vez por item e reaproveitado depois.
"""
import sqlite3
from datetime import date, datetime

from app.config import CAMINHO_BANCO
from app.modelos import ItemCache


def conectar() -> sqlite3.Connection:
    conexao = sqlite3.connect(CAMINHO_BANCO)
    conexao.row_factory = sqlite3.Row
    return conexao


def criar_tabelas():
    with conectar() as conexao:
        conexao.executescript("""
            CREATE TABLE IF NOT EXISTS itens_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url_name TEXT NOT NULL UNIQUE,
                nome TEXT NOT NULL,
                preco_plata REAL,
                ducados INTEGER,
                data_atualizacao TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS historico_relicas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_hora TEXT NOT NULL,
                melhor_item_nome TEXT,
                item_escolhido_nome TEXT
            );

            CREATE TABLE IF NOT EXISTS historico_itens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                relica_id INTEGER NOT NULL REFERENCES historico_relicas(id),
                posicao INTEGER,
                nome TEXT,
                preco_plata REAL,
                ducados INTEGER,
                e_melhor INTEGER,
                foi_escolhido INTEGER
            );

            CREATE TABLE IF NOT EXISTS config (
                chave TEXT PRIMARY KEY,
                valor TEXT
            );

            CREATE TABLE IF NOT EXISTS inventario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                quantidade INTEGER NOT NULL DEFAULT 1,
                preco_plata REAL,
                slug TEXT,
                ducados INTEGER,
                data_hora TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mods_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url_name TEXT NOT NULL UNIQUE,
                nome TEXT NOT NULL,
                preco_plata REAL,
                data_atualizacao TEXT NOT NULL
            );
        """)

        # Migração: bancos criados antes da coluna `ducados` recebem ela agora.
        colunas = {
            linha["name"]
            for linha in conexao.execute("PRAGMA table_info(itens_cache)").fetchall()
        }
        if "ducados" not in colunas:
            conexao.execute("ALTER TABLE itens_cache ADD COLUMN ducados INTEGER")

        # Migração: histórico ganhou a coluna `slug` (pra permitir "vender" um
        # item direto do histórico).
        colunas_hist = {
            linha["name"]
            for linha in conexao.execute("PRAGMA table_info(historico_itens)").fetchall()
        }
        if "slug" not in colunas_hist:
            conexao.execute("ALTER TABLE historico_itens ADD COLUMN slug TEXT")

        # Migração: inventário ganhou a coluna `ducados` (F6).
        colunas_inv = {
            linha["name"]
            for linha in conexao.execute("PRAGMA table_info(inventario)").fetchall()
        }
        if "ducados" not in colunas_inv:
            conexao.execute("ALTER TABLE inventario ADD COLUMN ducados INTEGER")


def salvar_itens(itens: list) -> int:
    """Recebe uma lista de ItemMercado (de cliente_api.py) e substitui o cache inteiro.

    Itens que vieram sem ducados (porque já existiam no banco e foram pulados
    na atualização) preservam o valor antigo — o ducado é fixo por item.
    """
    agora = datetime.now().isoformat()
    with conectar() as conexao:
        existentes = {
            linha["url_name"]: linha["ducados"]
            for linha in conexao.execute(
                "SELECT url_name, ducados FROM itens_cache"
            ).fetchall()
        }
        conexao.execute("DELETE FROM itens_cache")
        linhas = []
        for item in itens:
            ducados = item.ducados
            if ducados is None and item.slug in existentes:
                ducados = existentes[item.slug]
            linhas.append((item.slug, item.nome, item.preco_plata, ducados, agora))
        conexao.executemany(
            """INSERT INTO itens_cache (url_name, nome, preco_plata, ducados, data_atualizacao)
               VALUES (?, ?, ?, ?, ?)""",
            linhas,
        )
        conexao.commit()
    return len(itens)


def data_da_ultima_atualizacao() -> date | None:
    with conectar() as conexao:
        linha = conexao.execute(
            "SELECT data_atualizacao FROM itens_cache ORDER BY data_atualizacao DESC LIMIT 1"
        ).fetchone()
    if linha is None:
        return None
    return datetime.fromisoformat(linha["data_atualizacao"]).date()


def precisa_atualizar_hoje() -> bool:
    ultima = data_da_ultima_atualizacao()
    return ultima is None or ultima < date.today()


def todos_os_nomes_e_precos() -> list[ItemCache]:
    """Usado pelo módulo de matching (Fase 2) pra comparar contra o texto do OCR."""
    with conectar() as conexao:
        linhas = conexao.execute(
            "SELECT url_name, nome, preco_plata, ducados FROM itens_cache"
        ).fetchall()
    return [
        ItemCache(
            nome=linha["nome"],
            preco_plata=linha["preco_plata"],
            ducados=linha["ducados"],
            slug=linha["url_name"],
        )
        for linha in linhas
    ]


def obter_config(chave: str, padrao: str | None = None) -> str | None:
    """Lê um valor da tabela `config` (configurações do usuário)."""
    with conectar() as conexao:
        linha = conexao.execute(
            "SELECT valor FROM config WHERE chave = ?", (chave,)
        ).fetchone()
    return linha["valor"] if linha else padrao


def salvar_config(chave: str, valor: str):
    """Grava um valor na tabela `config` (cria ou sobrescreve)."""
    with conectar() as conexao:
        conexao.execute(
            """INSERT INTO config (chave, valor) VALUES (?, ?)
               ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor""",
            (chave, valor),
        )
        conexao.commit()


def _nome_normalizado(nome: str) -> str:
    """Identidade de nome usada no dedup (mesma regra do chave_de_dedup)."""
    return "".join(nome.split()).casefold()


def _encontrar_no_inventario(conexao, slug: str | None, nome: str | None):
    """Localiza no inventário o item igual a (slug, nome), na mesma
    precedência do merge: slug → nome exato → nome normalizado.

    Devolve a linha (id, nome, preco_plata, slug, ducados) ou None.
    """
    alvo = None
    if slug:
        alvo = conexao.execute(
            "SELECT id, nome, preco_plata, slug, ducados FROM inventario WHERE slug = ?",
            (slug,),
        ).fetchone()
    if alvo is None and nome:
        alvo = conexao.execute(
            "SELECT id, nome, preco_plata, slug, ducados FROM inventario WHERE nome = ?",
            (nome,),
        ).fetchone()
    if alvo is None and nome:
        norm = _nome_normalizado(nome)
        todos = conexao.execute(
            "SELECT id, nome, preco_plata, slug, ducados FROM inventario"
        ).fetchall()
        alvo = next((l for l in todos if _nome_normalizado(l["nome"]) == norm), None)
    return alvo


def reconciliar_escolhidos() -> int:
    """Adiciona ao inventário geral todo item marcado ✓ no histórico que ainda
    não está lá (peças ganhas em sessões gravadas por versões antigas do app).

    Devolve quantos itens foram adicionados. A verificação usa a mesma
    precedência do merge (slug → nome exato → nome normalizado), então nada é
    somado em dobro.
    """
    with conectar() as conexao:
        escolhidos = conexao.execute(
            """SELECT nome, preco_plata, ducados, slug
               FROM historico_itens
               WHERE foi_escolhido = 1"""
        ).fetchall()
    adicionados = 0
    for item in escolhidos:
        with conectar() as conexao:
            alvo = _encontrar_no_inventario(conexao, item["slug"], item["nome"])
        if alvo is None:
            adicionar_ao_inventario(
                item["nome"],
                item["preco_plata"],
                item["slug"],
                item["ducados"],
            )
            adicionados += 1
    return adicionados


def adicionar_ao_inventario(
    nome: str,
    preco_plata: float | None = None,
    slug: str | None = None,
    ducados: int | None = None,
    quantidade: int = 1,
) -> None:
    """Adiciona `quantidade` unidades ao inventário geral (merge).

    Se já existe um item igual (mesmo slug; senão nome exato; senão nome
    normalizado), só soma a quantidade. Linha existente com dados faltando
    (slug/preço/ducados NULL) é preenchida com os valores novos.
    """
    if not nome or not nome.strip():
        return
    agora = datetime.now().isoformat()
    nome = nome.strip()
    with conectar() as conexao:
        alvo = _encontrar_no_inventario(conexao, slug, nome)
        if alvo is not None:
            novos_slug = slug if alvo["slug"] is None else alvo["slug"]
            novos_preco = preco_plata if alvo["preco_plata"] is None else alvo["preco_plata"]
            novos_ducados = ducados if alvo["ducados"] is None else alvo["ducados"]
            conexao.execute(
                "UPDATE inventario SET quantidade = quantidade + ?, "
                "preco_plata = ?, slug = ?, ducados = ?, data_hora = ? WHERE id = ?",
                (quantidade, novos_preco, novos_slug, novos_ducados, agora, alvo["id"]),
            )
        else:
            conexao.execute(
                """INSERT INTO inventario
                   (nome, quantidade, preco_plata, slug, ducados, data_hora)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (nome, quantidade, preco_plata, slug, ducados, agora),
            )
        conexao.commit()


def salvar_inventario(linhas: list) -> int:
    """Mescla as linhas atuais no inventário geral (inventário acumulativo).

    Recebe uma lista de LinhaInventario (app/dados/inventario.py). Cada linha
    soma a quantidade com o item igual que já existir (mesmo slug ou nome);
    itens novos entram como novas linhas. Nada é apagado — os ✓ marcados no
    histórico e itens de varreduras anteriores continuam no inventário.
    """
    for linha in linhas:
        adicionar_ao_inventario(
            linha.nome,
            linha.preco_plata,
            linha.slug,
            linha.ducados,
            linha.quantidade,
        )
    return len(linhas)


def obter_inventario_salvo() -> list[dict]:
    """Devolve as linhas salvas do inventário (na ordem de salvamento).

    Cada item tem as chaves: nome, quantidade, preco_plata, slug, ducados,
    data_hora.
    """
    with conectar() as conexao:
        linhas = conexao.execute(
            "SELECT nome, quantidade, preco_plata, slug, ducados, data_hora "
            "FROM inventario ORDER BY id"
        ).fetchall()
    return [dict(linha) for linha in linhas]


def obter_info_inventario_salvo() -> tuple[int, str] | None:
    """(quantidade de itens, data_hora do último salvo) ou None se vazio."""
    with conectar() as conexao:
        linha = conexao.execute(
            "SELECT COUNT(*) AS total, MAX(data_hora) AS ultima FROM inventario"
        ).fetchone()
    if linha["total"] == 0:
        return None
    return (linha["total"], linha["ultima"])


# ---------------------------------------------------------------------------
# Cache de preços de Mods (Fase Mods) — tabela própria, sem ducados.
# ---------------------------------------------------------------------------

def salvar_mods(itens: list) -> int:
    """Recebe os preços de mods (de cliente_api.py) e substitui o cache inteiro."""
    agora = datetime.now().isoformat()
    with conectar() as conexao:
        conexao.execute("DELETE FROM mods_cache")
        linhas = [(item.slug, item.nome, item.preco_plata, agora) for item in itens]
        conexao.executemany(
            """INSERT INTO mods_cache (url_name, nome, preco_plata, data_atualizacao)
               VALUES (?, ?, ?, ?)""",
            linhas,
        )
        conexao.commit()
    return len(itens)


def precisa_atualizar_mods_hoje() -> bool:
    """Mods também precisam de atualização diária (data marcada na config).

    Separado do cache de peças Prime porque os dois são baixados em rotinas
    independentes na mesma abertura do app.
    """
    valor = obter_config("ultima_atualizacao_mods")
    if not valor:
        return True
    try:
        return date.fromisoformat(valor) < date.today()
    except (TypeError, ValueError):
        return True


def listar_mods_candidatos() -> list[ItemCache]:
    """Candidatos de matching pro OCR de mods (app/matching/comparador.py).

    Reusa ItemCache (ducados sempre None — mod não tem valor em ducados).
    """
    with conectar() as conexao:
        linhas = conexao.execute(
            "SELECT url_name, nome, preco_plata FROM mods_cache"
        ).fetchall()
    return [
        ItemCache(
            nome=linha["nome"],
            preco_plata=linha["preco_plata"],
            ducados=None,
            slug=linha["url_name"],
        )
        for linha in linhas
    ]


def obter_slugs_com_ducados() -> set[str]:
    """Slugs dos itens que já têm valor de ducados no cache.

    O ducado é fixo por item, então na atualização diária só buscamos de novo
    itens que ainda não têm esse valor salvo (peças novas).
    """
    with conectar() as conexao:
        linhas = conexao.execute(
            "SELECT url_name FROM itens_cache WHERE ducados IS NOT NULL"
        ).fetchall()
    return {linha["url_name"] for linha in linhas}


def contar_itens_no_cache() -> int:
    with conectar() as conexao:
        return conexao.execute("SELECT COUNT(*) AS total FROM itens_cache").fetchone()["total"]


def contar_mods_no_cache() -> int:
    with conectar() as conexao:
        return conexao.execute("SELECT COUNT(*) AS total FROM mods_cache").fetchone()["total"]


def buscar_slug_por_nome(nome: str) -> str | None:
    """Resolve o slug de um item pelo nome (match EXATO apenas).

    Usado pelo histórico pra permitir "vender" itens que foram salvos antes da
    coluna slug existir (slug NULL). Nomes reconhecidos vêm do próprio banco,
    então o match exato basta — fuzzy aqui é perigoso (pode publicar venda do
    item errado).
    """
    if not nome or nome.startswith("(não reconhecido"):
        return None
    with conectar() as conexao:
        linha = conexao.execute(
            "SELECT url_name FROM itens_cache WHERE nome = ? LIMIT 1", (nome,)
        ).fetchone()
    if linha is not None:
        return linha["url_name"]
    return None


def listar_itens(
    *,
    ordenar_por: str = "preco_plata",
    decrescente: bool = True,
    limite: int = 100,
    offset: int = 0,
    filtro_nome: str | None = None,
    preco_min: float | None = None,
    preco_max: float | None = None,
    somente_com_preco: bool = False,
) -> tuple[list[ItemCache], int]:
    """Lista itens do cache com ordenação, filtros e paginação.

    Parâmetros:
      ordenar_por: "nome" | "preco_plata" | "ducados"
      decrescente: True = do maior pro menor; False = crescente
      limite/offset: paginação
      filtro_nome: substring (case-insensitive) que deve aparecer no nome
      preco_min / preco_max: faixa de preço em platina (inclusive)
      somente_com_preco: excluir itens sem preço salvo

    Devolve (itens, total) — onde `total` é o número total de itens que
    casam com os mesmos filtros (sem LIMIT/OFFSET), útil pra paginação na
    UI. Os `itens` são uma lista de ItemCache preenchido.

    Itens sem preço ficam no final quando ordem é por preço decrescente
    (NULLs últimos) — visualmente mais natural: "top do banco" primeiro.
    """
    colunas_validas = {"nome", "preco_plata", "ducados"}
    if ordenar_por not in colunas_validas:
        ordenar_por = "preco_plata"

    where_clauses = []
    params: list = []

    if filtro_nome:
        where_clauses.append("nome LIKE ?")
        params.append(f"%{filtro_nome}%")
    if preco_min is not None:
        where_clauses.append("preco_plata >= ?")
        params.append(preco_min)
    if preco_max is not None:
        where_clauses.append("preco_plata <= ?")
        params.append(preco_max)
    if somente_com_preco:
        where_clauses.append("preco_plata IS NOT NULL")

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Ordenação NULL-safe: quando é por preço, NULL vão pro fim (independente
    # do ASC/DESC — não queremos "sem preço" aparecendo no topo das listas).
    if ordenar_por == "preco_plata":
        ordem_sql = (
            " ORDER BY "
            f"CASE WHEN preco_plata IS NULL THEN 1 ELSE 0 END, "
            f"preco_plata {'DESC' if decrescente else 'ASC'}"
        )
    else:
        ordem_sql = f" ORDER BY {ordenar_por} {'DESC' if decrescente else 'ASC'}"

    with conectar() as conexao:
        total = conexao.execute(
            f"SELECT COUNT(*) AS t FROM itens_cache{where_sql}", params
        ).fetchone()["t"]

        rows = conexao.execute(
            f"SELECT url_name, nome, preco_plata, ducados FROM itens_cache"
            f"{where_sql}{ordem_sql} LIMIT ? OFFSET ?",
            params + [limite, offset],
        ).fetchall()

    itens = [
        ItemCache(
            nome=r["nome"],
            preco_plata=r["preco_plata"],
            ducados=r["ducados"],
            slug=r["url_name"],
        )
        for r in rows
    ]
    return itens, total


def listar_mods(
    *,
    ordenar_por: str = "preco_plata",
    decrescente: bool = True,
    limite: int = 100,
    offset: int = 0,
    filtro_nome: str | None = None,
    preco_min: float | None = None,
    preco_max: float | None = None,
    somente_com_preco: bool = False,
) -> tuple[list[ItemCache], int]:
    """Lista mods do cache com ordenação, filtros e paginação.

    Mesmo contrato de `listar_itens` (peças Prime), só que sobre a tabela
    `mods_cache` — mod não tem ducados, então a ordenação é por nome ou preço.
    Devolve (itens, total), onde `total` é o número de mods que casam com os
    mesmos filtros (sem LIMIT/OFFSET). Mods sem preço vão pro fim quando a
    ordem é por preço (NULLs últimos).
    """
    colunas_validas = {"nome", "preco_plata"}
    if ordenar_por not in colunas_validas:
        ordenar_por = "preco_plata"

    where_clauses = []
    params: list = []

    if filtro_nome:
        where_clauses.append("nome LIKE ?")
        params.append(f"%{filtro_nome}%")
    if preco_min is not None:
        where_clauses.append("preco_plata >= ?")
        params.append(preco_min)
    if preco_max is not None:
        where_clauses.append("preco_plata <= ?")
        params.append(preco_max)
    if somente_com_preco:
        where_clauses.append("preco_plata IS NOT NULL")

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    if ordenar_por == "preco_plata":
        ordem_sql = (
            " ORDER BY "
            f"CASE WHEN preco_plata IS NULL THEN 1 ELSE 0 END, "
            f"preco_plata {'DESC' if decrescente else 'ASC'}"
        )
    else:
        ordem_sql = f" ORDER BY {ordenar_por} {'DESC' if decrescente else 'ASC'}"

    with conectar() as conexao:
        total = conexao.execute(
            f"SELECT COUNT(*) AS t FROM mods_cache{where_sql}", params
        ).fetchone()["t"]

        rows = conexao.execute(
            f"SELECT url_name, nome, preco_plata FROM mods_cache"
            f"{where_sql}{ordem_sql} LIMIT ? OFFSET ?",
            params + [limite, offset],
        ).fetchall()

    mods = [
        ItemCache(
            nome=r["nome"],
            preco_plata=r["preco_plata"],
            ducados=None,
            slug=r["url_name"],
        )
        for r in rows
    ]
    return mods, total
