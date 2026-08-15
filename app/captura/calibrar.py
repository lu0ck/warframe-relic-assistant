"""
Script de calibração — RODAR NA SUA MÁQUINA, com o Warframe aberto na tela
"Fenda do Void/Prêmios" (fim de missão com relíquia), antes de confiar no
reconhecimento automático.

Uso:
    python -m app.captura.calibrar                     # captura a janela do jogo agora
    python -m app.captura.calibrar --arquivo print.png  # usa uma imagem salva em vez de capturar

O que ele faz:
    1. Localiza a janela do Warframe (via xdotool) e mostra a geometria encontrada
    2. Captura só essa janela (ou o monitor inteiro, se não achar a janela)
    3. Recorta a faixa de nomes (FAIXA_NOMES_Y em app/config.py) e salva em
       calibracao/faixa_nomes.png — ABRA ESSE ARQIVO E CONFIRA se a faixa
       cobre os nomes dos itens sem cortar
    4. Roda o reconhecimento e mostra quantos itens achou e o texto de cada um

Se a faixa não estiver no lugar certo, ajuste FAIXA_NOMES_Y em
app/config.py (são frações de 0.0 a 1.0 da ALTURA DA JANELA DO JOGO, não da
tela inteira) e rode de novo até bater.
"""
import argparse
import sys
import time
from pathlib import Path

from PIL import Image

from app.captura.janela import encontrar_janela_do_jogo
from app.captura.screenshot import capturar_janela_do_jogo, recortar_faixa_dos_nomes
from app.captura.ocr import reconhecer_nomes_multiplos
from app.config import NOME_JANELA_JOGO


def main():
    parser = argparse.ArgumentParser(description="Calibra o recorte de tela do overlay")
    parser.add_argument("--arquivo", type=str, default=None, help="usar uma imagem salva em vez de capturar a tela")
    args = parser.parse_args()

    pasta_saida = Path("calibracao")
    pasta_saida.mkdir(exist_ok=True)

    if args.arquivo:
        imagem = Image.open(args.arquivo).convert("RGB")
        print(f"Usando imagem de arquivo: {args.arquivo} ({imagem.size[0]}x{imagem.size[1]})")
    else:
        geometria = encontrar_janela_do_jogo(NOME_JANELA_JOGO)
        if geometria:
            print(f"Janela '{NOME_JANELA_JOGO}' encontrada: {geometria}")
        else:
            print(
                f"AVISO: não achei uma janela chamada '{NOME_JANELA_JOGO}'. "
                f"Confirme que o jogo está aberto e que o 'xdotool' está instalado "
                f"(sudo apt install xdotool). Vou capturar o monitor inteiro como "
                f"alternativa, mas os recortes provavelmente vão sair errados."
            )
        print("Capturando em 3 segundos... deixe a tela 'Fenda do Void/Prêmios' visível!")
        time.sleep(3)
        imagem, achou = capturar_janela_do_jogo()
        print(f"Capturado ({'janela do jogo' if achou else 'monitor inteiro'}): {imagem.size[0]}x{imagem.size[1]}")

    imagem.save(pasta_saida / "captura_completa.png")

    faixa = recortar_faixa_dos_nomes(imagem)
    faixa.save(pasta_saida / "faixa_nomes.png")
    print(f"\nFaixa de nomes salva em: {pasta_saida / 'faixa_nomes.png'}")
    print("Abra esse arquivo e confira se os nomes dos itens aparecem inteiros, sem cortar.")

    nomes = reconhecer_nomes_multiplos(faixa)
    print(f"\n--- {len(nomes)} item(ns) reconhecido(s) ---")
    for i, nome in enumerate(nomes, start=1):
        print(f"  {i}. {nome!r}")

    if not nomes:
        print("\nNenhum item reconhecido. Provavelmente a faixa não está cobrindo o texto certo.")
    print("\nSe algo estiver errado, ajuste FAIXA_NOMES_Y em app/config.py (fração da altura da JANELA) e rode de novo.")


if __name__ == "__main__":
    sys.exit(main())
