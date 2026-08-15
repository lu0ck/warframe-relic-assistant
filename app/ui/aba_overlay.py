"""
Aba 1 — Painel de controle do overlay.

Mostra o status do cache de preços com uma animação leve (baseada só em
texto girando, sem precisar de nenhum arquivo de imagem) enquanto a
atualização diária roda em background, e o resultado (sucesso/falha) ao
final — isso é a Fase 6 do plano.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QScrollArea, QHBoxLayout,
)
from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices

from app import config
from app.dados import cache
from app.dados.atualizador_thread import AtualizadorThread
from app.modelos import OpcaoRecompensa
from app.ui import tema
from app.ui.card_opcao import CardOpcao

QUADROS_SPINNER = ["◐", "◓", "◑", "◒"]


class AbaOverlay(QWidget):
    recompensa_escolhida = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread_atualizacao: AtualizadorThread | None = None
        self._indice_spinner = 0
        self._geracao = 0

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(6)
        layout.setContentsMargins(14, 12, 14, 12)

        titulo = QLabel("Overlay de Relíquias")
        titulo.setProperty("data-role", "titulo")
        layout.addWidget(titulo)

        descricao = QLabel(
            "Aperte a tecla configurada na tela de recompensa — o overlay "
            "abre no monitor configurado."
        )
        descricao.setWordWrap(True)
        descricao.setStyleSheet(
            f"color: {tema.COR_TEXTO_SECUNDARIO}; "
            f"font-size: {tema.FONTE_PEQUENA};"
        )
        layout.addWidget(descricao)

        # Cartão de status do banco — uma única caixa compacta. A label "Banco
        # de preços" é só um microtítulo acima do status em si; padding interno
        # reduzido pra não comer espaço vertical.
        self._cartao_status = QWidget()
        self._cartao_status.setStyleSheet(f"background: {tema.COR_FUNDO_CARTAO}; border: 1px solid {tema.COR_DIVISORIA}; border-radius: 8px;")
        layout_status = QVBoxLayout(self._cartao_status)
        layout_status.setContentsMargins(12, 8, 12, 8)
        layout_status.setSpacing(2)
        rotulo_status = QLabel("Banco de preços")
        rotulo_status.setStyleSheet(f"color: {tema.COR_TEXTO_SECUNDARIO}; font-size: {tema.FONTE_PEQUENA}; letter-spacing: 1px;")
        self.status_cache = QLabel("Verificando banco de preços...")
        self.status_cache.setStyleSheet(f"color: {tema.COR_TEXTO}; font-size: {tema.FONTE_CORPO}; font-weight: 600;")
        layout_status.addWidget(rotulo_status)
        layout_status.addWidget(self.status_cache)
        layout.addWidget(self._cartao_status)

        # Painel para mostrar as recompensas da última captura (modo embutido).
        # Fica dentro de um QScrollArea pra lista grande nunca redimensionar a
        # janela do app (o que fazia ela "encolher do nada" ao reconhecer itens).
        # Sem setMaximumHeight: antes a área era capada em 340px mesmo numa
        # janela gigante — agora ela pega todo o espaço vertical que sobra do
        # layout (via stretch=1 no addWidget abaixo).
        self._recompensas_rolagem = QScrollArea()
        self._recompensas_rolagem.setWidgetResizable(True)
        self._recompensas_rolagem.setMinimumHeight(120)
        conteudo = QWidget()
        conteudo.setStyleSheet("background: transparent;")
        self._recompensas_panel = QVBoxLayout(conteudo)
        self._recompensas_panel.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._recompensas_panel.setSpacing(8)
        self._recompensas_rolagem.setWidget(conteudo)
        layout.addWidget(self._recompensas_rolagem, 1)

        linha_botoes = QHBoxLayout()
        self.botao_atualizar_agora = QPushButton("Atualizar banco agora")
        self.botao_atualizar_agora.setProperty("role", "primario")
        self.botao_atualizar_agora.clicked.connect(self.iniciar_atualizacao)
        linha_botoes.addWidget(self.botao_atualizar_agora)

        self.botao_cancelar = QPushButton("Cancelar atualização")
        self.botao_cancelar.clicked.connect(self.cancelar_atualizacao)
        self.botao_cancelar.setEnabled(False)
        linha_botoes.addWidget(self.botao_cancelar)

        # Abre o cache.db no gerenciador de arquivos do sistema — útil pra
        # inspecionar os dados com sqlitebrowser/DB Browser for SQLite, ou
        # pra backup. Não mexe no arquivo (abre a pasta).
        self.botao_abrir_bd = QPushButton("Abrir banco de dados")
        self.botao_abrir_bd.setToolTip(
            f"Abre o arquivo do banco ({config.CAMINHO_BANCO.name}) no "
            f"gerenciador de arquivos do sistema — pra você inspecionar "
            f"com sqlitebrowser ou fazer backup."
        )
        self.botao_abrir_bd.clicked.connect(self._abrir_bd)
        linha_botoes.addWidget(self.botao_abrir_bd)
        layout.addLayout(linha_botoes)

        self._timer_spinner = QTimer(self)
        self._timer_spinner.setInterval(150)
        self._timer_spinner.timeout.connect(self._girar_spinner)

    def mostrar_recompensas(self, opcoes: list[OpcaoRecompensa]) -> int:
        """Mostra as recompensas no painel embedded (modo embutido).

        Devolve um "token de geração" — pra quem agenda o auto-clear saber se o
        painel ainda mostra esta captura ou se já foi substituída por outra.
        """
        self._geracao += 1
        token = self._geracao
        # Limpar painel existente
        while self._recompensas_panel.count():
            item = self._recompensas_panel.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        # Adicionar novos cards
        for opcao in opcoes:
            card = CardOpcao(opcao)
            card.clicado.connect(lambda _, o=opcao: self.recompensa_escolhida.emit(o))
            self._recompensas_panel.addWidget(card)
        return token

    def limpar_recompensas(self, token: int | None = None):
        """Limpa o painel embutido. Se `token` for dado, só limpa se o painel
        ainda exibe aquela geração (evita apagar uma captura mais nova)."""
        if token is not None and token != self._geracao:
            return
        while self._recompensas_panel.count():
            item = self._recompensas_panel.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def verificar_e_atualizar_se_necessario(self):
        total = cache.contar_itens_no_cache()
        # A rotina diária baixa peças Prime E mods — dispara se qualquer um
        # dos dois estiver defasado.
        if cache.precisa_atualizar_hoje() or cache.precisa_atualizar_mods_hoje():
            self.iniciar_atualizacao()
        else:
            ultima = cache.data_da_ultima_atualizacao()
            self.status_cache.setText(f"● Banco em dia ({total} itens, atualizado em {ultima})")

    def iniciar_atualizacao(self):
        if self._thread_atualizacao is not None and self._thread_atualizacao.isRunning():
            return  # já tem uma atualização rolando, não duplica

        self.botao_atualizar_agora.setEnabled(False)
        self.botao_cancelar.setEnabled(True)
        self._timer_spinner.start()

        self._thread_atualizacao = AtualizadorThread(self)
        self._thread_atualizacao.progresso.connect(self._ao_progredir)
        self._thread_atualizacao.concluido.connect(self._ao_concluir)
        self._thread_atualizacao.start()

    def cancelar_atualizacao(self):
        if self._thread_atualizacao is not None and self._thread_atualizacao.isRunning():
            self.botao_cancelar.setEnabled(False)
            self.status_cache.setText("◐ Cancelando atualização...")
            self._thread_atualizacao.cancelar()

    def parar_atualizacao(self):
        """Encerra a atualização em background (usado ao fechar o app)."""
        if self._thread_atualizacao is not None and self._thread_atualizacao.isRunning():
            self._thread_atualizacao.cancelar()
            self._thread_atualizacao.wait(5000)

    def _girar_spinner(self):
        quadro = QUADROS_SPINNER[self._indice_spinner % len(QUADROS_SPINNER)]
        self._indice_spinner += 1
        texto_atual = self.status_cache.text()
        if " itens processados" in texto_atual:
            self.status_cache.setText(f"{quadro} {texto_atual.split(' ', 1)[1]}")
        else:
            self.status_cache.setText(f"{quadro} Atualizando banco de preços...")

    def _ao_progredir(self, feito: int, total: int):
        self.status_cache.setText(f"◐ {feito}/{total} itens processados")

    def _ao_concluir(self, sucesso: bool, mensagem: str):
        self._timer_spinner.stop()
        self.botao_atualizar_agora.setEnabled(True)
        self.botao_cancelar.setEnabled(False)
        simbolo = "●" if sucesso else "▲"
        cor = tema.COR_MELHOR if sucesso else tema.COR_ALERTA
        self.status_cache.setText(f"{simbolo} {mensagem}")
        self.status_cache.setStyleSheet(
            f"color: {cor}; font-size: {tema.FONTE_SUBTITULO}; font-weight: 600;"
        )

    def _abrir_bd(self):
        """Abre o arquivo do banco no gerenciador de arquivos do sistema.

        Usa QDesktopServices.openUrl com a pasta que contém o cache.db —
        abrir a pasta (em vez do arquivo) é mais útil porque a maioria dos
        gerenciadores não sabe o que fazer com .db sozinho. Selecionar o
        arquivo não é portátil, então pelo menos já cai na pasta certa.
        """
        pasta = config.CAMINHO_BANCO.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pasta)))
