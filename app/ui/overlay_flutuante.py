from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from app.modelos import OpcaoRecompensa
from app.ui import tema
from app.ui.card_opcao import CardOpcao


class OverlayFlutuante(QWidget):
    """
    Janela sem borda, sempre no topo, transparente, mostrada no monitor
    secundário com os 4 cards de opção. Fecha sozinha depois de alguns
    segundos, ou se o usuário clicar num card / apertar ESC.
    """
    item_escolhido = Signal(object)  # emite o OpcaoRecompensa clicado
    fechado = Signal()

    def __init__(
        self,
        opcoes: list[OpcaoRecompensa],
        indice_monitor: int = 1,
        duracao_segundos: int = 12,
        y_frac: float = 0.5,
        parent=None,
    ):
        super().__init__(parent)
        self._opcoes = opcoes
        self._y_frac = y_frac

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        layout_geral = QVBoxLayout(self)
        layout_geral.setContentsMargins(12, 12, 12, 12)
        layout_geral.setSpacing(8)

        melhor = next((o for o in opcoes if o.e_melhor), None)
        if melhor:
            titulo_texto = f"MELHOR ESCOLHA  —  {melhor.nome}"
        else:
            titulo_texto = "Nenhuma opção reconhecida com confiança"
        titulo = QLabel(titulo_texto)
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titulo.setStyleSheet(
            f"color: {tema.COR_TEXTO}; "
            f"font-size: {tema.FONTE_CORPO}; font-weight: 600; "
            "background-color: rgba(10, 12, 20, 220); "
            "border: 1px solid rgba(54, 197, 214, 0.25); "
            "border-radius: 6px; padding: 6px 12px;"
        )
        layout_geral.addWidget(titulo)

        linha_cards = QHBoxLayout()
        linha_cards.setSpacing(14)
        for opcao in opcoes:
            card = CardOpcao(opcao)
            card.clicado.connect(self._ao_clicar_card)
            linha_cards.addWidget(card)
        layout_geral.addLayout(linha_cards)

        self._posicionar_no_monitor(indice_monitor)

        self._efeito_opacidade = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._efeito_opacidade)
        self._animacao_entrada = QPropertyAnimation(self._efeito_opacidade, b"opacity")
        self._animacao_entrada.setDuration(280)
        self._animacao_entrada.setStartValue(0.0)
        self._animacao_entrada.setEndValue(1.0)
        self._animacao_entrada.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._timer_fechamento = QTimer(self)
        self._timer_fechamento.setSingleShot(True)
        self._timer_fechamento.timeout.connect(self.close)
        self._duracao_ms = duracao_segundos * 1000

    def _posicionar_no_monitor(self, indice_monitor: int):
        telas = QGuiApplication.screens()
        if indice_monitor >= len(telas):
            indice_monitor = 0  # fallback seguro se o monitor configurado não existir
        geometria = telas[indice_monitor].geometry()

        self.adjustSize()
        x = geometria.x() + (geometria.width() - self.width()) // 2
        if hasattr(self, '_y_frac') and self._y_frac is not None:
            y = geometria.y() + int(geometria.height() * self._y_frac)
        else:
            y = geometria.y() + (geometria.height() - self.height()) // 2
        self.move(max(x, geometria.x()), max(y, geometria.y()))

    def _ao_clicar_card(self, opcao: OpcaoRecompensa):
        self.item_escolhido.emit(opcao)
        self.close()

    def showEvent(self, evento):
        super().showEvent(evento)
        self._animacao_entrada.start()
        self._timer_fechamento.start(self._duracao_ms)

    def keyPressEvent(self, evento):
        if evento.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(evento)

    def closeEvent(self, evento):
        self.fechado.emit()
        super().closeEvent(evento)
