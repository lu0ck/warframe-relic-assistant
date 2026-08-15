"""
Motor PaddleOCR pra faixa de nomes (substitui o Tesseract no fluxo).

Diferente do Tesseract, o Paddle recebe a faixa SEM upscale (fator 1): o
modelo PP-OCRv5 já lida bem com texto pequeno, e até renderiza melhor sem a
imagem interpolada. O pré-processamento fica só em grayscale + autocontraste,
mantendo as coordenadas originais — assim as constantes de agrupamento
(ESPACO_MINIMO_ENTRE_ITENS_PX, MARGEM_SOBREPOSICAO_PX) se aplicam direto, sem
multiplicar por fator de upscale.

Reconstrução de itens: o detector do Paddle agrupa TODO o texto de uma mesma
linha num único box (ex: "Fang Prime Handle Perigale Prime Receiver" numa
caixa só), então pedimos `return_word_box=True` (caixas por palavra) e
replicamos a lógica do Tesseract: agrupar palavras por gap horizontal grande
(> ESPACO_MINIMO_ENTRE_ITENS_PX) e fundir blocos de linhas diferentes cujo
intervalo horizontal se sobrepõe (nome quebrado em 2 linhas no jogo).

DEBUG_OCR=1: salva a faixa original e a pré-processada em dados_locais/debug/
e imprime no terminal o texto e a confiança de cada item reconhecido.
"""
from PIL import Image, ImageOps
import locale
import numpy as np

from app.config import (
    DEBUG_OCR,
    ESPACO_MINIMO_ENTRE_ITENS_PX,
    MOTOR_OCR,
    PASTA_DADOS,
)
from app.captura.ocr import (
    MARGEM_SOBREPOSICAO_PX,
    MAX_ITENS,
    MINIMO_ALFANUMERICOS,
    PONTUACAO_DE_BORDA,
    _filtro_whitelist,
    _grayscale,
    _intervalos_se_sobrepoem,
)

# Confiança mínima por linha detectada (0..1). Valores reais ficam ~0.97;
# abaixo disso o Paddle normalmente "viu coisas" ou texto de UI atravessado.
PADDLE_CONFIANCA_MINIMA = 0.6

# Nome dos modelos mobile do PaddleOCR 3.7.0 (baixados automaticamente no
# primeiro uso, salvos em ~/.paddlex/official_models/).
MODELO_DETECCAO = "PP-OCRv5_mobile_det"
MODELO_RECONHECIMENTO = "PP-OCRv5_mobile_rec"

_ocr = None


def _garantir_locale_numerico_c():
    """Qt instancia QApplication com setlocale(LC_ALL, pt_BR) (usuário BR);
    com LC_NUMERIC pt_BR o strtod("0.8") do protobuf do paddle falha na hora de
    carregar os protos (separador decimal é vírgula). Força LC_NUMERIC=C.
    """
    if locale.setlocale(locale.LC_NUMERIC, None) != "C":
        try:
            locale.setlocale(locale.LC_NUMERIC, "C")
        except locale.Error:
            pass


def _obter_ocr():
    """Singleton lazy do PaddleOCR (criação é cara: carrega os modelos)."""
    global _ocr
    if _ocr is None:
        _garantir_locale_numerico_c()
        from paddleocr import PaddleOCR

        # enable_mkldnn=False é obrigatório: com oneDNN ligado o PaddlePaddle
        # 3.3.1 quebra com NotImplementedError no PIR (see onednn_instruction).
        _ocr = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_detection_model_name=MODELO_DETECCAO,
            text_recognition_model_name=MODELO_RECONHECIMENTO,
            enable_mkldnn=False,
        )
    return _ocr


def _preparar_faixa(faixa: Image.Image) -> Image.Image:
    """Pré-processamento do Paddle: grayscale + autocontraste, SEM upscale."""
    return _autocontraste(_grayscale(faixa))


def _autocontraste(imagem: Image.Image) -> Image.Image:
    return ImageOps.autocontrast(imagem)


def _salvar_debug(faixa_original: Image.Image, faixa_preparada: Image.Image):
    """DEBUG: salva as imagens da faixa e o estado do motor pra inspeção."""
    if not DEBUG_OCR:
        return
    pasta = PASTA_DADOS / "debug"
    pasta.mkdir(parents=True, exist_ok=True)
    faixa_original.convert("RGB").save(pasta / "faixa_original.png")
    faixa_preparada.convert("RGB").save(pasta / "faixa_preprocessada.png")


def _imprimir_resultados(resultado):
    """DEBUG: imprime no terminal o texto e a confiança de cada item."""
    if not DEBUG_OCR:
        return
    print(f"[OCR] motor={MOTOR_OCR}")
    for texto, confianca in resultado:
        print(f"[OCR]   conf={confianca:.2f}  {texto!r}")


def _reconstruir_itens_paddle(resultado: dict) -> list[str]:
    """Reconstrói os nomes a partir das caixas de palavra do Paddle.

    Etapa 1: dentro de cada linha detectada, separa por gap horizontal grande
    (varias itens lado a lado no mesmo nível vertical).
    Etapa 2: funde blocos de linhas diferentes com sobreposição horizontal
    (a mesma etiqueta quebrada em 2 linhas no jogo).
    """
    espaco_minimo_px = ESPACO_MINIMO_ENTRE_ITENS_PX  # fator 1: coords originais
    blocos = []

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
            palavras_filtradas.append((x0, x1, y0, texto))

        palavras_filtradas.sort(key=lambda p: p[0])
        subgrupo = []
        fim_anterior = None
        for x0, x1, y0, texto in palavras_filtradas:
            if fim_anterior is not None and (x0 - fim_anterior) > espaco_minimo_px:
                blocos.append(subgrupo)
                subgrupo = []
            subgrupo.append((x0, x1, y0, texto))
            fim_anterior = x1
        if subgrupo:
            blocos.append(subgrupo)

    blocos_flat = [{
        "x0": min(p[0] for p in sub),
        "x1": max(p[1] for p in sub),
        "y0": min(p[2] for p in sub),
        "texto": " ".join(p[3] for p in sub),
    } for sub in blocos]
    blocos_flat.sort(key=lambda b: b["x0"])

    itens: list[dict] = []
    for bloco in blocos_flat:
        item_encontrado = None
        for item in itens:
            if _intervalos_se_sobrepoem(
                item["x0"], item["x1"], bloco["x0"], bloco["x1"], MARGEM_SOBREPOSICAO_PX
            ):
                item_encontrado = item
                break
        if item_encontrado is not None:
            item_encontrado["x0"] = min(item_encontrado["x0"], bloco["x0"])
            item_encontrado["x1"] = max(item_encontrado["x1"], bloco["x1"])
            item_encontrado["blocos"].append(bloco)
        else:
            itens.append({"x0": bloco["x0"], "x1": bloco["x1"], "blocos": [bloco]})

    itens.sort(key=lambda item: item["x0"])

    resultado_itens = []
    for item in itens:
        blocos_ordenados = sorted(item["blocos"], key=lambda b: b["y0"])
        texto_item = " ".join(b["texto"] for b in blocos_ordenados)
        texto_item = _filtro_whitelist(texto_item)
        if sum(1 for c in texto_item if c.isalnum()) < MINIMO_ALFANUMERICOS + 1:
            continue
        resultado_itens.append(texto_item)

    if len(resultado_itens) > MAX_ITENS:
        indices = sorted(
            range(len(resultado_itens)),
            key=lambda i: sum(1 for c in resultado_itens[i] if c.isalnum()),
            reverse=True,
        )[:MAX_ITENS]
        indices.sort()
        resultado_itens = [resultado_itens[i] for i in indices]
    return resultado_itens


def reconhecer_com_paddle(faixa: Image.Image) -> list[str]:
    """Reconhece os nomes da faixa com o PaddleOCR e devolve list[str].

    Retorna também (via DEBUG) o texto e a confiança de cada item no terminal
    e salva as imagens da faixa. Sempre devolve list[str], no mesmo formato do
    Tesseract, pra quem consome (fluxo_captura, calibrar) não mudar nada.
    """
    resultado = _resultado_bruto(faixa)
    itens = _reconstruir_itens_paddle(resultado)

    # Confiança média das linhas que geraram os itens (pra DEBUG e medição).
    conf_linhas = [
        float(c) for c in resultado.get("rec_scores", []) if c >= PADDLE_CONFIANCA_MINIMA
    ]
    confianca_media = sum(conf_linhas) / len(conf_linhas) if conf_linhas else 0.0
    _imprimir_resultados([(item, confianca_media) for item in itens])

    return itens


def _resultado_bruto(faixa: Image.Image, salvar_debug: bool = True) -> dict:
    """Roda o pré-processamento + inferência do Paddle e devolve o resultado
    BRUTO (linhas, palavras, caixas e confianças). Quem precisa de dados de
    posição além da faixa de nomes (ex.: a grade do inventário) consome aqui.

    `salvar_debug=False` é usado pra recortes de apoio (ex.: o selo de
    quantidade) que não devem sobrescrever os arquivos de debug da faixa."""
    faixa_preparada = _preparar_faixa(faixa)
    if salvar_debug:
        _salvar_debug(faixa, faixa_preparada)

    ocr = _obter_ocr()
    # O Paddle espera 3 canais (BGR); converte a L (grayscale) pra RGB
    # (3 canais iguais) antes de virar ndarray.
    return ocr.predict(
        np.array(faixa_preparada.convert("RGB")), return_word_box=True
    )[0]
