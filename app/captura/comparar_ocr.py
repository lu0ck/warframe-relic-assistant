"""
Comparador A/B Tesseract vs PaddleOCR nos prints reais.

Uso:
    python -m app.captura.comparar_ocr [caminho_de_um_print]

Sem argumento, roda em todos os prints de dados_locais/prints/. Imprime uma
tabela `arquivo | Tesseract | Paddle | conf. Paddle` com os itens reconhecidos
por cada motor e o tempo de cada passada.
"""
import glob
import sys
import time

from PIL import Image

from app.captura.ocr import _reconhecer_tesseract
from app.captura.screenshot import recortar_faixa_dos_nomes


def _nome_resumido(caminho: str) -> str:
    return caminho.split("/")[-1].replace(".png", "")


def medir_motor(fn, faixa):
    t0 = time.time()
    itens = fn(faixa)
    decorrido = time.time() - t0
    return itens, decorrido


def main():
    argumentos = sys.argv[1:]
    prints = argumentos or sorted(glob.glob("dados_locais/prints/*.png"))
    if not prints:
        print("Nenhum print encontrado em dados_locais/prints/")
        return 1

    for caminho in prints:
        imagem = Image.open(caminho).convert("RGB")
        faixa = recortar_faixa_dos_nomes(imagem)
        itens_tess, tempo_tess = medir_motor(_reconhecer_tesseract, faixa)
        itens_paddle, tempo_paddle = medir_motor(_reconhecer_com_paddle, faixa)

        print(f"\n=== {_nome_resumido(caminho)} ===")
        print(f"  Tesseract ({tempo_tess:.2f}s):")
        for item in itens_tess:
            print(f"    - {item}")
        print(f"  Paddle    ({tempo_paddle:.2f}s):")
        for item in itens_paddle:
            print(f"    - {item}")
    return 0


def _reconhecer_com_paddle(faixa):
    from app.captura.ocr_paddle import reconhecer_com_paddle

    return reconhecer_com_paddle(faixa)


if __name__ == "__main__":
    sys.exit(main())
