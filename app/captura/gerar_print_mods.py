"""
Gera um print SINTÉTICO da tela de Mods do Warframe (grade de cards) e salva
em PNG — útil pra validar o pipeline de OCR da aba Mods SEM abrir o jogo.

Uso:
    python -m app.captura.gerar_print_mods                # escreve data/debug/mods_grade_sintetico.png
    python -m app.captura.gerar_print_mods --saida x.png
    python -m app.captura.gerar_print_mods --reconhecer   # roda o OCR (lento: carrega o Paddle) e imprime o que leu

O layout segue o que o leitor de quantidade (mods_ocr._regiao_badge_mods)
espera: nome centralizado no card e o badge de quantidade no canto inferior
esquerdo, logo abaixo do nome. Quando um print real estiver disponível, rode
com DEBUG_OCR=1 pra conferir as janelas de busca (mods_grade_badges.png).
"""
import argparse

from PIL import Image, ImageDraw, ImageFont

from app.config import PASTA_DADOS

FONTE_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONTE_NORMAL = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# (nome do mod, quantidade no card) — nomes reais do jogo, quantidades variadas.
MODS = [
    ("Vitality", 5), ("Split Chamber", 2), ("Flow", 3), ("Serration", 1),
    ("Continuity", 4), ("Streamline", 2), ("Intensify", 6), ("Rage", 1),
    ("Hunter Adrenaline", 2), ("Blind Rage", 1), ("Narrow Minded", 3),
    ("Heavy Caliber", 2), ("Fleeting Expertise", 1), ("Overextended", 2),
    ("Transient Fortitude", 1), ("Primed Continuity", 1),
]

LARGURA, ALTURA = 1280, 720
COLUNAS, LINHAS = 4, 4
LARGURA_CARD, ALTURA_CARD = 280, 120
GAP = 40
MARGEM_X = (LARGURA - (COLUNAS * LARGURA_CARD + (COLUNAS - 1) * GAP)) // 2
TOPO = 90

COR_FUNDO = (22, 26, 36)
COR_CARD = (30, 36, 48)
COR_BORDA = (58, 68, 88)
COR_NOME = (230, 234, 240)
COR_BADGE = (28, 34, 46)
COR_BADGE_BORDA = (90, 100, 120)
COR_NUMERO = (255, 214, 107)


def _fonte(caminho: str, tamanho: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(caminho, tamanho)
    except OSError:
        return ImageFont.load_default()


def gerar_print(caminho: str) -> Image.Image:
    """Desenha a grade de mods e salva em `caminho`; devolve a imagem."""
    imagem = Image.new("RGB", (LARGURA, ALTURA), COR_FUNDO)
    desenho = ImageDraw.Draw(imagem)
    fonte_nome = _fonte(FONTE_BOLD, 22)
    fonte_numero = _fonte(FONTE_BOLD, 16)

    for indice, (nome, quantidade) in enumerate(MODS):
        linha, coluna = divmod(indice, COLUNAS)
        x = MARGEM_X + coluna * (LARGURA_CARD + GAP)
        y = TOPO + linha * (ALTURA_CARD + GAP)

        # Card
        desenho.rounded_rectangle(
            (x, y, x + LARGURA_CARD, y + ALTURA_CARD), radius=8, fill=COR_CARD,
            outline=COR_BORDA, width=2,
        )

        # Diamante de rank (canto superior esquerdo) — sem número, só forma.
        centro_d = (x + 16, y + 16)
        diamante = [
            (centro_d[0], centro_d[1] - 9),
            (centro_d[0] + 9, centro_d[1]),
            (centro_d[0], centro_d[1] + 9),
            (centro_d[0] - 9, centro_d[1]),
        ]
        desenho.polygon(diamante, fill=(150, 120, 40), outline=(110, 85, 25))

        # Nome do mod (centralizado, no terço superior do card)
        cx = x + LARGURA_CARD // 2
        desenho.text(
            (cx, y + 52), nome, font=fonte_nome, fill=COR_NOME, anchor="mm",
        )

        # Badge de quantidade (canto inferior esquerdo, logo abaixo do nome)
        bx, by, bw, bh = x + 12, y + ALTURA_CARD - 34, 52, 26
        desenho.rounded_rectangle((bx, by, bx + bw, by + bh), radius=6,
                                  fill=COR_BADGE, outline=COR_BADGE_BORDA, width=1)
        desenho.text((bx + bw // 2, by + bh // 2), str(quantidade),
                     font=fonte_numero, fill=COR_NUMERO, anchor="mm")

    imagem.save(caminho)
    return imagem


def _reconhecer(caminho: str):
    """Roda o pipeline real de OCR contra o print sintético (lento na 1ª vez)."""
    from app.captura.mods_ocr import reconhecer_itens_mods

    print(f"Rodando OCR em {caminho} (primeira carga do Paddle pode demorar)...")
    itens = reconhecer_itens_mods(Image.open(caminho))
    if not itens:
        print("Nenhum mod reconhecido. Confira se o cache de mods está populado "
              "(aba Overlay) e se o print ficou legível.")
        return
    print(f"{len(itens)} mod(s) reconhecido(s):")
    for item in itens:
        preco = f"{item.preco_plata:g}p" if item.preco_plata is not None else "sem preço"
        print(f"  {item.nome:<20} qtd {item.quantidade:<3} {preco}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", default=str(PASTA_DADOS / "debug" / "mods_grade_sintetico.png"))
    parser.add_argument("--reconhecer", action="store_true",
                        help="roda o OCR no print gerado e imprime o resultado")
    argumentos = parser.parse_args()

    caminho = argumentos.saida
    import os
    from pathlib import Path

    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    gerar_print(caminho)
    print(f"Print sintético salvo em {caminho} ({os.path.getsize(caminho)} bytes).")
    if argumentos.reconhecer:
        _reconhecer(caminho)


if __name__ == "__main__":
    main()
