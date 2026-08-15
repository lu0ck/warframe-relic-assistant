"""
Bandeja do sistema (Fase 8).

Ícone no tray com: Abrir (janela principal), Atualizar banco agora,
Configurações e Sair. Criado em app/main.py.
"""
from PySide6.QtWidgets import QMenu, QSystemTrayIcon
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPainterPath

from app import config
from app.config import NOME_APP


def icone_app() -> QIcon:
    """Ícone do app: usa o arquivo icones/assistente-reliquias.svg se existir;
    senão gera em runtime um losango ciano sobre fundo escuro."""
    svg = config.RAIZ_PROJETO / "icones" / "assistente-reliquias.svg"
    if svg.exists():
        return QIcon(str(svg))

    tamanho = 64
    pix = QPixmap(tamanho, tamanho)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # fundo arredondado
    p.setBrush(QColor("#0b0e14"))
    p.setPen(QColor("#25304a"))
    p.drawRoundedRect(2, 2, tamanho - 4, tamanho - 4, 12, 12)
    # losango ciano (estilo relíquia do Void)
    p.setBrush(QColor("#36c5d6"))
    p.setPen(QColor("#5ad9e8"))
    caminho = QPainterPath()
    cx, cy = tamanho / 2, tamanho / 2
    r = tamanho * 0.28
    caminho.moveTo(cx, cy - r)
    caminho.lineTo(cx + r, cy)
    caminho.lineTo(cx, cy + r)
    caminho.lineTo(cx - r, cy)
    caminho.closeSubpath()
    p.drawPath(caminho)
    p.end()
    return QIcon(pix)


class Bandeja:
    def __init__(self, ao_abrir, ao_atualizar, ao_configurar, ao_sair):
        self._ao_abrir = ao_abrir
        self._tray = QSystemTrayIcon(icone_app(), None)
        self._tray.setToolTip(NOME_APP)

        menu = QMenu()
        menu.addAction("Abrir", ao_abrir)
        menu.addAction("Atualizar banco agora", ao_atualizar)
        menu.addAction("Configurações", ao_configurar)
        menu.addSeparator()
        menu.addAction("Sair", ao_sair)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._ao_ativar)

    def _ao_ativar(self, razao):
        # Clique simples no ícone reabre a janela principal.
        if razao == QSystemTrayIcon.ActivationReason.Trigger:
            self._ao_abrir()

    def mostrar(self):
        self._tray.show()

    def notificar(self, titulo: str, mensagem: str):
        self._tray.showMessage(titulo, mensagem, QSystemTrayIcon.MessageIcon.Information, 4000)
