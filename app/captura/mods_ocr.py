"""
OCR da tela de Offerings das Syndicates (grade de mods à venda).

A tela é uma grade 6×4 de cards (~152px de passo, validado no print
`exemplomods.png`): o PREÇO em standing ("25.000") fica no topo de cada card
com confiança altíssima no Paddle (0.99-1.00), e o NOME do mod fica numa faixa
mais abaixo, sobre a arte do card (texto pequeno e sobreposto à arte — é o que
torna o OCR do nome difícil).

Fluxo:
  1. Detecta os tokens de preço (padrão \\d+.\\d{3}) no recorte inteiro e
     estima o passo da grade a partir da posição deles (auto-adaptativo à
     resolução).
  2. Pra cada preço, recorta a BANDA do nome calibrada no print — relativa ao
     CENTRO do preço (px, py):
         x0 = px - 0.22·passo   x1 = px + 0.78·passo
         y0 = py + 0.14·passo   y1 = py + 0.55·passo
  3. OCR da banda com o Paddle (preciso em texto pequeno sobre a arte do card);
     fallback no Tesseract em variantes (psm6 bruta -> psm11 bruta -> upscale
     3x -> upscale 3x invert+sharpen -> upscale 2x sharpen), com parada
     antecipada por confiança. O texto vira o nome candidato.
  4. MATCHING EM DUAS PASSADAS contra o pool de mods de syndicate
     (app/dados/mods_syndicate.py), que tem os preços do mods_cache:
       - passada 1: match contra TODOS os mods de syndicate; vota nas
         syndicates dos mods que casaram (cada nome pode pertencer a mais de
         uma syndicate — elas compartilham mods em pares);
       - escolhe a syndicate dominante (no print: 21/23 votos pra Arbiters);
       - passada 2: re-match de cada banda restrito à syndicate escolhida
         (~67 mods) — elimina os falsos positivos do fuzzy no pool gigante
         ('Blade orn' -> Blade of Truth, 'calin& Frenzy' -> Calm & Frenzy).
  5. Quantidade é sempre 1 (a tela mostra 1 cópia por card; não há badge).

A coluna de quantidade do card (rank do mod, tipo '9') é lida junto com o nome
mas é descartada antes do match (nenhum nome de mod tem número).
"""
import re
from collections import Counter
from PIL import Image, ImageDraw
import pytesseract
from pytesseract import Output

from app.captura.inventario_ocr import ItemLido
from app.captura.ocr import (
    CONFIANCA_MINIMA_PALAVRA,
    CONFIANCA_PARADA,
    MINIMO_ALFANUMERICOS,
    PONTUACAO_DE_BORDA,
    _autocontraste,
    _filtro_whitelist,
    _grayscale,
    _inverter,
    _sharpen,
)
from app.captura.ocr_paddle import (
    PADDLE_CONFIANCA_MINIMA,
    _resultado_bruto,
)
from app.config import DEBUG_OCR, PASTA_DADOS
from app.dados.cache import listar_mods_candidatos
from app.dados.mods_syndicate import MODS_DE_SYNDICATE, MODS_SINDICATO_POR_NOME
from app.matching.comparador import encontrar_melhor_correspondencia

# ---------------------------------------------------------------------------
# Banda do nome, calibrada no print exemplomods.png (1599x900, passo 152px).
# Frações do passo: o passo é estimado a cada passada a partir dos preços.
# ---------------------------------------------------------------------------
# Banda do nome, calibrada no print exemplomods.png (1599x900, passo 152px).
# Frações do passo: o passo é estimado a cada passada a partir dos preços.
# ---------------------------------------------------------------------------
BANDA_X0_FRACAO = -0.22   # do centro do preço pra esquerda
BANDA_X1_FRACAO = 0.78    # do centro do preço pra direita
BANDA_Y0_FRACAO = 0.14    # do centro do preço pra baixo
BANDA_Y1_FRACAO = 0.55    # do centro do preço pra baixo
# Fallback do passo quando o OCR não acha 2 linhas de preços (grade com 1
# fileira): fração da maior dimensão do recorte. 0.095*1599 ~= 152px.
PITCH_PADRAO_FRACAO = 0.095
CONFIANCA_MINIMA_PRECO = 0.8
# Guarda de palavra única: OCR 1 palavra só (risco de falso positivo alto) —
# exige candidato de 1 palavra e confiança alta. Exceção: texto longo (>= 8
# chars) pode ser concatenação de um nome composto lido sem espaço pelo OCR
# ('AvengingeTruth' -> 'Avenging Truth'), aí o candidato de 2 palavras vale.
LIMIAR_PALAVRA_UNICA = 80
MINIMO_CHARS_CONCATENACAO = 8

# ---------------------------------------------------------------------------
# Leitura direta de nomes (fallback pra tela de Mods, sem âncora de preço)
# ---------------------------------------------------------------------------
# Tokens de interface que a área calibrada pode encostar (barra de busca,
# título) — nunca são nome de mod.
TOKENS_UI = frozenset({
    "name", "search", "mods", "hide", "owned", "exit", "filter",
    "sort", "rank", "polarity", "upgrade", "sell", "buy", "selling",
})
# Frações do recorte pra agrupar palavras em células: palavras da mesma linha
# têm y-centro próximo (<= TOLERANCIA_LINHA_FRACAO·altura); dentro da linha,
# palavras do mesmo card têm gap horizontal pequeno (<= GAP_MAXIMO_COLUNA_FRACAO·
# largura), gap grande => nova célula. Valores validados no print de tela de
# Mods (linhas ~0.36·altura de passo, gaps dentro do card <= 0.05·largura).
TOLERANCIA_LINHA_FRACAO = 0.05
GAP_MAXIMO_COLUNA_FRACAO = 0.06

# Variantes de pré-processamento da banda, em ordem, com parada antecipada
# quando a confiança média já passa de CONFIANCA_PARADA (mesma política da
# faixa de nomes de recompensa). Valores: (nome, psm, fator_upscale, invert,
# sharpen). "bruta" = sem upscale.
VARIANTES_BANDA = (
    ("bruta", 6, 1, False, False),
    ("bruta11", 11, 1, False, False),
    ("z3", 6, 3, False, False),
    ("z3is", 6, 3, True, True),
    ("z2s", 6, 2, False, True),
)


def _normalizar(texto: str) -> str:
    """Minúsculas e sem espaços (mesma normalização do comparador)."""
    return "".join(texto.split()).casefold()


def _limpar_texto_celula(texto: str) -> str:
    """Remove tokens que nunca fazem parte do nome: números puros (selo de
    rank do card) e símbolos soltos ('%', '&' lidos como palavra própria).

    Nenhum nome de mod tem número, então um '9' solto é o selo de rank — tirá-lo
    antes do fuzzy matching evita que ele atrapalhe a confiança.
    """
    palavras = [
        p for p in texto.split()
        if any(c.isalnum() for c in p) and not p.isdigit()
    ]
    return " ".join(palavras).strip()


# ---------------------------------------------------------------------------
# Âncoras da grade: tokens de preço
# ---------------------------------------------------------------------------

_PADRAO_PRECO = re.compile(r"\d{1,4}[.,]\d{3}")


def _detectar_precos(resultado: dict) -> list[dict]:
    """Tokens que parecem preço em standing (\\d+.\\d{3}) com suas caixas.

    O preço fica no topo de cada card com confiança ~1.0 — é a âncora mais
    confiável da grade. A posição (centro) é o que importa; o valor em si é
    ignorado (a tela vende por standing, não por platina).
    """
    precos = []
    for idx_linha, palavras in enumerate(resultado.get("text_word", [])):
        conf = resultado["rec_scores"][idx_linha]
        if conf < CONFIANCA_MINIMA_PRECO:
            continue
        caixas = resultado["text_word_boxes"][idx_linha]
        for texto, caixa in zip(palavras, caixas):
            texto = texto.strip(PONTUACAO_DE_BORDA).strip()
            if not _PADRAO_PRECO.fullmatch(texto.replace(" ", "")):
                continue
            x0, y0, x1, y1 = caixa
            precos.append({
                "texto": texto,
                "x0": int(x0), "y0": int(y0),
                "x1": int(x1), "y1": int(y1),
                "cx": (int(x0) + int(x1)) // 2,
                "cy": (int(y0) + int(y1)) // 2,
                "conf": float(conf),
            })
    return precos


def _estimar_pitch(precos: list[dict], altura: int) -> float | None:
    """Passo da grade pela mediana das distâncias verticais entre linhas de
    preço. Sem 2 linhas distintas, devolve None (fallback em pixels)."""
    cy = sorted({p["cy"] for p in precos})
    if len(cy) < 2:
        return None
    diffs = [b - a for a, b in zip(cy, cy[1:]) if b - a > 0.1 * altura]
    if not diffs:
        return None
    diffs.sort()
    return float(diffs[len(diffs) // 2])


def _deduplicar_ancoras(precos: list[dict], pitch: float) -> list[dict]:
    """Une preços da MESMA célula (o OCR às vezes divide '25.000' em 2 caixas).

    Mantém o de maior confiança quando dois centros ficam a menos de 0.5×passo
    na horizontal e 0.5×passo na vertical.
    """
    limiar = 0.5 * pitch
    unicos: list[dict] = []
    for preco in sorted(precos, key=lambda p: p["conf"], reverse=True):
        for existente in unicos:
            if (abs(preco["cx"] - existente["cx"]) <= limiar
                    and abs(preco["cy"] - existente["cy"]) <= limiar):
                break
        else:
            unicos.append(preco)
    return unicos


def _banda_do_preco(preco: dict, pitch: float, largura: int, altura: int) -> tuple | None:
    """Banda do nome calibrada relativa ao centro do preço, limitada ao recorte."""
    x0 = int(preco["cx"] + BANDA_X0_FRACAO * pitch)
    x1 = int(preco["cx"] + BANDA_X1_FRACAO * pitch)
    y0 = int(preco["cy"] + BANDA_Y0_FRACAO * pitch)
    y1 = int(preco["cy"] + BANDA_Y1_FRACAO * pitch)
    x0 = max(0, min(largura, x0))
    y0 = max(0, min(altura, y0))
    x1 = max(0, min(largura, x1))
    y1 = max(0, min(altura, y1))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return (x0, y0, x1, y1)


# ---------------------------------------------------------------------------
# OCR da banda do nome (Tesseract em variantes)
# ---------------------------------------------------------------------------

def _preparar_banda(faixa: Image.Image, fator: int, invertida: bool, nitida: bool) -> Image.Image:
    """Imagem da banda pra variante: grayscale + autocontraste + upscale
    opcional + invert/sharpen opcionais."""
    imagem = _autocontraste(_grayscale(faixa))
    if fator > 1:
        imagem = imagem.resize(
            (imagem.width * fator, imagem.height * fator),
            Image.LANCZOS,
        )
    if invertida:
        imagem = _inverter(imagem)
    if nitida:
        imagem = _sharpen(imagem)
    return imagem


def _texto_da_variante(dados: dict) -> str:
    """Junta as palavras reconhecidas (ordem de leitura) e filtra o whitelist."""
    palavras = []
    for i, texto in enumerate(dados["text"]):
        texto = texto.strip(PONTUACAO_DE_BORDA).strip()
        if not texto or int(dados["conf"][i]) < CONFIANCA_MINIMA_PALAVRA:
            continue
        if sum(1 for c in texto if c.isalnum()) < MINIMO_ALFANUMERICOS:
            continue
        palavras.append((dados["top"][i], dados["left"][i], texto))
    palavras.sort(key=lambda p: (p[0], p[1]))
    if not palavras:
        return ""
    return _filtro_whitelist(" ".join(p[2] for p in palavras))


def _escore_confianca(dados: dict) -> float:
    """Confiança média das palavras que passariam nos filtros (escolhe a
    melhor variante; parada antecipada em CONFIANCA_PARADA)."""
    confiancas = []
    for i, texto in enumerate(dados["text"]):
        texto = texto.strip(PONTUACAO_DE_BORDA).strip()
        if not texto or int(dados["conf"][i]) < CONFIANCA_MINIMA_PALAVRA:
            continue
        if sum(1 for c in texto if c.isalnum()) < MINIMO_ALFANUMERICOS:
            continue
        confiancas.append(int(dados["conf"][i]))
    if not confiancas:
        return -1.0
    return sum(confiancas) / len(confiancas)


def _reconhecer_banda(faixa: Image.Image) -> str:
    """OCR da banda do nome: Paddle (preciso em texto pequeno sobre arte);
    fallback nas variantes do Tesseract quando o Paddle não devolve texto útil."""
    resultado = _resultado_bruto(faixa, salvar_debug=False)
    palavras = []
    for idx_linha, palavras_linha in enumerate(resultado.get("text_word", [])):
        if resultado["rec_scores"][idx_linha] < PADDLE_CONFIANCA_MINIMA:
            continue
        for palavra in palavras_linha:
            palavra = palavra.strip(PONTUACAO_DE_BORDA).strip()
            if palavra:
                palavras.append(palavra)
    texto = " ".join(palavras)
    if sum(1 for c in texto if c.isalnum()) >= MINIMO_ALFANUMERICOS + 1:
        return texto
    return _reconhecer_banda_tesseract(faixa)


def _reconhecer_banda_tesseract(faixa: Image.Image) -> str:
    """Fallback: variantes de pré-processamento em ordem com parada antecipada;
    fica com o texto da variante de maior confiança média."""
    melhor_texto = ""
    melhor_escore = -1.0
    for nome, psm, fator, invertida, nitida in VARIANTES_BANDA:
        imagem = _preparar_banda(faixa, fator, invertida, nitida)
        dados = pytesseract.image_to_data(
            imagem, config=f"--psm {psm}", output_type=Output.DICT
        )
        escore = _escore_confianca(dados)
        if escore > melhor_escore:
            melhor_escore = escore
            melhor_texto = _texto_da_variante(dados)
        if escore >= CONFIANCA_PARADA:
            break
    return melhor_texto


# ---------------------------------------------------------------------------
# Matching em duas passadas contra os mods de syndicate
# ---------------------------------------------------------------------------

def _candidatos_mods_por_nome() -> dict[str, object]:
    """Mapa nome normalizado -> ItemCache do mods_cache (com preço/slug).

    Só entram mods que existem no cache local (preço de platina conhecido).
    """
    por_nome = {}
    for item in listar_mods_candidatos():
        por_nome.setdefault(_normalizar(item.nome), item)
    return por_nome


def _pool_dos_nomes(por_nome: dict, nomes) -> list:
    """Pool de candidatos ItemCache pros nomes dados, sem duplicar por slug."""
    pool = []
    vistos = set()
    for nome in nomes:
        item = por_nome.get(_normalizar(nome))
        if item is not None and item.slug not in vistos:
            vistos.add(item.slug)
            pool.append(item)
    return pool


def _matchar(texto: str, pool: list) -> object | None:
    """Fuzzy match do texto da banda contra o pool, com as guardas calibradas.

    Guardas (validadas no print — o WRatio casa parcialmente lixo com nomes):
      - mínimo de 3 caracteres alfanuméricos ('ae', 'a' não passam);
      - OCR de 1 palavra exige candidato de 1 palavra e confiança >= 80
        (palavra solta de mod composto é falso positivo provável).
    """
    if not texto:
        return None
    if sum(1 for c in texto if c.isalnum()) < MINIMO_ALFANUMERICOS:
        return None
    resultado = encontrar_melhor_correspondencia(texto, candidatos=pool)
    if resultado.slug is None:
        return None
    if len(texto.split()) == 1:
        nome = (resultado.nome_encontrado or "").strip()
        if " " in nome and len(texto) < MINIMO_CHARS_CONCATENACAO:
            return None
        if " " not in nome and resultado.confianca < LIMIAR_PALAVRA_UNICA:
            return None
    return resultado


def _palavras_do_recorte(resultado: dict) -> list[dict]:
    """Palavras do OCR que podem fazer parte de nome de mod (com caixa/centro).

    Descarta tokens puramente numéricos (selo de rank do card: '9', '51'),
    tokens de interface (barra de busca/título da tela de Mods) e símbolos
    sem letras ('%', '='...). Palavra curta tipo "s" (de "Hunter's") passa —
    quem corta lixo de célula é o `_matchar` (mínimo de alfanuméricos).
    """
    palavras = []
    for idx, palavras_linha in enumerate(resultado.get("text_word", [])):
        if resultado["rec_scores"][idx] < PADDLE_CONFIANCA_MINIMA:
            continue
        caixas = resultado["text_word_boxes"][idx]
        for texto, caixa in zip(palavras_linha, caixas):
            texto = texto.strip(PONTUACAO_DE_BORDA).strip()
            if not texto or texto.isdigit():
                continue
            if texto.casefold() in TOKENS_UI:
                continue
            if not any(c.isalnum() for c in texto):
                continue
            x0, y0, x1, y1 = caixa
            palavras.append({
                "texto": texto,
                "cx": (int(x0) + int(x1)) / 2,
                "cy": (int(y0) + int(y1)) / 2,
                "x0": int(x0), "y0": int(y0),
                "x1": int(x1), "y1": int(y1),
            })
    return palavras


def _agrupar_palavras_em_celulas(palavras: list[dict], tamanho: tuple) -> list[dict]:
    """Agrupa as palavras do recorte em células (nome de um mod), sem âncora.

    Estratégia (valida no print de tela de Mods): palavras da mesma linha têm
    y-centro próximo (tolerância em fração da altura); dentro da linha,
    palavras do mesmo card têm gap horizontal pequeno, gap grande => nova
    célula. Cada célula vira o nome candidato com a caixa que engloba tudo.
    """
    largura, altura = tamanho
    tol_linha = TOLERANCIA_LINHA_FRACAO * altura
    gap_max = GAP_MAXIMO_COLUNA_FRACAO * largura

    linhas: list[list[dict]] = []
    for palavra in sorted(palavras, key=lambda p: (p["cy"], p["x0"])):
        if linhas and abs(palavra["cy"] - linhas[-1][0]["cy"]) <= tol_linha:
            linhas[-1].append(palavra)
        else:
            linhas.append([palavra])

    celulas = []
    for linha in linhas:
        linha.sort(key=lambda p: p["x0"])
        atual = [linha[0]]
        for palavra in linha[1:]:
            if palavra["x0"] - atual[-1]["x1"] <= gap_max:
                atual.append(palavra)
            else:
                celulas.append(atual)
                atual = [palavra]
        celulas.append(atual)

    resultado = []
    for celula in celulas:
        texto = _limpar_texto_celula(" ".join(p["texto"] for p in celula))
        if not texto:
            continue
        x0 = min(p["x0"] for p in celula)
        y0 = min(p["y0"] for p in celula)
        x1 = max(p["x1"] for p in celula)
        y1 = max(p["y1"] for p in celula)
        resultado.append({
            "texto": texto,
            "banda": (x0, y0, x1, y1),  # compatível com _salvar_debug_grade
            "cx": sum(p["cx"] for p in celula) / len(celula),
            "cy": sum(p["cy"] for p in celula) / len(celula),
            "x0": x0, "y0": y0,
            "x1": x1, "y1": y1,
        })
    return resultado


def _pool_todos_os_mods(por_nome: dict) -> list:
    """Pool com TODOS os mods do cache (a tela de Mods mostra qualquer mod do
    jogador, não só os de syndicate). Sem duplicar por slug."""
    pool = []
    vistos = set()
    for item in por_nome.values():
        if item.slug not in vistos:
            vistos.add(item.slug)
            pool.append(item)
    return pool


def _ler_nomes_da_grade(recorte, bruto: dict) -> tuple[list[ItemLido], list[dict]]:
    """Lê os nomes de mods direto do recorte e busca o preço no cache completo.

    Fallback pra tela de Mods (grade SEM preço em standing): em vez de ancorar
    em preço, agrupa as palavras do OCR em células (linha/coluna) e casa cada
    célula com o cache inteiro. Quantidade sempre 1. Devolve (itens, celulas)
    — celulas com `resultado` anexado pra debug.
    """
    palavras = _palavras_do_recorte(bruto)
    if not palavras:
        return [], []

    celulas = _agrupar_palavras_em_celulas(palavras, recorte.size)
    por_nome = _candidatos_mods_por_nome()
    if not por_nome:
        return [], celulas
    pool = _pool_todos_os_mods(por_nome)

    itens = []
    for celula in celulas:
        resultado = _matchar(celula["texto"], pool)
        celula["resultado"] = resultado
        if resultado is None:
            continue
        itens.append(ItemLido(
            nome=resultado.nome_encontrado,
            quantidade=1,
            preco_plata=resultado.preco_plata,
            slug=resultado.slug,
            ducados=None,
            confianca=resultado.confianca,
            x=celula["cx"],
            y=celula["cy"],
            x0=celula["x0"],
            y0=celula["y0"],
            x1=celula["x1"],
            y1=celula["y1"],
        ))
    return itens, celulas


def _sindicate_dominante(celulas: list[dict]) -> str | None:
    """Syndicate mais votada: cada mod reconhecido vota nas syndicates que o
    vendem (um mod pode pertencer a um par de syndicates)."""
    votos: Counter = Counter()
    for celula in celulas:
        resultado = celula.get("resultado")
        if resultado is None:
            continue
        for sindicate in MODS_SINDICATO_POR_NOME.get(
            _normalizar(resultado.nome_encontrado), ()
        ):
            votos[sindicate] += 1
    if not votos:
        return None
    return votos.most_common(1)[0][0]


# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------

def _salvar_debug_grade(recorte: Image.Image, celulas: list[dict], pitch: float | None):
    """DEBUG: salva o recorte com as bandas do nome desenhadas por célula."""
    if not DEBUG_OCR:
        return
    pasta = PASTA_DADOS / "debug"
    pasta.mkdir(parents=True, exist_ok=True)
    imagem = recorte.convert("RGB").copy()
    desenho = ImageDraw.Draw(imagem)
    for celula in celulas:
        banda = celula.get("banda")
        if banda is None:
            continue
        cor = "#3fdb6e" if celula.get("resultado") is not None else "#e06f7a"
        desenho.rectangle(banda, outline=cor, width=2)
        texto = celula.get("texto", "")
        if texto:
            desenho.text((banda[0] + 4, banda[1] + 2), texto[:28], fill="#ffffff")
    imagem.save(pasta / "mods_grade_cells.png")


def reconhecer_itens_mods(recorte, avisos: list | None = None) -> list[ItemLido]:
    """Roda o OCR na tela de Offerings recortada e devolve as células lidas.

    Duas passadas de matching: primeiro contra TODOS os mods de syndicate pra
    descobrir a syndicate dominante da tela, depois restrito à syndicate
    escolhida (elimina falsos positivos do pool gigante). Só entra o que casou
    com um mod de syndicate conhecido; quantidade sempre 1 (a tela não tem
    badge de cópias). Célula sem match confiável é descartada.

    `avisos` (opcional) recebe os porquês de a leitura ter vindo vazia — a UI
    usa pra avisar que a tela/área não parece a grade de Offerings em vez de
    só devolver uma tabela vazia sem explicação.

    Quando a área NÃO tem preço em standing (tela de Mods do jogo, que não
    mostra preço), há um fallback que lê os nomes direto do recorte e busca o
    preço de cada um no cache completo — a grade de Mods funciona igual.
    """

    def avisar(mensagem: str):
        if avisos is not None:
            avisos.append(mensagem)

    if DEBUG_OCR:
        pasta = PASTA_DADOS / "debug"
        pasta.mkdir(parents=True, exist_ok=True)
        recorte.convert("RGB").save(pasta / "mods_grade.png")

    largura, altura = recorte.size
    bruto = _resultado_bruto(recorte, salvar_debug=False)
    precos = _detectar_precos(bruto)
    if not precos:
        # Tela de Mods (sem preço em standing): em vez de desistir, lê os
        # nomes direto do recorte e busca o preço de cada um no cache.
        itens, celulas = _ler_nomes_da_grade(recorte, bruto)
        _salvar_debug_grade(recorte, celulas, None)
        if itens:
            if DEBUG_OCR:
                for item in itens:
                    print(f"[MODS] (grade direta) {item.nome!r} -> "
                          f"{item.preco_plata}p")
            return itens
        avisar(
            "nenhum preço em standing (ex: 25.000) nem nome de mod na área — "
            "confirme que a tela é a de Offerings de uma Syndicate (grade de "
            "cards com preço no topo) ou a tela de Mods do jogo (grade de "
            "cards com nome) e que a área salva cobre a grade inteira."
        )
        return []

    pitch = _estimar_pitch(precos, altura)
    if pitch is None:
        pitch = PITCH_PADRAO_FRACAO * max(largura, altura)
    precos = _deduplicar_ancoras(precos, pitch)

    por_nome = _candidatos_mods_por_nome()
    if not por_nome:
        avisar(
            "cache de mods vazio — baixe os preços de mods primeiro (aba "
            "Overlay), senão não há nome pra casar."
        )
        return []

    # Passada 1: match contra o pool completo de syndicates.
    pool_completo = _pool_dos_nomes(
        por_nome, (n for nomes in MODS_DE_SYNDICATE.values() for n in nomes)
    )
    celulas = []
    for preco in precos:
        banda = _banda_do_preco(preco, pitch, largura, altura)
        if banda is None:
            continue
        texto = _limpar_texto_celula(_reconhecer_banda(recorte.crop(banda)))
        celula = {
            "preco": preco,
            "banda": banda,
            "texto": texto,
            "resultado": _matchar(texto, pool_completo),
        }
        celulas.append(celula)

    sindicate = _sindicate_dominante(celulas)

    # Passada 2: re-match restrito à syndicate escolhida.
    if sindicate is not None:
        pool_restrito = _pool_dos_nomes(por_nome, MODS_DE_SYNDICATE[sindicate])
        if pool_restrito:
            for celula in celulas:
                resultado = _matchar(celula["texto"], pool_restrito)
                if resultado is not None:
                    celula["resultado"] = resultado

    if DEBUG_OCR:
        print(f"[MODS] sindicate detectada: {sindicate}")
        for celula in celulas:
            r = celula.get("resultado")
            if r is not None:
                print(f"[MODS]   {celula['texto']!r} -> {r.nome_encontrado} "
                      f"(conf={r.confianca:.0f})")

    itens = []
    for celula in celulas:
        resultado = celula.get("resultado")
        if resultado is None:
            continue
        preco = celula["preco"]
        banda = celula["banda"]
        itens.append(ItemLido(
            nome=resultado.nome_encontrado,
            quantidade=1,
            preco_plata=resultado.preco_plata,
            slug=resultado.slug,
            ducados=None,
            confianca=resultado.confianca,
            x=preco["cx"],
            y=preco["cy"],
            x0=banda[0],
            y0=banda[1],
            x1=banda[2],
            y1=banda[3],
        ))

    if not itens:
        avisar(
            f"{len(celulas)} card(s) lidos, mas nenhum nome casou com um mod "
            "de syndicate — confirme que a tela é a de Offerings e que a área "
            "cobre a grade inteira."
        )

    _salvar_debug_grade(recorte, celulas, pitch)
    return itens
