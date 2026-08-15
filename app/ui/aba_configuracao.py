"""
Aba 4 — Configurações, dentro da janela principal.

Reúne hotkey, monitor do overlay, duração, nome da janela do jogo e a pasta
de prints. Ao salvar, emite `salvo(hotkey)` pra aplicação reconfigurar o
listener sem precisar reiniciar.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app import config as config_do_app
from app.dados import cache
from app.ui import tema


def _cartao(titulo: str) -> tuple[QFrame, QVBoxLayout]:
    """Cria um cartão genérico (QFrame[role="cartao"]) com título e devolve
    o layout interno pra quem chamou adicionar os campos."""
    cartao = QFrame()
    cartao.setProperty("role", "cartao")
    layout_externo = QVBoxLayout(cartao)
    layout_externo.setContentsMargins(16, 14, 16, 16)
    layout_externo.setSpacing(10)

    rotulo = QLabel(titulo.upper())
    rotulo.setStyleSheet(
        f"color: {tema.COR_ACENTO}; font-size: {tema.FONTE_PEQUENA}; "
        "letter-spacing: 2px; font-weight: 600;"
    )
    layout_externo.addWidget(rotulo)

    return cartao, layout_externo


def _novo_formulario() -> QFormLayout:
    form = QFormLayout()
    form.setSpacing(8)
    form.setLabelAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    return form


class AbaConfiguracao(QWidget):
    salvo = Signal(str)  # emite o nome da hotkey configurada

    def __init__(self, parent=None):
        super().__init__(parent)
        self._construir_ui()
        self._preencher_campos()

    def _construir_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        titulo = QLabel("Configurações")
        titulo.setProperty("data-role", "titulo")
        layout.addWidget(titulo)

        # ---------- Cartão: Overlay ----------
        cartao_overlay, layout_overlay = _cartao("Overlay")
        form_overlay = _novo_formulario()

        self.campo_hotkey = QLineEdit()
        self.campo_hotkey.setPlaceholderText("ex: <home>, <f9>, j")
        form_overlay.addRow("Tecla do overlay", self.campo_hotkey)

        telas = QGuiApplication.screens()
        self.campo_monitor = QComboBox()
        for indice, tela in enumerate(telas):
            self.campo_monitor.addItem(
                f"{indice}: {tela.geometry().width()}x{tela.geometry().height()}", indice
            )
        form_overlay.addRow("Monitor do overlay", self.campo_monitor)

        self.campo_duracao = QSpinBox()
        self.campo_duracao.setRange(3, 120)
        self.campo_duracao.setSuffix(" s")
        form_overlay.addRow("Duração do overlay", self.campo_duracao)

        self.campo_nome_janela = QLineEdit()
        form_overlay.addRow("Nome da janela do jogo", self.campo_nome_janela)

        self.campo_modo_overlay = QComboBox()
        self.campo_modo_overlay.addItems(["Flutuante", "Embutido na janela"])
        self.campo_modo_overlay.setCurrentText("Flutuante")
        form_overlay.addRow("Modo do overlay", self.campo_modo_overlay)

        self.campo_overlay_y_frac = QDoubleSpinBox()
        self.campo_overlay_y_frac.setRange(0.0, 1.0)
        self.campo_overlay_y_frac.setSingleStep(0.01)
        self.campo_overlay_y_frac.setValue(config_do_app.PADRAO_OVERLAY_Y_FRAC)
        form_overlay.addRow("Altura do overlay (fração)", self.campo_overlay_y_frac)
        layout_overlay.addLayout(form_overlay)
        layout.addWidget(cartao_overlay)

        # ---------- Cartão: Captura automática ----------
        cartao_cap, layout_cap = _cartao("Captura automática")
        form_cap = _novo_formulario()

        self.campo_gatilho_automatico = QCheckBox(
            "Capturar sozinho quando a tela de recompensa abrir"
        )
        form_cap.addRow("Gatilho automático (EE.log)", self.campo_gatilho_automatico)

        self.campo_caminho_ee_log = QLineEdit()
        self.campo_caminho_ee_log.setReadOnly(True)
        self.campo_caminho_ee_log.setPlaceholderText(
            "Detecção automática — ou a variável WF_EE_LOG_PATH"
        )
        botao_escolher_log = QPushButton("Escolher...")
        botao_escolher_log.setCursor(Qt.CursorShape.PointingHandCursor)
        botao_escolher_log.clicked.connect(self._escolher_caminho_ee_log)
        linha_log = QHBoxLayout()
        linha_log.addWidget(self.campo_caminho_ee_log, 1)
        linha_log.addWidget(botao_escolher_log)
        form_cap.addRow("Caminho do EE.log", linha_log)

        self.campo_atraso = QSpinBox()
        self.campo_atraso.setRange(0, 10)
        self.campo_atraso.setSuffix(" s")
        form_cap.addRow("Atraso de captura após abrir", self.campo_atraso)
        layout_cap.addLayout(form_cap)
        layout.addWidget(cartao_cap)

        # ---------- Cartão: Prints ----------
        cartao_prints, layout_prints = _cartao("Prints da captura")
        form_prints = _novo_formulario()

        self.campo_pasta_prints = QLineEdit()
        self.campo_pasta_prints.setReadOnly(True)
        self.campo_pasta_prints.setPlaceholderText(
            f"Padrão: {config_do_app.PADRAO_PASTA_PRINTS}"
        )
        form_prints.addRow("Pasta dos prints", self.campo_pasta_prints)

        botao_escolher_pasta = QPushButton("Escolher pasta...")
        botao_escolher_pasta.setCursor(Qt.CursorShape.PointingHandCursor)
        botao_escolher_pasta.clicked.connect(self._escolher_pasta_prints)
        layout_prints.addWidget(botao_escolher_pasta, alignment=Qt.AlignmentFlag.AlignRight)
        layout_prints.addLayout(form_prints)
        layout.addWidget(cartao_prints)

        # ---------- Botão salvar + status ----------
        linha_botoes = QHBoxLayout()
        botao_salvar = QPushButton("Salvar")
        botao_salvar.setProperty("role", "primario")
        botao_salvar.clicked.connect(self._ao_salvar)
        linha_botoes.addWidget(botao_salvar)
        linha_botoes.addStretch(1)
        layout.addLayout(linha_botoes)

        self._rotulo_status = QLabel("")
        self._rotulo_status.setStyleSheet(f"color: {tema.COR_MELHOR}; font-size: {tema.FONTE_PEQUENA};")
        layout.addWidget(self._rotulo_status)

        layout.addStretch(1)

    def _preencher_campos(self):
        self.campo_hotkey.setText(
            cache.obter_config("hotkey", config_do_app.PADRAO_HOTKEY)
            or config_do_app.PADRAO_HOTKEY
        )

        indice_monitor = cache.obter_config(
            "monitor_index", str(config_do_app.PADRAO_MONITOR_INDEX)
        )
        try:
            self.campo_monitor.setCurrentIndex(int(indice_monitor))
        except ValueError:
            self.campo_monitor.setCurrentIndex(0)

        duracao = cache.obter_config(
            "duracao_overlay", str(config_do_app.PADRAO_DURACAO_OVERLAY_SEGUNDOS)
        )
        try:
            self.campo_duracao.setValue(int(duracao))
        except ValueError:
            self.campo_duracao.setValue(config_do_app.PADRAO_DURACAO_OVERLAY_SEGUNDOS)

        self.campo_nome_janela.setText(
            cache.obter_config("nome_janela_jogo", config_do_app.NOME_JANELA_JOGO)
            or config_do_app.NOME_JANELA_JOGO
        )

        modo = cache.obter_config("modo_overlay", "Flutuante")
        self.campo_modo_overlay.setCurrentText(modo)

        y_frac = cache.obter_config("overlay_y_frac")
        try:
            y = float(y_frac) if y_frac is not None else config_do_app.PADRAO_OVERLAY_Y_FRAC
            self.campo_overlay_y_frac.setValue(y)
        except (TypeError, ValueError):
            self.campo_overlay_y_frac.setValue(config_do_app.PADRAO_OVERLAY_Y_FRAC)

        gatilho = cache.obter_config(
            "gatilho_automatico", config_do_app.PADRAO_GATILHO_AUTOMATICO_LIGADO
        )
        self.campo_gatilho_automatico.setChecked(str(gatilho) not in ("0", "false", "False"))

        atraso = cache.obter_config(
            "atraso_captura_apos_abertura",
            config_do_app.PADRAO_ATRASO_CAPTURA_APOS_ABERTURA_SEG,
        )
        try:
            self.campo_atraso.setValue(int(float(atraso)))
        except (TypeError, ValueError):
            self.campo_atraso.setValue(
                int(config_do_app.PADRAO_ATRASO_CAPTURA_APOS_ABERTURA_SEG)
            )

        self.campo_pasta_prints.setText(
            cache.obter_config("pasta_prints") or ""
        )

        caminho_ee_log = cache.obter_config("caminho_ee_log")
        if caminho_ee_log:
            self.campo_caminho_ee_log.setText(caminho_ee_log)
        elif config_do_app.CAMINHO_EE_LOG:
            self.campo_caminho_ee_log.setText(str(config_do_app.CAMINHO_EE_LOG))

    def _ao_salvar(self):
        hotkey = self.campo_hotkey.text().strip() or config_do_app.PADRAO_HOTKEY
        cache.salvar_config("hotkey", hotkey)
        cache.salvar_config("monitor_index", str(self.campo_monitor.currentIndex()))
        cache.salvar_config("duracao_overlay", str(self.campo_duracao.value()))
        cache.salvar_config(
            "nome_janela_jogo",
            self.campo_nome_janela.text().strip() or config_do_app.NOME_JANELA_JOGO,
        )
        cache.salvar_config(
            "gatilho_automatico", "1" if self.campo_gatilho_automatico.isChecked() else "0"
        )
        cache.salvar_config("atraso_captura_apos_abertura", str(self.campo_atraso.value()))
        cache.salvar_config(
            "pasta_prints", self.campo_pasta_prints.text().strip()
        )
        cache.salvar_config("modo_overlay", self.campo_modo_overlay.currentText())
        cache.salvar_config("overlay_y_frac", str(self.campo_overlay_y_frac.value()))
        cache.salvar_config("caminho_ee_log", self.campo_caminho_ee_log.text().strip())
        self._rotulo_status.setText("● Configurações salvas.")
        self.salvo.emit(hotkey)

    def _escolher_caminho_ee_log(self):
        """Abre o seletor de arquivo apontando pro EE.log (só grava ao salvar)."""
        atual = self.campo_caminho_ee_log.text().strip()
        inicial = atual or str(
            config_do_app.CAMINHO_EE_LOG
            if config_do_app.CAMINHO_EE_LOG
            else Path.home()
        )
        escolhido, _ = QFileDialog.getOpenFileName(
            self, "Arquivo EE.log do Warframe", inicial, "Log (*.log *.txt);;Todos (*)"
        )
        if escolhido:
            self.campo_caminho_ee_log.setText(escolhido)

    def _escolher_pasta_prints(self):
        """Abre o seletor de pasta e preenche o campo (só grava no banco ao salvar)."""
        pasta_inicial = self.campo_pasta_prints.text().strip() or str(
            config_do_app.PADRAO_PASTA_PRINTS
        )
        escolhida = QFileDialog.getExistingDirectory(
            self, "Pasta dos prints da captura", pasta_inicial
        )
        if escolhida:
            self.campo_pasta_prints.setText(escolhida)
