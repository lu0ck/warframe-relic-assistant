"""
Compara o texto (imperfeito) que saiu do OCR contra os nomes conhecidos no
cache local, usando fuzzy matching — corrige a maioria dos erros de leitura
do Tesseract sem precisar de reconhecimento de imagem mais pesado.
"""
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from app.dados.cache import todos_os_nomes_e_precos

# Abaixo disso, o match é considerado não-confiável (melhor avisar o usuário
# do que mostrar um preço errado)
LIMIAR_CONFIANCA = 62

# Itens que aparecem na recompensa de relíquia mas NÃO existem no
# warframe.market (não têm página de ordens). Se o OCR ler o nome exato,
# reconhecemos como item conhecido SEM preço/ducados em vez de o fuzzy matching
# inventar um Prime parecido (ex: "Forma Blueprint" virando "Zephyr Prime
# Chassis Blueprint" a 86% e mostrando preço errado).
ITENS_CONHECIDOS_SEM_MERCADO: list[tuple[str, str]] = [
    ("forma_blueprint", "Forma Blueprint"),
]


def _normalizar(texto: str) -> str:
    """Minúsculas e SEM espaços — o OCR às vezes junta palavras (ex.: 'FormaBlueprint')."""
    return "".join(texto.split()).casefold()


@dataclass
class ItemReconhecido:
    texto_ocr: str
    nome_encontrado: str | None
    preco_plata: float | None
    ducados: int | None
    slug: str | None
    confianca: float


def encontrar_melhor_correspondencia(texto_ocr: str, candidatos=None) -> ItemReconhecido:
    if candidatos is None:
        candidatos = todos_os_nomes_e_precos()
    if not texto_ocr.strip() or not candidatos:
        return ItemReconhecido(texto_ocr=texto_ocr, nome_encontrado=None, preco_plata=None, ducados=None, slug=None, confianca=0.0)

    nome_limpo = texto_ocr.strip()
    normalizado = _normalizar(nome_limpo)

    # 1) itens conhecidos que não têm página no mercado (Forma Blueprint etc.)
    #
    # O OCR costuma ler a etiqueta "Forma Blueprint" de vários jeitos ruins
    # ("Forma", "Forma Buepunt", "FormaBlueprint", "pet mats Forma Blueprint",
    # "eau FormaBlueprint") e o fuzzy matching aí casa com um Prime parecido
    # (Fragor, Mesa, Kavasa, Zephyr...), mostrando preço errado. Nenhum item
    # real do cache contém "forma" no nome, então "forma" presente no texto é
    # assinatura segura da recompensa. Exceção: se o texto também tem "prime",
    # é leitura ruim de um Prime de verdade — deixa o fuzzy tentar.
    for _slug, nome in ITENS_CONHECIDOS_SEM_MERCADO:
        if "forma" in normalizado and "prime" not in normalizado:
            return ItemReconhecido(
                texto_ocr=texto_ocr,
                nome_encontrado=nome,
                preco_plata=None,
                ducados=None,
                slug=None,  # sem slug: o overlay mostra o item mas não oferece venda
                confianca=100.0,
            )
        if _normalizar(nome) == normalizado:
            return ItemReconhecido(
                texto_ocr=texto_ocr,
                nome_encontrado=nome,
                preco_plata=None,
                ducados=None,
                slug=None,
                confianca=100.0,
            )

    # 2) nome exato no banco, ignorando espaços (OCR junta palavras às vezes)
    for candidato in candidatos:
        if _normalizar(candidato.nome) == _normalizar(nome_limpo):
            return ItemReconhecido(
                texto_ocr=texto_ocr,
                nome_encontrado=candidato.nome,
                preco_plata=candidato.preco_plata,
                ducados=candidato.ducados,
                slug=candidato.slug,
                confianca=100.0,
            )

    nomes = [candidato.nome for candidato in candidatos]
    resultado = process.extractOne(texto_ocr, nomes, scorer=fuzz.WRatio)

    if resultado is None or resultado[1] < LIMIAR_CONFIANCA:
        return ItemReconhecido(texto_ocr=texto_ocr, nome_encontrado=None, preco_plata=None, ducados=None, slug=None, confianca=(resultado[1] if resultado else 0.0))

    nome_encontrado, confianca, indice = resultado
    candidato = candidatos[indice]

    # Guarda extra: quando ambos os nomes têm " Prime ", o que vem ANTES tem
    # que casar também — senão o fuzzy aceita trocar o Warframe/arma (ex.:
    # "Sevagoth Prime Neuroptics Blueprint" casando com "Rhino Prime
    # Neuroptics Blueprint" só porque a cauda é igual). Se o prefixo
    # divergir demais, é outro item.
    if not _prefix_prime_combate(texto_ocr, candidato.nome, confianca):
        return ItemReconhecido(
            texto_ocr=texto_ocr,
            nome_encontrado=None,
            preco_plata=None,
            ducados=None,
            slug=None,
            confianca=confianca,
        )

    return ItemReconhecido(
        texto_ocr=texto_ocr,
        nome_encontrado=nome_encontrado,
        preco_plata=candidato.preco_plata,
        ducados=candidato.ducados,
        slug=candidato.slug,
        confianca=confianca,
    )


def _prefix_prime_combate(texto_ocr: str, nome_candidato: str, confianca: float = 0.0) -> bool:
    """Confere que o prefixo antes de ' Prime ' do OCR bate com o do candidato.

    Se um dos dois não tem ' Prime ' (ex.: Forma Blueprint), considera ok.

    Exceção consciente: quando o prefixo do OCR tem ESPAÇO (ex. "Ne Yea Prime
    Receiver" pra "Nezha Prime Receiver"), é quase certamente fragmento do
    mesmo nome lido errado — nomes de frame nunca têm duas palavras. Nesse
    caso, se a confiança total do match for alta (>= 75), aceitamos; os
    nomes de frames diferentes nunca têm espaço no prefixo, então isso não
    libera confusões tipo Garuda/Gauss ou Sevagoth/Rhino.
    """
    marcador = " prime "
    ocr_norm = " " + texto_ocr.lower() + " "
    cand_norm = " " + nome_candidato.lower() + " "
    if marcador not in ocr_norm or marcador not in cand_norm:
        return True
    prefixo_ocr = ocr_norm.split(marcador, 1)[0].strip()
    prefixo_cand = cand_norm.split(marcador, 1)[0].strip()
    if not prefixo_cand:
        return True
    if not prefixo_ocr:
        # Fragmento: o OCR leu só a cauda ("Prime Carapace", "Prime Stock").
        # Todo item Prime começa pelo nome do frame/arma, então sem prefixo é
        # leitura incompleta — recusar em vez de chutar um Prime parecido.
        return False
    if " " in prefixo_ocr and confianca >= 75:
        return True
    # exige prefixo similar: o nome do Warframe/arma não pode ter mudado
    return fuzz.ratio(prefixo_ocr, prefixo_cand) >= 70


def _eh_forma_blueprint(texto: str) -> bool:
    """Texto contém "forma" (e não "prime") — assinatura da recompensa Forma Blueprint.

    Nenhum item real tem "forma" no nome (verificado no cache), então isso só
    acerta a etiqueta Forma Blueprint lida de forma incompleta/ruim pelo OCR
    (ex.: só "Forma", ou "pet mats Forma Blueprint"). Usado antes do descarte
    de fragmentos pra que "Forma" sozinho não seja ignorado.
    """
    normalizado = _normalizar(texto)
    return "forma" in normalizado and "prime" not in normalizado


def _eh_fragmento(texto: str) -> bool:
    """Palavra solta de nome quebrado (ex: "Receiver", "Blueprint", "Prime").

    Esses fragmentos aparecem quando o OCR separa um nome em duas colunas. Sem
    essa proteção eles viram "opções" extras (5+ itens na tela com só 4
    recompensas de verdade).
    """
    palavras = texto.strip().split()
    # Nada ou só pontuação não é item.
    if not palavras:
        return True
    # 1 palavra só nunca é nome completo de item de relíquia (mínimo seria
    # "Forma Blueprint" — 2 palavras). Descarta "Prime", "Receiver",
    # "Blueprint", "Chassis" etc.
    return len(palavras) < 2


def _cauda_prime(texto: str) -> str:
    """A parte depois de ' Prime ' normalizada (ex.: 'Nezha Prime Receiver' -> 'receiver').

    O OCR às vezes lê o MESMO nome de duas formas diferentes (ex. "Vadarya
    Prime Receiver" e "Ne Yea Prime Receiver" sendo o mesmo "Nezha Prime
    Receiver"). A cauda depois de "prime" é a pista mais confiável de que se
    trata do mesmo item — o prefixo (nome do frame) é justamente o que o OCR
    mais erra.
    """
    marcador = " prime "
    texto_norm = " " + texto.casefold() + " "
    if marcador not in texto_norm:
        return ""
    return texto_norm.split(marcador, 1)[1].strip()


def reconhecer_todos(textos_ocr: list[str]) -> list[ItemReconhecido]:
    """Uma correspondência por texto de OCR.

    A separação dos itens acontece ANTES, no OCR (app/captura/ocr.py), que
    quebra o bloco em colunas por proximidade horizontal — então aqui cada
    texto já é um item. Um texto sem match confiável vira None (o overlay
    mostra "(não reconhecido)" em vez de inventar preço).

    Aqui também:
    - fragmentos de nome quebrado são descartados;
    - quando o mesmo item é reconhecido 2x (o OCR leu a mesma etiqueta de duas
      formas — ex. "Vadarya Prime Receiver" e "Ne Yea Prime Receiver" sendo o
      mesmo "Nezha Prime Receiver"), fica só a correspondência mais confiável;
    - leituras não-reconhecidas que compartilham a MESMA cauda depois de
      "Prime" de um item reconhecido (ou de outra leitura) são unificadas,
      em vez de virarem "opções fantasma".
    """
    resultados: list[ItemReconhecido] = []
    for texto in textos_ocr:
        # "Forma" sozinho é um fragmento (1 palavra), mas é a recompensa real
        # (o OCR às vezes perde o "Blueprint" por confiança baixa) — trata
        # antes do descarte de fragmentos.
        if _eh_forma_blueprint(texto):
            resultados.append(encontrar_melhor_correspondencia(texto))
            continue
        if _eh_fragmento(texto):
            continue
        resultados.append(encontrar_melhor_correspondencia(texto))

    reconhecidos = [r for r in resultados if r.slug is not None]

    # 1) Deduplica reconhecidos pelo slug mantendo o de maior confiança.
    #    O OCR pode ler a mesma etiqueta em duas colunas diferentes (ex. quando
    #    o nome quebra em 2 linhas) — nesse caso a mesma peça aparece 2x.
    por_slug: dict[str, ItemReconhecido] = {}
    for r in reconhecidos:
        atual = por_slug.get(r.slug)
        if atual is None or r.confianca > atual.confianca:
            por_slug[r.slug] = r

    # 2) Entre os NÃO-reconhecidos, unifica leituras da mesma etiqueta (mesma
    #    cauda "Prime") mantendo a mais completa. Isso evita opções fantasma
    #    quando o OCR despedaça um nome. SÓ entre não-reconhecidos — itens
    #    diferentes reconhecidos legamente compartilham a mesma cauda (ex:
    #    "Nezha Prime Receiver" e "Sevagoth Prime Receiver" ambos "receiver").
    nao_reconhecidos = [r for r in resultados if r.slug is None]
    por_cauda: dict[str, ItemReconhecido] = {}
    for r in nao_reconhecidos:
        cauda = _cauda_prime(r.texto_ocr)
        if cauda:
            atual = por_cauda.get(cauda)
            if atual is None or len(r.texto_ocr) > len(atual.texto_ocr):
                por_cauda[cauda] = r
    nao_reconhecidos_unificados = [
        r for r in nao_reconhecidos
        if _cauda_prime(r.texto_ocr) not in por_cauda
        or por_cauda[_cauda_prime(r.texto_ocr)] is r
    ]

    # 3) Junta reconhecidos (deduped) + não-reconhecidos (unificados), na ordem
    #    original de leitura (esquerda → direita) pra preservar o layout da tela.
    final = []
    for r in resultados:
        if r.slug is not None:
            if por_slug.get(r.slug) is r:
                final.append(r)
        else:
            if r in nao_reconhecidos_unificados:
                final.append(r)

    # 4) Proteção extra: nunca devolver mais que 4 (uma abertura tem no máx. 4).
    if len(final) > 4:
        # Prefere reconhecidos; entre os não-reconhecidos, os mais completos.
        final.sort(key=lambda r: (
            r.slug is not None,
            sum(1 for c in r.texto_ocr if c.isalnum()),
        ), reverse=True)
        final = final[:4]
        final.sort(key=lambda r: r.texto_ocr)
    return final
