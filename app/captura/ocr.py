"""
OCR da faixa de nomes.

Em vez de recortar colunas fixas (quebra com squad de tamanho variável, ou
se a janela do jogo não estiver exatamente onde eu previ), roda o OCR na
faixa inteira com dados de posição (`image_to_data`) e reconstrói os itens
em duas etapas:

  1. Agrupa palavras por LINHA (como o Tesseract já detecta), preservando a
     ordem de leitura dentro de cada linha — isso evita embaralhar palavras
     entre linhas diferentes (necessário porque nomes longos tipo
     "Akbronco Prime (Diagrama)" quebram em 2 linhas no jogo).
  2. Funde linhas cujo intervalo horizontal se sobrepõe — é a mesma etiqueta
     de item quebrada em 2 linhas. Linhas sem sobreposição horizontal são
     itens diferentes.

Funciona pra 1, 2, 3 ou 4 itens na tela sem precisar reconfigurar nada.

Pré-processamento:
  A tela de recompensa NÃO tem cores fixas (texto e fundo variam), então a
  mesma faixa passa por 1+ variantes de pré-processamento (todas terminando no
  MESMO upscale, pra não desalinhar as coordenadas) e o Tesseract roda em cada
  uma. A variante cujo resultado tem maior confiança média é a escolhida.
  A "base" roda sempre; se ela já estiver acima de CONFIANCA_PARADA, as outras
  nem são testadas (latência baixa no caso comum).
"""
from PIL import Image, ImageOps, ImageFilter, ImageChops
import pytesseract
from pytesseract import Output

from app.config import ESPACO_MINIMO_ENTRE_ITENS_PX

FATOR_UPSCALE = 4  # aumentar a imagem antes do OCR melhora muito a precisão em texto pequeno
CONFIANCA_MINIMA_PALAVRA = 10  # abaixo disso, o Tesseract normalmente está "vendo coisas"
MARGEM_SOBREPOSICAO_PX = 10  # tolerância (em pixels originais) pra considerar duas linhas "a mesma etiqueta"
PONTUACAO_DE_BORDA = ".,;:!?|[](){}\"'`/\\-_—–"  # lixo que o OCR gruda no começo/fim de uma palavra
MINIMO_ALFANUMERICOS = 3  # palavras de item reais nunca têm menos letras que isso
MAX_ITENS = 4  # no máximo 4 recompensas por abertura de relíquia (tamanho de squad)

# ---------------------------------------------------------------------------
# Tesseract
# ---------------------------------------------------------------------------
# ATENÇÃO: não usar `tessedit_char_whitelist` na config do Tesseract. Testado
# contra prints reais, o whitelist com espaço (obrigatório pra nomes compostos)
# faz o Tesseract ZERAR a confiança de palavras válidas (ex: "Alternox Prime
# Barrel" -> "Alternox" e "Barrel" com conf=0) e quebra a segmentação de
# palavras — resultado pior que sem whitelist. O mesmo objetivo é alcançado de
# forma segura no PÓS-processamento: cada palavra reconhecida é filtrada pro
# conjunto abaixo (`_filtro_whitelist`), então nada fora dele chega ao matching.
#
# PSM 6 (assuma um bloco uniforme de texto) é o certo aqui: a faixa tem 1 a 4
# itens, e cada nome pode quebrar em 2 linhas — PSM 7/13 (linha única)
# perderiam itens, PSM 8 (palavra única) quebraria nomes compostos.
CONFIG_TESSERACT = "--psm 6"

# Caracteres permitidos no resultado final. Além do conjunto pedido (letras,
# dígitos, espaço e .;,:[]), inclui `()` porque nomes reais os usam (ex:
# "Akbronco Prime (Diagrama)" quebra em 2 linhas no jogo).
CARACTERES_PERMITIDOS = (
    set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .;,:[]()")
)

# ---------------------------------------------------------------------------
# Pré-processamento
# ---------------------------------------------------------------------------
# Quais variantes testar (em ordem). "base" é sempre a primeira e é obrigatória.
# Adicionar "sharpen", "invertida", "otsu", "adaptativo" permite A/B testar
# sem mexer no restante do código.
VARIANTES_ATIVAS = ("base", "otsu")
# Se a melhor confiança média já passou disso, para de testar outras variantes
# (1 única passada do Tesseract no caso comum).
CONFIANCA_PARADA = 40


def _grayscale(imagem: Image.Image) -> Image.Image:
    return imagem.convert("L")


def _autocontraste(imagem: Image.Image) -> Image.Image:
    return ImageOps.autocontrast(imagem)


def _sharpen(imagem: Image.Image) -> Image.Image:
    """Nitidez LEVE — melhora as bordas sem criar artefatos."""
    return imagem.filter(ImageFilter.UnsharpMask(radius=1, percent=80, threshold=2))


def _remover_ruido(imagem: Image.Image) -> Image.Image:
    """Redução de ruído leve, preservando as bordas das letras."""
    return imagem.filter(ImageFilter.MedianFilter(3))


def _otsu(imagem: Image.Image) -> Image.Image:
    """Binarização Otsu em Python puro (sem numpy, sem deps novas).

    Acha o threshold que maximiza a variância entre classes a partir do
    histograma — funciona com fundo de qualquer cor, sem assumir cor fixa.
    """
    hist = imagem.histogram()
    total = imagem.width * imagem.height
    soma_total = sum(i * h for i, h in enumerate(hist))
    soma_b = 0.0
    w_b = 0
    max_var = -1.0
    threshold = 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        soma_b += t * hist[t]
        m_b = soma_b / w_b
        m_f = (soma_total - soma_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > max_var:
            max_var = var
            threshold = t
    return imagem.point(lambda p: 255 if p > threshold else 0)


def _adaptativo(imagem: Image.Image, raio: int = 8, c: int = 10) -> Image.Image:
    """Binarização adaptativa aproximada: média local via BoxBlur.

    A diferença (pixel - média local) é limiarizada — robusta a iluminação
    que varia dentro da própria faixa.
    """
    blur = imagem.filter(ImageFilter.BoxBlur(raio))
    diferenca = ImageChops.subtract(imagem, blur)
    return diferenca.point(lambda v: 255 if v > c else 0)


def _inverter(imagem: Image.Image) -> Image.Image:
    return ImageOps.invert(imagem)


def _upscale(imagem: Image.Image) -> Image.Image:
    return imagem.resize(
        (imagem.width * FATOR_UPSCALE, imagem.height * FATOR_UPSCALE),
        Image.LANCZOS,
    )


def _preparar_variante(faixa: Image.Image, nome: str) -> Image.Image:
    """Monta a imagem final de uma variante.

    Todas as variantes passam pela base (grayscale + autocontraste + upscale)
    e terminam no MESMO tamanho — as coordenadas das palavras batem com as
    constantes de agrupamento, que multiplicam por FATOR_UPSCALE.
    """
    base = _upscale(_autocontraste(_grayscale(faixa)))
    if nome == "base":
        return base
    if nome == "sharpen":
        return _sharpen(base)
    if nome == "otsu":
        # binariza na imagem ORIGINAL (antes do upscale): o threshold pega a
        # distribuição real de cinza, e o upscale depois não "inventa" tons
        return _upscale(_otsu(_autocontraste(_grayscale(faixa))))
    if nome == "adaptativo":
        return _upscale(_adaptativo(_autocontraste(_grayscale(faixa))))
    if nome == "invertida":
        return _inverter(base)
    if nome == "ruido":
        return _upscale(_remover_ruido(_autocontraste(_grayscale(faixa))))
    return base


def preprocessar(imagem: Image.Image) -> Image.Image:
    """Pré-processamento padrão (mantido pra compatibilidade)."""
    return _preparar_variante(imagem, "base")


def _intervalos_se_sobrepoem(x0_a: int, x1_a: int, x0_b: int, x1_b: int, margem: int) -> bool:
    return not (x1_b < x0_a - margem or x0_b > x1_a + margem)


def _filtro_whitelist(texto: str) -> str:
    """Remove caracteres fora do conjunto permitido de um texto reconhecido.

    Faz o papel da whitelist do Tesseract no pós-processamento (mais seguro,
    ver nota no CONFIG_TESSERACT): o resultado final nunca carrega caracteres
    que não podem aparecer num nome de item. Espaços são preservados; a borda
    já é limpa por PONTUACAO_DE_BORDA antes.
    """
    return "".join(c for c in texto if c in CARACTERES_PERMITIDOS)


def _escore_confianca(dados: dict) -> float:
    """Confiança média das palavras que passariam no filtro de itens.

    Usado pra comparar variantes de pré-processamento e escolher a melhor
    antes de reconstruir os itens.
    """
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


def _reconstruir_itens(dados: dict) -> list[str]:
    """Reconstrói os nomes dos itens a partir do image_to_data (lógica atual)."""
    # Etapa 1: agrupa palavras por linha detectada pelo Tesseract. Atenção: o
    # Tesseract junta numa linha só tudo que está no mesmo nível vertical,
    # mesmo que sejam itens diferentes lado a lado — por isso a etapa 2
    # separa por espaço horizontal DENTRO de cada linha primeiro.
    linhas: dict[tuple[int, int], list[tuple[int, int, int, str]]] = {}
    for i, texto in enumerate(dados["text"]):
        texto = texto.strip(PONTUACAO_DE_BORDA).strip()
        if not texto or int(dados["conf"][i]) < CONFIANCA_MINIMA_PALAVRA:
            continue
        if sum(1 for c in texto if c.isalnum()) < MINIMO_ALFANUMERICOS:
            continue  # descarta fragmentos tipo "x", "ee", "a", "ox" (nunca são item)
        chave = (dados["block_num"][i], dados["line_num"][i])
        x0 = dados["left"][i]
        x1 = x0 + dados["width"][i]
        y0 = dados["top"][i]
        linhas.setdefault(chave, []).append((x0, x1, y0, texto))

    if not linhas:
        return []

    espaco_minimo_px = ESPACO_MINIMO_ENTRE_ITENS_PX * FATOR_UPSCALE

    # Etapa 2: dentro de cada linha, separa por espaço horizontal grande —
    # isso já resolve o caso de vários itens de 1 linha só na mesma altura.
    grupos_linha = []
    for palavras in linhas.values():
        palavras.sort(key=lambda p: p[0])  # ordem de leitura da esquerda pra direita
        subgrupo: list[tuple[int, int, int, str]] = []
        fim_anterior = None
        for x0, x1, y0, texto in palavras:
            if fim_anterior is not None and (x0 - fim_anterior) > espaco_minimo_px:
                grupos_linha.append(subgrupo)
                subgrupo = []
            subgrupo.append((x0, x1, y0, texto))
            fim_anterior = x1
        if subgrupo:
            grupos_linha.append(subgrupo)

    blocos = [{
        "x0": min(p[0] for p in sub),
        "x1": max(p[1] for p in sub),
        "y0": min(p[2] for p in sub),
        "texto": " ".join(p[3] for p in sub),
    } for sub in grupos_linha]
    blocos.sort(key=lambda b: b["x0"])

    # Etapa 3: funde blocos (de linhas diferentes) cujo intervalo horizontal
    # se sobrepõe — é a mesma etiqueta de item quebrada em 2 linhas.
    margem_px = MARGEM_SOBREPOSICAO_PX * FATOR_UPSCALE
    itens: list[dict] = []
    for bloco in blocos:
        item_encontrado = None
        for item in itens:
            if _intervalos_se_sobrepoem(item["x0"], item["x1"], bloco["x0"], bloco["x1"], margem_px):
                item_encontrado = item
                break
        if item_encontrado is not None:
            item_encontrado["x0"] = min(item_encontrado["x0"], bloco["x0"])
            item_encontrado["x1"] = max(item_encontrado["x1"], bloco["x1"])
            item_encontrado["blocos"].append(bloco)
        else:
            itens.append({"x0": bloco["x0"], "x1": bloco["x1"], "blocos": [bloco]})

    itens.sort(key=lambda item: item["x0"])

    resultado = []
    for item in itens:
        blocos_ordenados = sorted(item["blocos"], key=lambda b: b["y0"])
        texto_item = " ".join(b["texto"] for b in blocos_ordenados)
        # Whitelist no pós-processamento: garante que só caracteres válidos
        # chegam ao matching, sem mexer na confiança do Tesseract.
        texto_item = _filtro_whitelist(texto_item)
        # grupos que sobraram como fragmento curto puro (ex: "Pe J") não são item
        if sum(1 for c in texto_item if c.isalnum()) < MINIMO_ALFANUMERICOS + 1:
            continue
        resultado.append(texto_item)

    # Nunca mais que MAX_ITENS por tela: fragmentos de um nome que o OCR
    # separou errado não podem virar "opções extras". Descarta os candidatos
    # mais fracos (menos caracteres alfanuméricos) e preserva a ordem de
    # leitura (esquerda → direita) dos que ficaram.
    if len(resultado) > MAX_ITENS:
        indices = sorted(
            range(len(resultado)),
            key=lambda i: sum(1 for c in resultado[i] if c.isalnum()),
            reverse=True,
        )[:MAX_ITENS]
        indices.sort()
        resultado = [resultado[i] for i in indices]
    return resultado


def _reconhecer_tesseract(faixa: Image.Image) -> list[str]:
    """Motor Tesseract: reconhece os nomes da faixa (lógica original).

    Roda as variantes de pré-processamento em ordem e fica com a de maior
    confiança média. Parada antecipada quando a primeira já é boa.
    """
    melhor_dados = None
    melhor_escore = -1.0
    for nome_variante in VARIANTES_ATIVAS:
        imagem_preparada = _preparar_variante(faixa, nome_variante)
        dados = pytesseract.image_to_data(
            imagem_preparada, config=CONFIG_TESSERACT, output_type=Output.DICT
        )
        escore = _escore_confianca(dados)
        if escore > melhor_escore:
            melhor_escore = escore
            melhor_dados = dados
        if escore >= CONFIANCA_PARADA:
            break

    if melhor_dados is None:
        return []
    return _reconstruir_itens(melhor_dados)


def reconhecer_nomes_multiplos(faixa: Image.Image) -> list[str]:
    """Recebe a faixa inteira de nomes e devolve uma lista de textos, um por item detectado.

    Despachante de motor: usa o PaddleOCR por padrão (config.MOTOR_OCR), com o
    Tesseract disponível via env MOTOR_OCR=tesseract pra A/B. O import do
    paddle é feito aqui dentro (lazy) pra o app continuar abrindo mesmo se o
    paddle não estiver instalado.
    """
    from app.config import MOTOR_OCR

    if MOTOR_OCR == "paddle":
        from app.captura.ocr_paddle import reconhecer_com_paddle

        return reconhecer_com_paddle(faixa)
    return _reconhecer_tesseract(faixa)
