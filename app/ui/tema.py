"""
Tema visual central do app.

Tudo de cor/fonte/borda da UI vive aqui. Os widgets só referenciam os
tokens abaixo (QSS_BASE aplicado no QApplication inteiros + constantes
pra casos que precisam pintar à mão, como o overlay transparente).

Direção: dark "cyber/Warframe" — fundo quase-preto com leve tom azulado,
acento ciano, textos em cinza-claro. Cobre janela principal, abas, cards,
diálogo de venda e bandeja. O overlay flutuante usa as mesmas cores mas
precisa de fundo semi-transparente (próprios widgets pintam com
rgba(...) direto).
"""

# Paleta central — usada em QSS_BASE e nos pinceis já-cozidos por widget.
COR_FUNDO_JANELA = "#0b0e14"
COR_FUNDO_INPUT = "#11151f"
COR_FUNDO_CARTAO = "#141925"
COR_FUNDO_CARTAO_HOVER = "#1a2030"
COR_FUNDO_ALT = "#0e121a"
COR_DIVISORIA = "#1f2738"
COR_BORDA = "#25304a"
COR_BORDA_HOVER = "#3b4a6e"

COR_TEXTO = "#e6edf3"
COR_TEXTO_SECUNDARIO = "#8b95a7"
COR_TEXTO_MUTED = "#5c6678"

COR_ACENTO = "#36c5d6"        # ciano Warframe
COR_ACENTO_HOVER = "#5ad9e8"
COR_ACENTO_FRACO = "rgba(54, 197, 214, 0.15)"

COR_MELHOR = "#3fdb6e"        # verde "melhor escolha"
COR_MELHOR_HOVER = "#6ee88a"
COR_MELHOR_FRACO = "rgba(63, 219, 110, 0.12)"
COR_MELHOR_BORDA = "#56e0a0"

COR_PLATA = "#e6c36f"         # platina (amarelo)
COR_DUCADOS = "#6fb8e0"       # ducados (azul)
COR_ALERTA = "#e09a6f"        # laranja "consultando..."
COR_ERRO = "#e06f7a"

FONTE_FAMILIA = "Segoe UI, DejaVu Sans, sans-serif"
FONTE_TITULO = "20px"
FONTE_SUBTITULO = "15px"
FONTE_CORPO = "13px"
FONTE_PEQUENA = "11px"


# Stylesheet aplicado no QApplication.inteiriço — cobre QMainWindow,
# QWidget, QLabel, QPushButton, QLineEdit, QSpinBox, QDoubleSpinBox,
# QComboBox, QCheckBox, QTabWidget, QScrollArea, QFrame, QMenu.
QSS_BASE = f"""
* {{
    font-family: {FONTE_FAMILIA};
    font-size: {FONTE_CORPO};
    color: {COR_TEXTO};
}}

QMainWindow, QDialog, QWidget {{
    background-color: {COR_FUNDO_JANELA};
}}

QLabel {{
    background: transparent;
    color: {COR_TEXTO};
}}

/* ---------- Títulos ---------- */
QLabel[data-role="titulo"] {{
    font-size: {FONTE_TITULO};
    font-weight: 600;
    color: {COR_TEXTO};
}}
QLabel[data-role="subtitulo"] {{
    font-size: {FONTE_SUBTITULO};
    font-weight: 600;
    color: {COR_TEXTO};
}}

/* ---------- Botões ---------- */
QPushButton {{
    background-color: {COR_FUNDO_CARTAO};
    border: 1px solid {COR_BORDA};
    border-radius: 6px;
    padding: 7px 14px;
    color: {COR_TEXTO};
}}
QPushButton:hover {{
    background-color: {COR_FUNDO_CARTAO_HOVER};
    border: 1px solid {COR_BORDA_HOVER};
}}
QPushButton:pressed {{
    background-color: {COR_FUNDO_INPUT};
}}
QPushButton:disabled {{
    color: {COR_TEXTO_MUTED};
    background-color: {COR_FUNDO_ALT};
    border: 1px solid {COR_DIVISORIA};
}}
QPushButton[role="primario"] {{
    background-color: {COR_ACENTO_FRACO};
    border: 1px solid {COR_ACENTO};
    color: {COR_ACENTO_HOVER};
    font-weight: 600;
}}
QPushButton[role="primario"]:hover {{
    background-color: rgba(54, 197, 214, 0.22);
    border: 1px solid {COR_ACENTO_HOVER};
}}
QPushButton[role="perigo"] {{
    border: 1px solid rgba(224, 111, 122, 0.55);
    color: {COR_ERRO};
}}
QPushButton[role="perigo"]:hover {{
    background-color: rgba(224, 111, 122, 0.18);
}}

/* ---------- Inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {COR_FUNDO_INPUT};
    border: 1px solid {COR_BORDA};
    border-radius: 5px;
    padding: 6px 8px;
    selection-background-color: {COR_ACENTO};
    selection-color: #062028;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {COR_ACENTO};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 14px;
    background: transparent;
    border: none;
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background-color: {COR_FUNDO_INPUT};
    border: 1px solid {COR_BORDA_HOVER};
    selection-background-color: {COR_ACENTO_FRACO};
    selection-color: {COR_TEXTO};
    outline: 0;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {COR_BORDA_HOVER};
    border-radius: 3px;
    background: {COR_FUNDO_INPUT};
}}
QCheckBox::indicator:checked {{
    background: {COR_ACENTO};
    border: 1px solid {COR_ACENTO};
}}

/* ---------- Abas ---------- */
QTabWidget::pane {{
    border: 1px solid {COR_DIVISORIA};
    border-radius: 8px;
    top: -1px;
    background: {COR_FUNDO_ALT};
}}
QTabBar::tab {{
    background: transparent;
    color: {COR_TEXTO_SECUNDARIO};
    padding: 8px 18px;
    margin-right: 2px;
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:hover {{
    color: {COR_TEXTO};
    background: {COR_FUNDO_CARTAO};
}}
QTabBar::tab:selected {{
    color: {COR_ACENTO_HOVER};
    background: {COR_FUNDO_ALT};
    border: 1px solid {COR_DIVISORIA};
    border-bottom: 1px solid {COR_FUNDO_ALT};
    font-weight: 600;
}}

/* ---------- Cartões genéricos ---------- */
QFrame[role="cartao"] {{
    background-color: {COR_FUNDO_CARTAO};
    border: 1px solid {COR_BORDA};
    border-radius: 8px;
}}
QFrame[role="cartao-dia"] {{
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid {COR_DIVISORIA};
    border-radius: 8px;
}}
QFrame[role="cartao-sessao"] {{
    background-color: rgba(255, 255, 255, 0.025);
    border: 1px solid {COR_DIVISORIA};
    border-radius: 6px;
}}

/* ---------- ScrollArea ---------- */
QScrollArea {{
    background: transparent;
    border: 1px solid {COR_DIVISORIA};
    border-radius: 6px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {COR_BORDA_HOVER};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {COR_ACENTO}; }}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    border: none;
    background: transparent;
}}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {COR_BORDA_HOVER};
    border-radius: 5px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {COR_ACENTO}; }}

/* ---------- Menu da bandeja ---------- */
QMenu {{
    background-color: {COR_FUNDO_CARTAO};
    border: 1px solid {COR_BORDA_HOVER};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 22px 6px 14px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {COR_ACENTO_FRACO};
    color: {COR_ACENTO_HOVER};
}}
QMenu::separator {{
    height: 1px;
    background: {COR_DIVISORIA};
    margin: 4px 8px;
}}

/* ---------- Dica (tooltip) ---------- */
QToolTip {{
    background-color: {COR_FUNDO_INPUT};
    color: {COR_TEXTO};
    border: 1px solid {COR_BORDA_HOVER};
    padding: 4px 8px;
    border-radius: 4px;
}}

/* ---------- GroupBox ---------- */
QGroupBox {{
    background-color: {COR_FUNDO_ALT};
    border: 1px solid {COR_DIVISORIA};
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {COR_ACENTO};
    background: {COR_FUNDO_JANELA};
}}

/* ---------- Caixa de texto read-only (resultados de OCR) ---------- */
QTextEdit {{
    background-color: {COR_FUNDO_INPUT};
    border: 1px solid {COR_BORDA};
    border-radius: 6px;
    padding: 8px;
    color: {COR_TEXTO};
    selection-background-color: {COR_ACENTO};
    selection-color: #062028;
}}

/* ---------- QListWidget (lista de sugestões, listas de itens) ---------- */
QListWidget {{
    background-color: {COR_FUNDO_INPUT};
    border: 1px solid {COR_BORDA};
    border-radius: 6px;
    padding: 4px;
    outline: 0;
}}
QListWidget::item {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 6px;
    color: {COR_TEXTO};
}}
QListWidget::item:hover {{
    background-color: {COR_FUNDO_CARTAO_HOVER};
}}
QListWidget::item:selected {{
    background-color: {COR_ACENTO_FRACO};
    border: 1px solid {COR_ACENTO};
    color: {COR_TEXTO};
}}
QListWidget::item:disabled {{
    color: {COR_TEXTO_MUTED};
    background: transparent;
}}

/* ---------- QTreeWidget (Aba Itens Prime, diálogo de adicionar) ---------- */
QTreeWidget, QTreeView {{
    background-color: {COR_FUNDO_INPUT};
    border: 1px solid {COR_DIVISORIA};
    border-radius: 6px;
    outline: 0;
    font-size: 12px;
}}
QTreeWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    color: {COR_TEXTO};
}}
QTreeWidget::item:hover {{
    background-color: {COR_FUNDO_CARTAO_HOVER};
}}
QTreeWidget::item:selected {{
    background-color: {COR_ACENTO_FRACO};
    color: {COR_ACENTO_HOVER};
}}
QHeaderView::section {{
    background-color: {COR_FUNDO_CARTAO};
    color: {COR_ACENTO};
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid {COR_BORDA};
    border-right: 1px solid {COR_DIVISORIA};
    font-weight: 600;
    font-size: 12px;
}}
"""


def aplicar_tema(app):
    """Aplica o QSS_BASE num QApplication. É chamado uma vez em main.py."""
    app.setStyleSheet(QSS_BASE)


def _qcolor(hex_str: str):
    """Converte um token de cor do tema (#rrggbb) em QColor — usado em
    widgets que pintam células via setForeground (QTreeWidget, QTableWidget),
    já que essas APIs não aceitam string."""
    from PySide6.QtGui import QColor
    cor = QColor(hex_str)
    return cor
