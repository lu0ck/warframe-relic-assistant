"""Diálogo "Adicionar item ao histórico".

Quando o usuário percebe que o OCR não pegou um item na sessão de abertura,
ele adiciona manualmente. Fluxo:

  - digita no campo de texto → debounce → fuzzy match → mostra TOP N
    candidatos numa tabela com colunas (nome, preço, ducados, confiança);
  - o usuário navega com ↑↓ do teclado, clica com o mouse (clique simples
    seleciona, duplo-clique confirma) ou Enter (confirma o selecionado);
  - se o texto não casar com nada confiável, ainda dá pra confirmar com
    "Adicionar" — o item fica salvo como nome bruto (sem preço/slug);
  - ESC cancela.

A busca é feita com rapidfuzz (mesma engine do `encontrar_melhor_correspondencia`),
usando o limiar LIMIAR_CONFIANCA = 62 da comparação principal.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QMessageBox,
)
from rapidfuzz import fuzz, process

from app.dados import cache
from app.ui import tema

MAX_SUGESTOES = 8
DEBOUNCE_MS = 220


class DialogoAdicionarItem(QDialog):
    """Diálogo para adicionar um item a uma sessão do histórico.

    Emite `item_confirmado(nome)` — quem instancia conecta nesse signal e
    chama `historico.adicionar_item`, que resolve de novo contra o cache
    pra achar preço/ducados/slug e recalcular o "melhor".
    """

    item_confirmado = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Adicionar item ao histórico")
        self.setMinimumWidth(560)
        self.setMinimumHeight(480)

        # Última busca — lista paralela à QTreeWidget (mesma ordem das
        # linhas). Usada pra saber qual ItemCache corresponde ao row atual.
        self._candidatos: list[cache.ItemCache] = []

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._atualizar_lista)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        titulo = QLabel("Adicionar item à sessão")
        titulo.setProperty("data-role", "subtitulo")
        layout.addWidget(titulo)

        instrucao = QLabel(
            "Digite o nome do item como aparece no jogo (em inglês). "
            "Use ↑↓ pra escolher, Enter pra confirmar, ou clique no item."
        )
        instrucao.setWordWrap(True)
        instrucao.setStyleSheet(f"color: {tema.COR_TEXTO_SECUNDARIO};")
        layout.addWidget(instrucao)

        self.entrada = QLineEdit()
        self.entrada.setPlaceholderText("ex: Neo Saryn Prime Chassis Blueprint")
        self.entrada.textChanged.connect(self._ao_texto_mudar)
        layout.addWidget(self.entrada)

        # QTreeWidget com 4 colunas — texto nunca sobrepõe porque cada
        # coluna tem largura própria. Navegação por teclado é nativa.
        self.tabela = QTreeWidget()
        self.tabela.setColumnCount(4)
        self.tabela.setHeaderLabels(["Item", "Preço", "Ducados", "Confiança"])
        self.tabela.setRootIsDecorated(False)
        self.tabela.setUniformRowHeights(True)
        self.tabela.setAlternatingRowColors(False)
        self.tabela.setItemsExpandable(False)
        self.tabela.itemSelectionChanged.connect(self._ao_selecao_mudar)
        self.tabela.itemDoubleClicked.connect(lambda _item: self._confirmar_selecionado())

        header = self.tabela.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tabela, stretch=1)

        # Hint de aviso (sem correspondência confiável etc).
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setVisible(False)
        self._hint.setStyleSheet(
            f"color: {tema.COR_ALERTA}; font-size: {tema.FONTE_PEQUENA}; "
            "background: rgba(224, 154, 111, 0.08); "
            "border: 1px solid rgba(224, 154, 111, 0.25); "
            "border-radius: 6px; padding: 8px 10px;"
        )
        layout.addWidget(self._hint)

        botoes = QHBoxLayout()
        botoes.addStretch(1)
        self._botao_cancelar = QPushButton("Cancelar")
        self._botao_cancelar.clicked.connect(self.reject)
        self._botao_confirmar = QPushButton("Adicionar")
        self._botao_confirmar.setProperty("role", "primario")
        self._botao_confirmar.setEnabled(False)
        self._botao_confirmar.clicked.connect(self._confirmar_selecionado)
        botoes.addWidget(self._botao_cancelar)
        botoes.addWidget(self._botao_confirmar)
        layout.addLayout(botoes)

        self.entrada.setFocus()

    # ------------------------------------------------------------------
    # Busca
    # ------------------------------------------------------------------

    def _ao_texto_mudar(self, texto: str):
        if not texto.strip():
            self.tabela.clear()
            self._candidatos = []
            self._botao_confirmar.setEnabled(False)
            self._hint.setVisible(False)
            return
        self._debounce.start()

    def _atualizar_lista(self):
        """Roda a busca fuzzy (debounce já protegeu) e povoa a QTreeWidget
        com os top N candidatos acima do limiar de confiança."""
        texto = self.entrada.text().strip()
        if not texto:
            self.tabela.clear()
            self._candidatos = []
            return

        candidatos = cache.todos_os_nomes_e_precos()
        if not candidatos:
            self._candidatos = []
            self._povoar_mensagem("Banco de preços vazio. Atualize na aba Overlay antes.")
            return

        nomes = [c.nome for c in candidatos]
        resultados = process.extract(texto, nomes, scorer=fuzz.WRatio, limit=MAX_SUGESTOES * 2)
        # Limiar 62 — mesmo do `encontrar_melhor_correspondencia`.
        filtrados = [r for r in resultados if r[1] >= 62]
        if not filtrados:
            self._candidatos = []
            melhor_pct = f"{resultados[0][1]:.0f}%" if resultados else "—"
            self._povoar_mensagem(
                f"Nenhuma correspondência confiável (melhor: {melhor_pct}). "
                f"\"Adicionar\" salva como nome bruto."
            )
            self._mostrar_hint_alerta(
                f"▲ sem correspondência confiável pra '{texto}'. "
                f"\"Adicionar\" salva como '{texto}' sem preço/slug — você "
                f"pode editar o nome depois."
            )
            return

        # Top N. Monta `_candidatos` PARALELO às linhas da tabela.
        top = filtrados[:MAX_SUGESTOES]
        self._candidatos = [candidatos[r[2]] for r in top]

        self.tabela.clear()
        for r in top:
            c = candidatos[r[2]]
            row = QTreeWidgetItem([
                c.nome,
                f"{c.preco_plata:.0f}p" if c.preco_plata is not None else "—",
                f"◆ {c.ducados}" if c.ducados is not None else "—",
                f"{r[1]:.0f}%",
            ])
            # Cor por coluna
            row.setForeground(0, tema._qcolor(tema.COR_TEXTO))
            row.setForeground(1, tema._qcolor(tema.COR_PLATA))
            row.setForeground(2, tema._qcolor(tema.COR_DUCADOS))
            row.setForeground(3, tema._qcolor(tema.COR_TEXTO_MUTED))
            self.tabela.addTopLevelItem(row)

        self._hint.setVisible(False)
        if self.tabela.topLevelItemCount() > 0:
            self.tabela.setCurrentItem(self.tabela.topLevelItem(0))

    def _povoar_mensagem(self, mensagem: str):
        self.tabela.clear()
        row = QTreeWidgetItem([mensagem, "", "", ""])
        row.setFlags(Qt.ItemFlag.NoItemFlags)
        row.setForeground(0, tema._qcolor(tema.COR_TEXTO_MUTED))
        self.tabela.addTopLevelItem(row)

    def _mostrar_hint_alerta(self, mensagem: str):
        self._hint.setText(mensagem)
        self._hint.setVisible(True)
        # Habilita o botão Adicionar mesmo sem match confiável (pra salvar
        # nome bruto, com confirmação explícita no _confirmar_selecionado).
        self._botao_confirmar.setEnabled(True)

    def _ao_selecao_mudar(self):
        self._botao_confirmar.setEnabled(True)

    # ------------------------------------------------------------------
    # Confirmação
    # ------------------------------------------------------------------

    def _confirmar_selecionado(self):
        """Confirma o item selecionado. Se a tabela está vazia (sem match),
        confirma o texto bruto digitado — depois de confirmar com o usuário."""
        item = self.tabela.currentItem()
        if item is None or (item.flags() & Qt.ItemFlag.NoItemFlags):
            # Sem seleção na tabela: só aceita se tiver texto bruto.
            texto = self.entrada.text().strip()
            if not texto:
                return
            resposta = QMessageBox.question(
                self, "Sem correspondência",
                f"'{texto}' não foi encontrado no cache de preços.\n\n"
                f"Adicionar mesmo assim como nome bruto (sem preço/ducados/slug)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return
            self.item_confirmado.emit(texto)
            self.accept()
            return

        # Item selecionado: o índice da linha na tabela == índice em
        # `_candidatos` (montados em paralelo).
        row_idx = self.tabela.indexOfTopLevelItem(item)
        if 0 <= row_idx < len(self._candidatos):
            nome = self._candidatos[row_idx].nome
        else:
            nome = self.entrada.text().strip()
        self.item_confirmado.emit(nome)
        self.accept()

    # ------------------------------------------------------------------
    # Teclado
    # ------------------------------------------------------------------

    def keyPressEvent(self, evento: QKeyEvent):
        """Repassa ↑↓ do QLineEdit pra tabela (pra usuário navegar sem ter
        que clicar nela) e cuida do Enter/ESC."""
        if evento.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        if evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirmar_selecionado()
            return
        # Se o foco está no QLineEdit e a tecla é ↑/↓, navega a tabela em
        # vez de mexer no cursor do texto.
        if self.focusWidget() is self.entrada:
            if evento.key() == Qt.Key.Key_Down:
                row = min(self.tabela.currentIndex().row() + 1, self.tabela.topLevelItemCount() - 1)
                if row >= 0 and self.tabela.topLevelItemCount() > 0:
                    self.tabela.setCurrentItem(self.tabela.topLevelItem(row))
                return
            if evento.key() == Qt.Key.Key_Up:
                row = max(self.tabela.currentIndex().row() - 1, 0)
                if self.tabela.topLevelItemCount() > 0:
                    self.tabela.setCurrentItem(self.tabela.topLevelItem(row))
                return
        super().keyPressEvent(evento)
