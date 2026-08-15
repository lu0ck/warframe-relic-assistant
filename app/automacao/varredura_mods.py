"""
Varredura contínua da grade de Mods (tela de Mods do jogo).

Roda numa QThread própria: captura a janela do jogo, recorta a área demarcada
pelo usuário (config `grade_mods`), roda o OCR na grade e emite a lista de mods
lidos nesta passada via signal `nomes`. A UI acumula e deduplica. O loop é
interrompível a qualquer momento por `parar()`.

O OCR roda aqui na thread (não na principal) pra não travar a UI a cada
passada — o PaddleOCR é criado lazy na primeira chamada dentro desta thread.
"""
import threading

from PySide6.QtCore import QThread, Signal

from app import config
from app.captura.calibrar_mods import recortar_grade_mods
from app.captura.mods_ocr import reconhecer_itens_mods
from app.captura.screenshot import capturar_janela_do_jogo
from app.dados import cache


class VarreduraMods(QThread):
    nomes = Signal(object)  # list[ItemLido] desta passada
    erro = Signal(str)
    parada = Signal()

    def __init__(self, intervalo: float = 0.8, parent=None):
        super().__init__(parent)
        self._intervalo = max(0.3, intervalo)
        self._pedido_parada = threading.Event()

    def parar(self):
        """Pede a interrupção da varredura SEM bloquear a UI.

        O thread só confere o pedido entre passadas (o OCR atual termina antes),
        então encerra sozinho e emite `parada`. Quem precisa de sincronismo
        (fechamento da janela) chama `wait()` por conta própria.
        """
        self._pedido_parada.set()

    def run(self):
        self._pedido_parada.clear()
        nome_janela = cache.obter_config("nome_janela_jogo") or config.NOME_JANELA_JOGO
        avisou_sem_area = False
        avisou_sem_janela = False
        avisou_sem_precos = False

        while not self._pedido_parada.is_set():
            try:
                imagem, achou_janela = capturar_janela_do_jogo(nome_janela=nome_janela)
                if not achou_janela:
                    if not avisou_sem_janela:
                        self.erro.emit(
                            "Janela do Warframe não encontrada — capturando o "
                            "monitor inteiro (recortes provavelmente errados)."
                        )
                        avisou_sem_janela = True
                else:
                    avisou_sem_janela = False

                recorte, area = recortar_grade_mods(imagem)
                if area is None:
                    if not avisou_sem_area:
                        self.erro.emit(
                            "Configure a área da grade primeiro (botão "
                            "'Definir área da grade')."
                        )
                        avisou_sem_area = True
                    self._pedido_parada.wait(self._intervalo)
                    continue
                avisou_sem_area = False

                avisos = []
                itens = reconhecer_itens_mods(recorte, avisos=avisos)
                if itens:
                    avisou_sem_precos = False
                    self.nomes.emit(itens)
                elif avisos and not avisou_sem_precos:
                    # Tela/área não parece a grade de Offerings — avisa UMA
                    # vez (não pode spam por passada) até voltar a reconhecer.
                    self.erro.emit(avisos[0])
                    avisou_sem_precos = True
            except Exception as erro:
                self.erro.emit(f"Erro na varredura: {erro}")

            self._pedido_parada.wait(self._intervalo)

        self.parada.emit()
