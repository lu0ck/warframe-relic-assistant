"""
OCR da grade do inventário (tela de vendas/Inventory do jogo).

Recorta a área demarcada pelo usuário e reconstrói a grade 2D de nomes: cada
célula (nome da peça abaixo do ícone) vira um `ItemLido` com o texto, a
posição (pra preservar a ordem de leitura) e o preço/slug resolvidos por
fuzzy matching contra o cache local (o mesmo do overlay).

Quantidade (F3): sem check dourado de quantidade o item vale 1. O check
aparece só quando há 2+ cópias: um "✓" dourado (~7-9px, cor rgb(190,169,102))
no canto do ÍCONE, logo acima do nome, com o número da quantidade ao lado
direito. Pra cada célula, busca a faixa acima do nome por um componente
dourado compacto em formato de check/losango e, se achar, lê o número ao lado.

As distâncias/tamanhos são CALIBRADAS no print real
(dados_locais/prints/printinventario.png, passo da grade ≈171px) e escaladas
pelo passo da grade estimado a cada passada — assim a detecção funciona em
qualquer resolução de janela do jogo, não só na do print.
"""
import re
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from app.captura.ocr import (
    MINIMO_ALFANUMERICOS,
    PONTUACAO_DE_BORDA,
    _filtro_whitelist,
)
from app.captura.ocr_paddle import (
    PADDLE_CONFIANCA_MINIMA,
    _resultado_bruto,
)
from app.config import DEBUG_OCR, ESPACO_MINIMO_ENTRE_ITENS_PX, PASTA_DADOS
from app.dados.cache import todos_os_nomes_e_precos
from app.matching.comparador import encontrar_melhor_correspondencia

# ---------------------------------------------------------------------------
# Check dourado de quantidade (F3)
# ---------------------------------------------------------------------------
# O check fica no canto do ícone, logo acima do nome; a faixa de busca vai um
# pouco além das bordas do nome (horizontal) e sobe acima do topo do texto
# (vertical). Tudo em pixels DO PRINT DE CALIBRAÇÃO (passo da grade = 171px).
# A cada passada o passo real da grade é estimado e os valores são escalados
# por passo/171 — robusto a mudança de resolução da janela do jogo.
PITCH_REFERENCIA = 171.0

# Faixa de busca do check, calibrada no print (check fica ~87-101px acima do
# topo do nome, daí uma faixa de busca maior que a do nome).
SELO_ALTURA_ACIMA_NOME_PX = 120
SELO_MARGEM_INFERIOR_ACIMA_NOME_PX = 55
SELO_EXTENSAO_ESQUERDA_PX = 30
SELO_EXTENSAO_DIREITA_PX = 10
# Cor do check (dourado Warframe) em RGB: (190, 169, 102) medido no print.
# A faixa de detecção é BRILHANTE (só valores >= centro): o contorno do "2"
# em volta do check é dourado mais escuro e não deve fundir com ele.
SELO_COR_RGB = (190, 169, 102)
SELO_TOLERANCIA_RGB = 22
# Formato do check: componente conexo dourado compacto (check ~5-12px).
SELO_TAMANHO_MIN_PX = 5
SELO_TAMANHO_MAX_PX = 12
SELO_MINIMO_PIXELS = 8
# Janela de leitura do número: começa no check (dá contexto pro OCR) e vai
# ~34px para a direita (o número fica logo ao lado direito do check).
SELO_JANELA_NUMERO_EXTENSAO_PX = 34
SELO_JANELA_NUMERO_MARGEM_ESQ_PX = 6
SELO_JANELA_NUMERO_MARGEM_VER_PX = 8
# O OCR lê a janela check+número SEM upscale (fator 1) com confiança ~0.99
# nas 4 células com check do print real; com upscale falha em algumas.
FATOR_UPSCALE_SELO = 1


def _escala_selo(pitch: float | None, valor_px: float) -> float:
    """Escala um valor calibrado no print (pitch de referência) pro passo da
    grade atual; sem pitch (grade com 1 linha só), usa o valor em pixels."""
    if not pitch or pitch <= 0:
        return valor_px
    return valor_px * pitch / PITCH_REFERENCIA


@dataclass
class ItemLido:
    """Uma célula da grade lida na última passada da varredura."""
    nome: str                # nome canônico (match no cache) ou como saiu do OCR
    quantidade: int = 1
    preco_plata: float | None = None
    slug: str | None = None
    ducados: int | None = None
    confianca: float = 0.0
    x: int = 0               # posição na célula (pra ordenação de leitura)
    y: int = 0
    x0: int = 0              # limites da célula (selo busca acima do topo)
    y0: int = 0
    x1: int = 0
    y1: int = 0


def _reconstruir_grade(resultado: dict) -> list[dict]:
    """Reconstrói as células da grade a partir das caixas de palavra do Paddle.

    Dentro de cada linha detectada, palavras com gap horizontal grande viram
    células separadas (itens lado a lado na mesma fileira). Cada célula carrega
    o texto, os limites e a confiança da linha.
    """
    espaco_minimo_px = ESPACO_MINIMO_ENTRE_ITENS_PX  # fator 1: coords originais
    linhas: list[tuple[list, float]] = []

    for idx_linha, palavras in enumerate(resultado.get("text_word", [])):
        conf_linha = resultado["rec_scores"][idx_linha]
        if conf_linha < PADDLE_CONFIANCA_MINIMA:
            continue
        caixas = resultado["text_word_boxes"][idx_linha]
        palavras_filtradas = []
        for texto, caixa in zip(palavras, caixas):
            texto = texto.strip(PONTUACAO_DE_BORDA).strip()
            if not texto:
                continue
            if sum(1 for c in texto if c.isalnum()) < MINIMO_ALFANUMERICOS:
                continue
            x0, y0, x1, y1 = caixa
            palavras_filtradas.append((x0, y0, x1, y1, texto))

        palavras_filtradas.sort(key=lambda p: p[0])
        subgrupo = []
        fim_anterior = None
        for x0, y0, x1, y1, texto in palavras_filtradas:
            if fim_anterior is not None and (x0 - fim_anterior) > espaco_minimo_px:
                linhas.append((subgrupo, conf_linha))
                subgrupo = []
            subgrupo.append((x0, y0, x1, y1, texto))
            fim_anterior = x1
        if subgrupo:
            linhas.append((subgrupo, conf_linha))

    celulas = []
    for subgrupo, conf_linha in linhas:
        texto = _filtro_whitelist(" ".join(p[4] for p in subgrupo))
        if sum(1 for c in texto if c.isalnum()) < MINIMO_ALFANUMERICOS + 1:
            continue
        celulas.append({
            "x0": min(p[0] for p in subgrupo),
            "y0": min(p[1] for p in subgrupo),
            "x1": max(p[2] for p in subgrupo),
            "y1": max(p[3] for p in subgrupo),
            "texto": texto,
            "conf": conf_linha,
        })

    # Ordem de leitura da grade: fileira por fileira, da esquerda pra direita.
    celulas.sort(key=lambda c: (c["y0"], c["x0"]))
    return celulas


def _estimar_passo_da_grade(celulas: list[dict], altura_recorte: int) -> float | None:
    """Estima o passo vertical da grade (distância entre fileiras).

    Usa as posições `y0` das células: diferenças pequenas (mesma fileira,
    nomes quebrados) são descartadas; a mediana das diferenças grandes é o
    passo. Sem ao menos 2 fileiras, devolve None (detecção usa pixels fixos).
    """
    y0s = sorted({int(c["y0"]) for c in celulas})
    if len(y0s) < 3:
        return None
    limiar = 0.15 * altura_recorte
    diffs = [
        b - a
        for a, b in zip(y0s, y0s[1:])
        if b - a > limiar
    ]
    if not diffs:
        return None
    diffs.sort()
    return float(diffs[len(diffs) // 2])


def _fundir_grade(celulas: list[dict], pitch: float | None) -> list[dict]:
    """Une células de linhas consecutivas da MESMA coluna numa só.

    No jogo o nome da peça quebra em 2 linhas; o OCR devolve uma célula por
    linha, criando itens-fantasma. Células com x-ranges sobrepostos e que
    começam logo abaixo (gap < 0.5×passo) são a mesma peça: funde texto e
    limites. Sem passo estimado, devolve as células como estão.
    """
    if not pitch:
        return celulas
    fundidas: list[dict] = []
    for celula in sorted(celulas, key=lambda c: (c["y0"], c["x0"])):
        alvo = None
        for base in fundidas:
            if base["x1"] < celula["x0"] or celula["x1"] < base["x0"]:
                continue  # colunas diferentes
            if abs(celula["y0"] - base["y1"]) < 0.5 * pitch:
                alvo = base
                break
        if alvo is None:
            fundidas.append(dict(celula))
        else:
            alvo["x0"] = min(alvo["x0"], celula["x0"])
            alvo["x1"] = max(alvo["x1"], celula["x1"])
            alvo["y1"] = max(alvo["y1"], celula["y1"])
            alvo["texto"] = (alvo["texto"] + " " + celula["texto"]).strip()
    return fundidas


# ---------------------------------------------------------------------------
# Selo de quantidade
# ---------------------------------------------------------------------------

def _componentes_conexos(mascara: np.ndarray) -> list[list[tuple[int, int]]]:
    """Lista os componentes conexos (4-vizinhança) de uma máscara booleana."""
    altura, largura = mascara.shape
    visitado = np.zeros_like(mascara)
    componentes = []
    for iy in range(altura):
        for ix in range(largura):
            if visitado[iy, ix] or not mascara[iy, ix]:
                continue
            fila = [(ix, iy)]
            visitado[iy, ix] = True
            pontos = []
            while fila:
                cx, cy = fila.pop()
                pontos.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < largura and 0 <= ny < altura and not visitado[ny, nx] and mascara[ny, nx]:
                        visitado[ny, nx] = True
                        fila.append((nx, ny))
            componentes.append(pontos)
    return componentes


def _eh_losango(pontos: list[tuple[int, int]], pitch: float | None) -> bool:
    """True se o componente dourado tem o formato compacto do check (✓).

    O check é pequeno (tamanho calibrado no print, escalado pelo passo da
    grade), com as pontas de cima e de baixo estreitas — 1-2px. Componentes
    grandes (ícones Prime dourados) e faixas longas ficam de fora.
    """
    tam_min = _escala_selo(pitch, SELO_TAMANHO_MIN_PX)
    tam_max = _escala_selo(pitch, SELO_TAMANHO_MAX_PX)
    pixels_min = max(5, round(_escala_selo(pitch, SELO_MINIMO_PIXELS)))
    xs = [p[0] for p in pontos]
    ys = [p[1] for p in pontos]
    largura = max(xs) - min(xs) + 1
    altura = max(ys) - min(ys) + 1
    if not (tam_min <= largura <= tam_max and tam_min <= altura <= tam_max):
        return False
    if len(pontos) < pixels_min:
        return False
    topo = [p for p in pontos if p[1] == min(ys)]
    base = [p for p in pontos if p[1] == max(ys)]
    return len(topo) <= 2 and len(base) <= 2


def _encontrar_selo(recorte, celula: dict, pitch: float | None) -> tuple | None:
    """Posição do check dourado (x0, y0, x1, y1) acima do nome, ou None.

    Busca componentes conexos da cor do check na faixa acima do topo do nome;
    o primeiro componente compacto em formato de check é o selo.
    """
    regiao = _regiao_do_selo(recorte, celula, pitch)
    if regiao is None:
        return None
    x0, y0, x1, y1 = regiao
    fatia = np.asarray(recorte.crop((x0, y0, x1, y1)).convert("RGB")).astype(int)
    # Faixa BRILHANTE: só pixels da cor do check PRA CIMA (centro..centro+tol),
    # validada no print real. A faixa simétrica completa une o check ao
    # contorno do "2" ao redor dele (dourado mais escuro) num blob só.
    mascara = (
        (fatia[:, :, 0] >= SELO_COR_RGB[0])
        & (fatia[:, :, 0] <= SELO_COR_RGB[0] + SELO_TOLERANCIA_RGB)
        & (fatia[:, :, 1] >= SELO_COR_RGB[1])
        & (fatia[:, :, 1] <= SELO_COR_RGB[1] + SELO_TOLERANCIA_RGB)
        & (fatia[:, :, 2] >= SELO_COR_RGB[2])
        & (fatia[:, :, 2] <= SELO_COR_RGB[2] + SELO_TOLERANCIA_RGB)
    )
    for pontos in _componentes_conexos(mascara):
        if not _eh_losango(pontos, pitch):
            continue
        xs = [p[0] for p in pontos]
        ys = [p[1] for p in pontos]
        return (min(xs) + x0, min(ys) + y0, max(xs) + x0, max(ys) + y0)
    return None


def _regiao_do_selo(recorte, celula: dict, pitch: float | None) -> tuple | None:
    """Faixa de busca do check: acima do nome, margens validadas no print
    real (diag_ouro38) escaladas pelo passo da grade."""
    largura, altura = recorte.size
    esq = _escala_selo(pitch, SELO_EXTENSAO_ESQUERDA_PX)
    dir_ = _escala_selo(pitch, SELO_EXTENSAO_DIREITA_PX)
    topo = _escala_selo(pitch, SELO_ALTURA_ACIMA_NOME_PX)
    base = _escala_selo(pitch, SELO_MARGEM_INFERIOR_ACIMA_NOME_PX)
    x0 = max(0, int(celula["x0"]) - int(esq))
    x1 = min(largura, int(celula["x1"]) + int(dir_))
    y0 = max(0, int(celula["y0"]) - int(topo))
    y1 = min(altura, int(celula["y0"]) - int(base))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return (x0, y0, x1, y1)


def _extrair_quantidade(texto: str) -> int | None:
    """Extrai o número do selo (aceita 'x3', '3', '2'...)."""
    encontrado = re.search(r"(\d+)", texto)
    if not encontrado:
        return None
    quantidade = int(encontrado.group(1))
    return quantidade if quantidade >= 1 else None


def _ler_quantidade_do_selo(recorte, celula: dict, pitch: float | None) -> int:
    """Quantidade do item lida do selo dourado; 1 quando não há selo.

    Sem selo = quantidade 1 (regra confirmada na tela de vendas). Com selo,
    lê o número logo ao lado direito dele com o Paddle. Se o dourado aparecer
    mas o número não for lido, mantém 1 (não inventa quantidade).
    """
    selo = _encontrar_selo(recorte, celula, pitch)
    if selo is None:
        return 1
    x0, y0, x1, y1 = _regiao_do_numero(recorte, selo, pitch)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return 1
    faixa = recorte.crop((x0, y0, x1, y1))
    ampliada = faixa.resize(
        (faixa.width * FATOR_UPSCALE_SELO, faixa.height * FATOR_UPSCALE_SELO),
        Image.LANCZOS,
    )
    try:
        resultado = _resultado_bruto(ampliada, salvar_debug=False)
        textos = []
        for palavras in resultado.get("text_word", []):
            for palavra in palavras:
                texto = palavra.strip(PONTUACAO_DE_BORDA).strip()
                if texto:
                    textos.append(texto)
        quantidade = _extrair_quantidade(" ".join(textos))
    except Exception:
        quantidade = None
    return quantidade if quantidade is not None else 1


def _regiao_do_numero(recorte, selo: tuple, pitch: float | None) -> tuple:
    """Janela de leitura do número: selo+~6px de margem à esquerda (contexto
    pro OCR) até a extensão calibrada à direita, na altura do selo ±8px
    (diag_ouro39: lê '2' nas 4 células com selo do print real, sem upscale).
    A extensão da direita é escalada pelo passo da grade.
    """
    largura, altura = recorte.size
    sx0, sy0, sx1, sy1 = selo
    x0 = max(0, sx0 - SELO_JANELA_NUMERO_MARGEM_ESQ_PX)
    x1 = min(largura, sx1 + int(_escala_selo(pitch, SELO_JANELA_NUMERO_EXTENSAO_PX)))
    y0 = max(0, sy0 - SELO_JANELA_NUMERO_MARGEM_VER_PX)
    y1 = min(altura, sy1 + SELO_JANELA_NUMERO_MARGEM_VER_PX)
    return (x0, y0, x1, y1)


def _salvar_debug_selos(recorte, celulas: list[dict], quantidades: dict, pitch: float | None):
    """DEBUG: salva a grade com as regiões de busca do selo desenhadas."""
    if not DEBUG_OCR:
        return
    pasta = PASTA_DADOS / "debug"
    pasta.mkdir(parents=True, exist_ok=True)
    imagem = recorte.convert("RGB").copy()
    desenho = ImageDraw.Draw(imagem)
    for celula in celulas:
        regiao = _regiao_do_selo(recorte, celula, pitch)
        if regiao is None:
            continue
        cor = "#3fdb6e" if quantidades.get(celula["texto"], 1) > 1 else "#e06f7a"
        desenho.rectangle(regiao, outline=cor, width=2)
    imagem.save(pasta / "inventario_grade_selos.png")


def reconhecer_itens_inventario(recorte) -> list[ItemLido]:
    """Roda o OCR na grade recortada e devolve as células lidas.

    Cada célula é resolvida contra o cache (uma única carga dos candidatos pra
    toda a passada — a grade tem dezenas de células). A grade só mostra peças
    Prime, então só entra item que casou com um Prime conhecido DO CACHE E tem
    preço — texto solto (fala de NPC ao fundo, fragmento de nome vizinho, OCR
    confuso) é descartado, sem fallback pro texto cru. A quantidade vem do
    selo dourado (F3); sem selo = 1.
    """
    if DEBUG_OCR:
        pasta = PASTA_DADOS / "debug"
        pasta.mkdir(parents=True, exist_ok=True)
        recorte.convert("RGB").save(pasta / "inventario_grade.png")

    celulas_brutas = _reconstruir_grade(_resultado_bruto(recorte))
    pitch = _estimar_passo_da_grade(celulas_brutas, recorte.height)
    celulas = _fundir_grade(celulas_brutas, pitch)
    if not celulas:
        return []

    candidatos = todos_os_nomes_e_precos()
    itens = []
    quantidades_por_texto: dict[str, int] = {}
    for celula in celulas:
        texto = celula["texto"]
        resultado = encontrar_melhor_correspondencia(texto, candidatos=candidatos)
        if resultado.slug is None or resultado.preco_plata is None:
            continue  # sem match confiável de Prime ou sem preço: não entra
        quantidade = _ler_quantidade_do_selo(recorte, celula, pitch)
        quantidades_por_texto[texto] = quantidade
        itens.append(ItemLido(
            nome=resultado.nome_encontrado or texto,
            quantidade=quantidade,
            preco_plata=resultado.preco_plata,
            slug=resultado.slug,
            ducados=resultado.ducados,
            confianca=celula["conf"],
            x=celula["x0"],
            y=celula["y0"],
            x0=celula["x0"],
            y0=celula["y0"],
            x1=celula["x1"],
            y1=celula["y1"],
        ))

    if DEBUG_OCR:
        _salvar_debug_selos(recorte, celulas, quantidades_por_texto, pitch)
        for item in itens:
            print(f"[SELO] {item.nome}: qtd={item.quantidade}")
    return itens
