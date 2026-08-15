"""Grava e lê o histórico de sessões de abertura de relíquia."""
from datetime import datetime

from app.dados import cache
from app.dados.cache import conectar
from app.modelos import OpcaoRecompensa

# Janela de tempo (segundos) em que duas sessões com os MESMOS itens são
# consideradas a mesma abertura — evita poluir o histórico quando o gatilho
# automático (ou um hotkey rápido) dispara duas vezes pra mesma tela.
JANELA_DEDUPE_SEG = 60


def salvar_sessao(opcoes: list[OpcaoRecompensa], item_escolhido: str | None = None) -> int:
    """Grava uma abertura de relíquia e devolve o id da sessão criada.

    Se a sessão mais recente (nos últimos JANELA_DEDUPE_SEG segundos) tiver
    exatamente os mesmos itens, NÃO cria outra linha — devolve o id da que já
    existe. Isso elimina os registros duplicados da mesma abertura.
    """
    melhor = next((o.nome for o in opcoes if o.e_melhor), None)
    agora_dt = datetime.now()
    conjunto_nomes = {o.nome for o in opcoes}

    with conectar() as conexao:
        ultima = conexao.execute(
            "SELECT id, data_hora FROM historico_relicas ORDER BY data_hora DESC LIMIT 1"
        ).fetchone()
        if ultima is not None:
            try:
                anterior_dt = datetime.fromisoformat(ultima["data_hora"])
            except (TypeError, ValueError):
                anterior_dt = None
            if anterior_dt is not None and (agora_dt - anterior_dt).total_seconds() < JANELA_DEDUPE_SEG:
                itens_anteriores = {
                    linha["nome"]
                    for linha in conexao.execute(
                        "SELECT nome FROM historico_itens WHERE relica_id = ?",
                        (ultima["id"],),
                    )
                }
                if itens_anteriores == conjunto_nomes:
                    return ultima["id"]

        agora = agora_dt.isoformat()
        cursor = conexao.execute(
            """INSERT INTO historico_relicas (data_hora, melhor_item_nome, item_escolhido_nome)
               VALUES (?, ?, ?)""",
            (agora, melhor, item_escolhido),
        )
        relica_id = cursor.lastrowid
        conexao.executemany(
            """INSERT INTO historico_itens
               (relica_id, posicao, nome, preco_plata, ducados, e_melhor, foi_escolhido, slug)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    relica_id, i + 1, o.nome, o.preco_plata, o.ducados,
                    int(o.e_melhor), int(o.nome == item_escolhido), o.slug,
                )
                for i, o in enumerate(opcoes)
            ],
        )
        conexao.commit()
    # O item escolhido na abertura também vai pro inventário geral: uma
    # abertura = uma peça ganha (mesmo que seja a mesma tela recapturada, o
    # dedup acima já devolve sem somar de novo).
    if item_escolhido:
        for o in opcoes:
            if o.nome == item_escolhido:
                cache.adicionar_ao_inventario(o.nome, o.preco_plata, o.slug, o.ducados)
                break
    return relica_id


def criar_sessao() -> int:
    """Cria uma sessão vazia no histórico (sem itens) com a data/hora atual.

    Usado pelo botão "Criar sessão" da aba Histórico, pra quando o usuário quer
    registrar uma abertura que o OCR não captou. Devolve o id da sessão criada —
    os itens entram depois via `adicionar_item`.
    """
    agora = datetime.now().isoformat()
    with conectar() as conexao:
        cursor = conexao.execute(
            "INSERT INTO historico_relicas (data_hora, melhor_item_nome, item_escolhido_nome)"
            " VALUES (?, NULL, NULL)",
            (agora,),
        )
        conexao.commit()
        return cursor.lastrowid


def listar_historico_completo() -> list[dict]:
    """Retorna todas as sessões, mais recente primeiro, cada uma com seus itens."""
    with conectar() as conexao:
        sessoes = conexao.execute(
            "SELECT * FROM historico_relicas ORDER BY data_hora DESC"
        ).fetchall()

        resultado = []
        for sessao in sessoes:
            itens = conexao.execute(
                "SELECT * FROM historico_itens WHERE relica_id = ? ORDER BY posicao",
                (sessao["id"],),
            ).fetchall()
            resultado.append({
                "id": sessao["id"],
                "data_hora": sessao["data_hora"],
                "melhor_item_nome": sessao["melhor_item_nome"],
                "item_escolhido_nome": sessao["item_escolhido_nome"],
                "itens": [dict(item) for item in itens],
            })
        return resultado


def agrupar_por_dia(sessoes: list[dict]) -> dict[str, list[dict]]:
    """Agrupa as sessões por data (AAAA-MM-DD), mantendo a ordem mais recente primeiro."""
    grupos: dict[str, list[dict]] = {}
    for sessao in sessoes:
        dia = sessao["data_hora"][:10]
        grupos.setdefault(dia, []).append(sessao)
    return grupos


def editar_item(item_id: int, novo_nome: str) -> None:
    """Renomeia um item do histórico e atualiza preço/ducados/slug automaticamente.

    O novo nome é resolvido contra o cache de preços (fuzzy matching) — assim,
    quando o usuário corrige um nome que o OCR leu errado, o preço e o slug
    ficam certos também (pra o overlay/histórico mostrar o valor certo e pra
    permitir a venda direto do histórico).
    """
    novo_nome = novo_nome.strip()
    if not novo_nome:
        return

    # Resolve o novo nome contra o cache pra atualizar preço/ducados/slug.
    from app.matching.comparador import encontrar_melhor_correspondencia

    recon = encontrar_melhor_correspondencia(novo_nome)
    nome_final = recon.nome_encontrado or novo_nome
    preco = recon.preco_plata
    ducados = recon.ducados
    slug = recon.slug

    with conectar() as conexao:
        conexao.execute(
            """UPDATE historico_itens
               SET nome = ?, preco_plata = ?, ducados = ?, slug = ?
               WHERE id = ?""",
            (nome_final, preco, ducados, slug, item_id),
        )

        # Recalcula o "melhor" da sessão inteira (o item editado pode ter
        # mudado de preço e ultrapassado o outrora melhor — ou vice-versa).
        linha = conexao.execute(
            "SELECT relica_id FROM historico_itens WHERE id = ?", (item_id,)
        ).fetchone()
        if linha is not None:
            _recalcular_melhor(conexao, linha["relica_id"])

        conexao.commit()


def apagar_item(item_id: int) -> None:
    """Remove um item do histórico (a sessão continua com os demais)."""
    with conectar() as conexao:
        linha = conexao.execute(
            "SELECT relica_id FROM historico_itens WHERE id = ?", (item_id,)
        ).fetchone()
        conexao.execute("DELETE FROM historico_itens WHERE id = ?", (item_id,))
        # Recalcula o "melhor" da sessão: o item apagado pode ter sido o ★.
        if linha is not None:
            _recalcular_melhor(conexao, linha["relica_id"])
        conexao.commit()


def adicionar_item(relica_id: int, texto: str) -> dict | None:
    """Adiciona um item a uma sessão existente do histórico.

    O texto é resolvido contra o cache de preços (fuzzy matching) — da mesma
    forma que `editar_item` faz — pra preço/ducados/slug ficarem certos. O
    "e_melhor" da sessão inteira é recalculado depois (o novo item pode ser
    mais caro que o outrora melhor). O item adicionado NÃO fica marcado como
    "foi_escolhido" — o usuário marca isso depois, se quiser.

    Devolve o dicionário do item criado (com id, nome, preco_plata, ducados,
    slug, e_melhor, foi_escolhido) ou None se o texto for vazio.
    """
    texto = texto.strip()
    if not texto:
        return None

    from app.matching.comparador import encontrar_melhor_correspondencia

    recon = encontrar_melhor_correspondencia(texto)
    nome_final = recon.nome_encontrado or texto
    preco = recon.preco_plata
    ducados = recon.ducados
    slug = recon.slug

    with conectar() as conexao:
        # Pega a próxima posição livre na sessão.
        linha_pos = conexao.execute(
            "SELECT COALESCE(MAX(posicao), 0) + 1 AS prox FROM historico_itens WHERE relica_id = ?",
            (relica_id,),
        ).fetchone()
        prox_pos = linha_pos["prox"]

        cursor = conexao.execute(
            """INSERT INTO historico_itens
               (relica_id, posicao, nome, preco_plata, ducados, e_melhor, foi_escolhido, slug)
               VALUES (?, ?, ?, ?, ?, 0, 0, ?)""",
            (relica_id, prox_pos, nome_final, preco, ducados, slug),
        )
        novo_id = cursor.lastrowid

        _recalcular_melhor(conexao, relica_id)
        conexao.commit()

        # Recarrega o item novo do banco (e_melhor foi decidido em
        # _recalcular_melhor depois do insert, então o dict retornado reflete
        # o estado real — quem chamou pode usar pra feedback pro usuário).
        linha = conexao.execute(
            "SELECT * FROM historico_itens WHERE id = ?", (novo_id,)
        ).fetchone()
        return dict(linha) if linha is not None else None


def _recalcular_melhor(conexao, relica_id: int) -> None:
    """Recalcula a coluna e_melhor de todos os itens da sessão e atualiza
    historico_relicas.melhor_item_nome. Operação interna — quem chama abre o
    `with conectar()` e chama commit() depois.
    """
    itens = conexao.execute(
        "SELECT id, nome, preco_plata FROM historico_itens WHERE relica_id = ?",
        (relica_id,),
    ).fetchall()
    melhor_nome = None
    melhor_preco = None
    for it in itens:
        if it["preco_plata"] is not None:
            if melhor_preco is None or it["preco_plata"] > melhor_preco:
                melhor_preco = it["preco_plata"]
                melhor_nome = it["nome"]
    for it in itens:
        conexao.execute(
            "UPDATE historico_itens SET e_melhor = ? WHERE id = ?",
            (int(it["nome"] == melhor_nome) if melhor_nome else 0, it["id"]),
        )
    conexao.execute(
        "UPDATE historico_relicas SET melhor_item_nome = ? WHERE id = ?",
        (melhor_nome, relica_id),
    )


def definir_item_escolhido(relica_id: int, item_id: int | None) -> None:
    """Marca qual item da sessão o usuário realmente escolheu no jogo.

    SÓ UM item por sessão pode ser o escolhido — passar item_id=None remove a
    marca de todos. Atualiza historico_relicas.item_escolhido_nome também.

    Quando um item vira o escolhido (marcação nova, não repetição da atual),
    ele também entra no inventário geral com +1 — o ✓ representa a peça que o
    usuário pegou. Desmarcar não remove do inventário.
    """
    item_escolhido = None
    marcacao_nova = False
    with conectar() as conexao:
        anterior = conexao.execute(
            "SELECT id FROM historico_itens WHERE relica_id = ? AND foi_escolhido = 1",
            (relica_id,),
        ).fetchone()
        itens = conexao.execute(
            "SELECT id, nome, preco_plata, slug, ducados FROM historico_itens WHERE relica_id = ?",
            (relica_id,),
        ).fetchall()
        escolhido_nome = None
        for it in itens:
            marcado = 1 if (item_id is not None and it["id"] == item_id) else 0
            if marcado:
                escolhido_nome = it["nome"]
                item_escolhido = it
                marcacao_nova = anterior is None or anterior["id"] != item_id
            conexao.execute(
                "UPDATE historico_itens SET foi_escolhido = ? WHERE id = ?",
                (marcado, it["id"]),
            )
        conexao.execute(
            "UPDATE historico_relicas SET item_escolhido_nome = ? WHERE id = ?",
            (escolhido_nome, relica_id),
        )
        conexao.commit()
    if marcacao_nova and item_escolhido is not None:
        cache.adicionar_ao_inventario(
            item_escolhido["nome"],
            item_escolhido["preco_plata"],
            item_escolhido["slug"],
            item_escolhido["ducados"],
        )


def apagar_sessao(relica_id: int) -> None:
    """Remove uma sessão inteira do histórico (e os itens dela)."""
    with conectar() as conexao:
        conexao.execute("DELETE FROM historico_itens WHERE relica_id = ?", (relica_id,))
        conexao.execute("DELETE FROM historico_relicas WHERE id = ?", (relica_id,))
        conexao.commit()
