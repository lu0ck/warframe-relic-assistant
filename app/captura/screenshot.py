"""
Captura de tela e recorte da faixa de nomes dos itens.

Usa `mss` (rápido, focado só em screenshot). Sempre que possível, captura só
a JANELA DO JOGO (localizada via app/captura/janela.py), não o monitor
inteiro — o jogo roda em janela, então recortar por % do monitor pega o
lugar errado se a janela não ocupa a tela toda ou não está no canto (0,0).
Se a janela não for encontrada (xdotool ausente, jogo fechado, etc.), cai
pro fallback de capturar o monitor inteiro.
"""
from datetime import datetime
from pathlib import Path

from PIL import Image
import mss

from app.config import NOME_JANELA_JOGO, PADRAO_PASTA_PRINTS, obter_faixa_nomes_y
from app.captura.janela import encontrar_janela_do_jogo


def capturar_monitor(indice_monitor: int = 1) -> Image.Image:
    """
    Fallback: captura o monitor inteiro. No mss, o índice 0 é "todos os
    monitores combinados"; os monitores reais começam em 1.
    """
    with mss.mss() as sct:
        if not (0 <= indice_monitor < len(sct.monitors)):
            indice_monitor = 1
        monitor = sct.monitors[indice_monitor]
        screenshot = sct.grab(monitor)
        return Image.frombytes("RGB", screenshot.size, screenshot.rgb)


def capturar_janela_do_jogo(
    indice_monitor_fallback: int = 1,
    nome_janela: str | None = None,
) -> tuple[Image.Image, bool]:
    """
    Tenta capturar só a janela do jogo. Retorna (imagem, achou_janela) —
    achou_janela=False significa que caiu no fallback de monitor inteiro,
    então as % de recorte podem não bater se o jogo não estiver ocupando a
    tela toda.
    """
    nome_janela = nome_janela or NOME_JANELA_JOGO
    geometria = encontrar_janela_do_jogo(nome_janela)
    with mss.mss() as sct:
        if geometria is not None:
            try:
                # mss.monitors[0] é a área combinada de todos os monitores.
                # A janela pode estar parcialmente fora dela (ex: monitor em
                # posição não-trivial), e pedir um recorte que extrapola o
                # desktop virtual faz o X11 estourar com "BadMatch".
                virtual = sct.monitors[0]
                regiao = {
                    "left": max(geometria["left"], virtual["left"]),
                    "top": max(geometria["top"], virtual["top"]),
                    "width": max(
                        0,
                        min(
                            geometria["width"],
                            virtual["width"] - (geometria["left"] - virtual["left"]),
                        ),
                    ),
                    "height": max(
                        0,
                        min(
                            geometria["height"],
                            virtual["height"] - (geometria["top"] - virtual["top"]),
                        ),
                    ),
                }
                screenshot = sct.grab(regiao)
                return Image.frombytes("RGB", screenshot.size, screenshot.rgb), True
            except Exception as erro:
                print(
                    f"Aviso: falha ao capturar a janela do jogo ({erro}). "
                    f"Usando o monitor inteiro."
                )

        if not (0 <= indice_monitor_fallback < len(sct.monitors)):
            indice_monitor_fallback = 1
        monitor = sct.monitors[indice_monitor_fallback]
        screenshot = sct.grab(monitor)
        return Image.frombytes("RGB", screenshot.size, screenshot.rgb), False


def recortar_faixa_dos_nomes(imagem: Image.Image) -> Image.Image:
    """Recebe a imagem da janela/tela do jogo e devolve só a faixa onde ficam os nomes.

    Usa a faixa salva pelo calibrador visual (app/captura/calibrar_gui.py),
    se houver; senão a faixa interpolada pra proporção desta imagem.
    """
    largura, altura = imagem.size
    y0, y1 = obter_faixa_nomes_y(largura / altura)
    return imagem.crop((0, int(altura * y0), largura, int(altura * y1)))


def salvar_print_captura(imagem: Image.Image) -> str | None:
    """Salva a imagem da captura numa pasta com data/hora no nome.

    A pasta vem da configuração `pasta_prints` (escolhida nas Configurações);
    se não estiver configurada, usa PADRAO_PASTA_PRINTS. A pasta é criada se
    não existir. O nome do arquivo leva a data/hora com milissegundos, então
    capturas no mesmo segundo não se sobrescrevem.

    Devolve o caminho salvo, ou None se algo falhar (nunca lança — o print é
    acessório e não pode derrubar a captura/OCR).
    """
    try:
        from app.dados import cache

        pasta_texto = cache.obter_config("pasta_prints")
        pasta = Path(pasta_texto) if pasta_texto else PADRAO_PASTA_PRINTS
        pasta = pasta.expanduser()
        pasta.mkdir(parents=True, exist_ok=True)

        carimbo = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        caminho = pasta / f"reliquias_{carimbo}.png"
        imagem.save(caminho)
        return str(caminho)
    except Exception as erro:
        print(f"Aviso: não foi possível salvar o print da captura ({erro}).")
        return None
