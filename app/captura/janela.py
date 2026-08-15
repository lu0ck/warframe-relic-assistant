"""
Localiza a janela do Warframe na tela pelo nome, e captura só ela — não o
monitor inteiro. Isso é importante porque o jogo roda em JANELA (não em
tela cheia), e a posição/tamanho da janela pode não ser a tela toda, então
recortar por % da tela inteira pega o lugar errado (foi exatamente o que
aconteceu na primeira tentativa).

Depende do `xdotool` (sudo apt install xdotool).
"""
import re
import subprocess


def _geometria_da_janela(id_janela: str) -> dict | None:
    try:
        saida_geometria = subprocess.check_output(
            ["xdotool", "getwindowgeometry", "--shell", id_janela],
            text=True, stderr=subprocess.DEVNULL,
        )
        valores = {}
        for linha in saida_geometria.strip().split("\n"):
            chave, _, valor = linha.partition("=")
            valores[chave] = valor
        return {
            "left": int(valores["X"]),
            "top": int(valores["Y"]),
            "width": int(valores["WIDTH"]),
            "height": int(valores["HEIGHT"]),
        }
    except (subprocess.CalledProcessError, FileNotFoundError, KeyError, ValueError):
        return None


def _buscar_ids_por_nome(padrao: str) -> list[str]:
    try:
        saida_busca = subprocess.check_output(
            ["xdotool", "search", "--name", padrao],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return saida_busca.split("\n") if saida_busca else []
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def _buscar_ids_por_classe(padrao: str) -> list[str]:
    try:
        saida_busca = subprocess.check_output(
            ["xdotool", "search", "--class", padrao],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return saida_busca.split("\n") if saida_busca else []
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def _geometria_utilizavel(geometria) -> bool:
    """Ignora janelas sem área de conteúdo real (ex: janelas minimizadas ou 1x1)."""
    return (
        geometria is not None
        and geometria["width"] > 100
        and geometria["height"] > 100
    )


def encontrar_janela_do_jogo(nome_janela: str = "Warframe") -> dict | None:
    """
    Retorna {'left', 'top', 'width', 'height'} em pixels da janela do jogo,
    ou None se não achou (jogo fechado, xdotool não instalado, etc — nesse
    caso o chamador deve cair pro fallback de capturar o monitor inteiro).

    O `xdotool search --name` casa SUBSTRING, então "Warframe" também acha
    terminais, editores e o próprio projeto (o caminho da pasta aparece no
    título). Por isso a busca é feita em duas camadas seguras:

      1. Nome EXATO (regex ancorada): a janela do jogo tem título "Warframe".
      2. WM_CLASS do jogo (via Proton/wine costuma ser "Warframe" ou
         "warframe.exe") — a classe não contém o caminho da pasta, então não
         existe o risco de pegar o README/terminal.

    Nada disso casa? Retorna None → o chamador captura o monitor inteiro em
    vez de arriscar pegar uma janela aleatória.
    """
    for id_janela in _buscar_ids_por_nome(f"^{re.escape(nome_janela)}$"):
        geometria = _geometria_da_janela(id_janela)
        if _geometria_utilizavel(geometria):
            return geometria

    for padrao_classe in (r"[Ww]arframe", r"[Ww]arframe\.exe"):
        for id_janela in _buscar_ids_por_classe(padrao_classe):
            geometria = _geometria_da_janela(id_janela)
            if _geometria_utilizavel(geometria):
                return geometria

    return None
