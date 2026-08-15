"""
Aba 3 — Calibração da faixa de nomes, dentro do próprio app.

Reaproveita o PainelCalibracao de app/captura/calibrar_gui.py. O botão
"Capturar janela do jogo agora" fotografa a janela do Warframe (com 3s de
espera pra você deixar a tela de recompensa visível) e abre o editor visual
da faixa — arrastar, testar o OCR e salvar.
"""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app import config
from app.captura.calibrar_gui import PainelCalibracao
from app.captura.screenshot import capturar_janela_do_jogo
from app.dados import cache
from app.ui import tema


class AbaCalibracao(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._painel: PainelCalibracao | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        titulo = QLabel("Calibração da faixa de nomes")
        titulo.setProperty("data-role", "titulo")
        layout.addWidget(titulo)

        instrucoes = QLabel(
            "O app recorta uma faixa horizontal da tela de recompensa pra ler "
            "os nomes dos itens. Se os nomes não estiverem sendo lidos, ajuste "
            "a faixa aqui.\n\n"
            "1. Deixe o Warframe aberto na tela 'Fenda do Void/Prêmios'.\n"
            "2. Clique em 'Capturar janela do jogo' (3s pra posicionar).\n"
            "3. Arraste a faixa azul em cima dos nomes até o OCR ler certo.\n"
            "4. Salve — o overlay passa a usar na hora, sem reiniciar."
        )
        instrucoes.setWordWrap(True)
        instrucoes.setStyleSheet(f"color: {tema.COR_TEXTO_SECUNDARIO};")
        layout.addWidget(instrucoes)

        self._rotulo_status = QLabel(
            f"Faixa salva (calibrada na última janela usada): {self._faixa_atual_descricao()}. "
            "Ela muda conforme o tamanho da janela do jogo — se o OCR não ler nada,"
            " recapture aqui."
        )
        self._rotulo_status.setWordWrap(True)
        self._rotulo_status.setStyleSheet(
            f"color: {tema.COR_TEXTO_SECUNDARIO}; "
            f"background: {tema.COR_FUNDO_CARTAO}; "
            f"border: 1px solid {tema.COR_DIVISORIA}; "
            "border-radius: 6px; padding: 10px 14px; margin-top: 4px;"
        )
        layout.addWidget(self._rotulo_status)

        self._botao_capturar = QPushButton("Capturar janela do jogo agora")
        self._botao_capturar.setProperty("role", "primario")
        self._botao_capturar.clicked.connect(self._capturar_agora)
        layout.addWidget(self._botao_capturar)

    def _faixa_atual_descricao(self) -> str:
        y0, y1 = config.obter_faixa_nomes_y()
        return f"y {y0:.4f}..{y1:.4f}"

    def _capturar_agora(self):
        self._botao_capturar.setEnabled(False)
        self._rotulo_status.setText(
            "Capturando em 3 segundos... deixe a tela 'Fenda do Void/Prêmios' visível!"
        )
        QTimer.singleShot(3000, self._executar_captura)

    def _executar_captura(self):
        nome_janela = cache.obter_config("nome_janela_jogo") or config.NOME_JANELA_JOGO
        imagem, achou_janela = capturar_janela_do_jogo(nome_janela=nome_janela)
        origem = "janela do jogo" if achou_janela else "MONITOR inteiro (janela do jogo não encontrada)"
        self._rotulo_status.setText(
            f"Capturado ({origem}): {imagem.size[0]}x{imagem.size[1]}"
        )

        if self._painel is None:
            self._painel = PainelCalibracao(imagem, achou_janela=achou_janela)
            self.layout().addWidget(self._painel, 1)
        else:
            self._painel.definir_imagem(imagem, achou_janela=achou_janela)
        self._botao_capturar.setEnabled(True)
