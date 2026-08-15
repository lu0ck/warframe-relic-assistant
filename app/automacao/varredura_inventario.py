"""
Varredura contínua da grade do inventário (tela de vendas/Inventory do jogo).

Roda numa QThread própria: captura a janela do jogo, recorta a área demarcada
pelo usuário (config `grade_inventario`), roda o OCR na grade e emite a lista
de itens lidos nesta passada via signal `nomes`. A UI acumula e deduplica. O
loop é interrompível a qualquer momento por `parar()`.

O OCR roda aqui na thread (não na principal) pra não travar a UI a cada
passada — o PaddleOCR é criado lazy na primeira chamada dentro desta thread.
"""
import threading

from PySide6.QtCore import QThread, Signal

from app import config
from app.captura.calibrar_inventario import recortar_grade_inventario
from app.captura.inventario_ocr import reconhecer_itens_inventario
from app.captura.screenshot import capturar_janela_do_jogo
from app.dados import cache


class VarreduraInventario(QThread):
    nomes = Signal(object)  # list[ItemLido] desta passada
    erro = Signal(str)
    parada = Signal()

    def __init__(self, intervalo: float = 1.0, parent=None):
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

                recorte, area = recortar_grade_inventario(imagem)
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

                itens = reconhecer_itens_inventario(recorte)
                if itens:
                    self.nomes.emit(itens)
            except Exception as erro:
                self.erro.emit(f"Erro na varredura: {erro}")

            self._pedido_parada.wait(self._intervalo)

        self.parada.emit()
