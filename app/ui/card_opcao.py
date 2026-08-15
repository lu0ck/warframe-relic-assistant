from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal

from app.modelos import OpcaoRecompensa
from app.ui import tema


# Cards do overlay rodam em janela transparente separada (WA_TranslucentBackground),
# então não podem depender do QSS global. Cada um pinta direto via setStyleSheet
# usando os tokens de tema — assim tudo fica coeso (overlay e janela principal
# usam exatamente as mesmas cores/bordas).

ESTILO_CARD_NORMAL = f"""
    QFrame {{
        background-color: rgba(20, 24, 38, 235);
        border: 1px solid rgba(120, 130, 160, 120);
        border-radius: 12px;
    }}
    QFrame:hover {{
        background-color: rgba(26, 32, 48, 245);
        border: 1px solid {tema.COR_ACENTO};
    }}
"""

ESTILO_CARD_MELHOR = f"""
    QFrame {{
        background-color: rgba(20, 45, 30, 235);
        border: 1px solid {tema.COR_MELHOR};
        border-radius: 12px;
    }}
    QFrame:hover {{
        background-color: rgba(26, 55, 36, 245);
        border: 1px solid {tema.COR_MELHOR_HOVER};
    }}
"""

ESTILO_SELO_MELHOR = (
    f"color: {tema.COR_MELHOR}; font-weight: 700; "
    f"font-size: {tema.FONTE_PEQUENA}; "
    "letter-spacing: 1.5px;"
)

ESTILO_NOME = (
    f"color: {tema.COR_TEXTO}; font-weight: 600; "
    f"font-size: {tema.FONTE_SUBTITULO};"
)

ESTILO_PRECO = f"color: {tema.COR_PLATA}; font-size: {tema.FONTE_CORPO}; font-weight: 600;"
ESTILO_DUCADOS = f"color: {tema.COR_DUCADOS}; font-size: {tema.FONTE_PEQUENA};"


class CardOpcao(QFrame):
    clicado = Signal(object)  # emite o OpcaoRecompensa quando o usuário clica

    def __init__(self, opcao: OpcaoRecompensa, parent=None):
        super().__init__(parent)
        self._opcao = opcao
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(ESTILO_CARD_MELHOR if opcao.e_melhor else ESTILO_CARD_NORMAL)
        self.setMinimumWidth(180)
        self.setMinimumHeight(130)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)
        layout.setContentsMargins(14, 12, 14, 12)

        if opcao.e_melhor:
            selo = QLabel("● MELHOR ESCOLHA")
            selo.setStyleSheet(ESTILO_SELO_MELHOR)
            selo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(selo)

        nome = QLabel(opcao.nome)
        nome.setWordWrap(True)
        nome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nome.setStyleSheet(ESTILO_NOME)
        layout.addWidget(nome)

        preco_texto = f"{opcao.preco_plata:.0f}p" if opcao.preco_plata is not None else "sem preço"
        preco = QLabel(preco_texto)
        preco.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preco.setStyleSheet(ESTILO_PRECO)
        layout.addWidget(preco)

        if opcao.ducados is not None:
            ducados = QLabel(f"◆ {opcao.ducados} ducados")
            ducados.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ducados.setStyleSheet(ESTILO_DUCADOS)
            layout.addWidget(ducados)

    def mousePressEvent(self, evento):
        self.clicado.emit(self._opcao)
        super().mousePressEvent(evento)
