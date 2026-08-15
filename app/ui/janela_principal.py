from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMainWindow, QTabWidget, QVBoxLayout, QWidget

from app.config import NOME_APP
from app.ui.aba_overlay import AbaOverlay
from app.ui.aba_historico import AbaHistorico
from app.ui.aba_itens import AbaItens
from app.ui.aba_precos_mods import AbaPrecosMods
from app.ui.aba_calibracao import AbaCalibracao
from app.ui.aba_configuracao import AbaConfiguracao
from app.ui.aba_inventario import AbaInventario
from app.ui.aba_mods import AbaMods

# Índices das abas em JanelaPrincipal.abas — usados por `abrir_na_aba`
# (bandeja: "Configurações" leva direto pra essa aba). Se mudar a ordem,
# ajuste esses índices junto.
ABA_OVERLAY = 0
ABA_HISTORICO = 1
ABA_ITENS = 2
ABA_MODS_PRECOS = 3
ABA_INVENTARIO = 4
ABA_CALIBRACAO = 5
ABA_CONFIGURACAO = 6
ABA_MODS = 7


class JanelaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(NOME_APP)

        # Tamanho inicial: ocupa o espaço vertical disponível no monitor
        # primário — importante pra telas na vertical (1080×1920 etc.), onde
        # um tamanho fixo pequeno obrigava a rolar a aba Itens Prime. Usamos
        # `availableGeometry` (sem taskbar) e limitamos a largura pra 900px
        # (colunas da aba Itens Prime não precisam de mais) e a altura a
        # 1400px (cabe ~50+ linhas da lista sem scroll, sem virar "janela
        # enorme" num monitor horizontal normal).
        tela = QGuiApplication.primaryScreen()
        if tela is not None:
            g = tela.availableGeometry()
            self.resize(min(g.width(), 900), min(g.height(), 1400))
        else:
            self.resize(900, 700)
        # Tamanho mínimo: mesmo quando o conteúdo interno (cards embutidos,
        # histórico) muda o sizeHint, a janela nunca encolhe abaixo disso.
        self.setMinimumSize(720, 560)

        self.abas = QTabWidget()
        self.abas.setDocumentMode(False)
        self.abas.tabBar().setExpanding(False)
        self.aba_overlay = AbaOverlay()
        self.aba_historico = AbaHistorico()
        self.aba_itens = AbaItens()
        self.aba_precos_mods = AbaPrecosMods()
        self.aba_calibracao = AbaCalibracao()
        self.aba_configuracao = AbaConfiguracao()
        self.aba_inventario = AbaInventario()
        self.aba_mods = AbaMods()

        self.abas.addTab(self.aba_overlay, "Overlay")
        self.abas.addTab(self.aba_historico, "Histórico")
        self.abas.addTab(self.aba_itens, "Itens Prime")
        self.abas.addTab(self.aba_precos_mods, "Mods Preços")
        self.abas.addTab(self.aba_inventario, "Inventário")
        self.abas.addTab(self.aba_calibracao, "Calibração")
        self.abas.addTab(self.aba_configuracao, "Configurações")
        self.abas.addTab(self.aba_mods, "Mods")

        container = QWidget()
        layout_container = QVBoxLayout(container)
        layout_container.setContentsMargins(0, 0, 0, 0)
        layout_container.addWidget(self.abas)
        self.setCentralWidget(container)

        # Garante que a aba histórico abre com a visão mais fresca —
        # protege contra qualquer caso de a aba ser mostrada sem update.
        self.aba_historico.recarregar()
        # ✓ no histórico entra no inventário geral na hora — a aba Inventário
        # recarrega do banco automaticamente.
        self.aba_historico.inventario_alterado.connect(
            self.aba_inventario.recarregar_do_banco
        )

    def abrir_na_aba(self, indice: int):
        """Mostra a janela (se estiver na bandeja) já na aba escolhida."""
        if 0 <= indice < self.abas.count():
            self.abas.setCurrentIndex(indice)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, evento):
        # Para as varreduras (inventário e mods) e a atualização do banco
        # antes de fechar — QThread destruído ativo é erro.
        self.aba_inventario.parar_varredura()
        self.aba_mods.parar_varredura()
        self.aba_overlay.parar_atualizacao()
        super().closeEvent(evento)
