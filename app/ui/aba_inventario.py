"""
Aba "Inventário" — varredura da tela de vendas/Inventory do jogo (Fase 1).

Esta versão é a casca da UI, validável FORA do jogo:
  - tabela editável (nome, conjunto, quantidade, preço unit, subtotal);
  - botão "Carregar exemplo" popula com dados falsos pra conferir layout,
    agrupamento por conjunto e os totais;
  - botão "Definir área da grade" abre o calibrador por retângulo (arrasto
    sobre a captura ao vivo) — a área fica salva pra varredura real;
  - botão "Salvar no banco" persiste a revisão na tabela `inventario`.

A varredura automática da tela (Iniciar/Finalizar) chega na próxima etapa —
por enquanto os botões ficam desabilitados com uma dica.
"""
from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.automacao.varredura_inventario import VarreduraInventario
from app.captura.calibrar_inventario import obter_grade_inventario
from app.captura.calibrar_inventario_gui import PainelCalibracaoInventario
from app.captura.screenshot import capturar_janela_do_jogo
from app.dados import cache
from app.dados.inventario import (
    LinhaInventario,
    calcular_resumo,
    chave_de_dedup,
    nome_do_conjunto,
    resolver_preco,
    total_geral,
    total_geral_ducados,
)
from app.ui import tema

COLUNAS = ["Item", "Conjunto", "Qtd", "Ducados", "Preço unit", "Subtotal", "Vender"]

# Dados falsos pra validar a UI sem o jogo: nomes reais de peças Prime
# (resolvidos contra o cache local quando existir) com quantidades variadas.
EXEMPLO_ITENS = [
    ("Soma Prime Receiver", 3),
    ("Soma Prime Barrel", 2),
    ("Soma Prime Stock", 1),
    ("Lex Prime Receiver", 2),
    ("Akbronco Prime Link", 1),
    ("Nezha Prime Chassis Blueprint", 1),
    ("Nezha Prime Neuroptics Blueprint", 2),
    ("Valkyr Prime Systems Blueprint", 1),
    ("Valkyr Prime Carapace Blueprint", 1),
    ("Forma Blueprint", 5),
]


def _formatar_preco(preco: float | None) -> str:
    if preco is None:
        return "—"
    return f"{preco:g}p"


def _icone_vender() -> QIcon:
    """Gera o ícone de vender em runtime (mesmo padrão da bandeja): uma
    moeda de platina — círculo dourado com anel interno e brilho."""
    tamanho = 28
    pix = QPixmap(tamanho, tamanho)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    cx, cy, raio = tamanho / 2, tamanho / 2, tamanho * 0.40
    # borda da moeda
    p.setBrush(QColor("#caa95a"))
    p.setPen(QColor("#8a6f33"))
    p.drawEllipse(int(cx - raio), int(cy - raio), int(2 * raio), int(2 * raio))
    # anel interno
    p.setBrush(QColor("#e6c36f"))
    p.setPen(QColor("#b99449"))
    raio_interno = raio * 0.72
    p.drawEllipse(int(cx - raio_interno), int(cy - raio_interno),
                  int(2 * raio_interno), int(2 * raio_interno))
    # "P" de platina
    p.setPen(QColor("#6b531f"))
    fonte = p.font()
    fonte.setBold(True)
    fonte.setPixelSize(int(raio))
    p.setFont(fonte)
    p.drawText(int(cx - raio), int(cy - raio), int(2 * raio), int(2 * raio),
               Qt.AlignmentFlag.AlignCenter, "P")
    p.end()
    return QIcon(pix)


class _TabelaInventario(QTableWidget):
    """Tabela da varredura; a tecla Delete remove as linhas selecionadas."""

    def __init__(self, ao_apagar, parent=None):
        super().__init__(0, len(COLUNAS), parent)
        self._ao_apagar = ao_apagar

    def keyPressEvent(self, evento):
        if evento.key() == Qt.Key.Key_Delete:
            self._ao_apagar()
            return
        super().keyPressEvent(evento)


class AbaInventario(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._carregando = False
        self._painel_area: PainelCalibracaoInventario | None = None
        self._varredura: VarreduraInventario | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        titulo = QLabel("Inventário")
        titulo.setProperty("data-role", "titulo")
        layout.addWidget(titulo)

        descricao = QLabel(
            "Clique em 'Definir área da grade' com o jogo na tela de "
            "vendas/Inventory e arraste o retângulo sobre a grade inteira. "
            "Depois é só 'Iniciar varredura' e rolar a grade — o app junta as "
            "peças, soma as quantidades (selo azul) e mostra o valor por "
            "conjunto. Use 'Carregar exemplo' pra testar sem o jogo."
        )
        descricao.setWordWrap(True)
        descricao.setStyleSheet(
            f"color: {tema.COR_TEXTO_SECUNDARIO}; font-size: {tema.FONTE_PEQUENA};"
        )
        layout.addWidget(descricao)

        # ---------------- Botões de varredura ----------------
        linha_varredura = QHBoxLayout()
        linha_varredura.setSpacing(8)
        self.botao_iniciar = QPushButton("Iniciar varredura")
        self.botao_iniciar.setProperty("role", "primario")
        self.botao_iniciar.clicked.connect(self._iniciar_varredura)
        self.botao_finalizar = QPushButton("Finalizar varredura")
        self.botao_finalizar.setEnabled(False)
        self.botao_finalizar.clicked.connect(self._finalizar_varredura)
        self.botao_definir_area = QPushButton("Definir área da grade")
        self.botao_definir_area.clicked.connect(self._definir_area)
        linha_varredura.addWidget(self.botao_iniciar)
        linha_varredura.addWidget(self.botao_finalizar)
        linha_varredura.addStretch(1)
        linha_varredura.addWidget(self.botao_definir_area)
        layout.addLayout(linha_varredura)

        # ---------------- Linha de dados de exemplo / salvar ----------------
        linha_dados = QHBoxLayout()
        linha_dados.setSpacing(8)
        self.botao_exemplo = QPushButton("Carregar exemplo")
        self.botao_exemplo.clicked.connect(self._carregar_exemplo)
        self.botao_carregar_salvo = QPushButton("Carregar salvo")
        self.botao_carregar_salvo.clicked.connect(self._carregar_salvo)
        self.botao_remover = QPushButton("Remover selecionado")
        self.botao_remover.clicked.connect(self._remover_selecionados)
        self.botao_limpar = QPushButton("Limpar")
        self.botao_limpar.clicked.connect(self._limpar)
        self.botao_salvar = QPushButton("Salvar no banco")
        self.botao_salvar.setProperty("role", "primario")
        self.botao_salvar.clicked.connect(self._salvar)
        linha_dados.addWidget(self.botao_exemplo)
        linha_dados.addWidget(self.botao_carregar_salvo)
        linha_dados.addWidget(self.botao_remover)
        linha_dados.addWidget(self.botao_limpar)
        linha_dados.addStretch(1)
        linha_dados.addWidget(self.botao_salvar)
        layout.addLayout(linha_dados)

        # ---------------- Busca (lupa) ----------------
        self.campo_busca = QLineEdit()
        self.campo_busca.setPlaceholderText("🔍 Buscar item ou conjunto…")
        self.campo_busca.setClearButtonEnabled(True)
        self.campo_busca.textChanged.connect(self._filtrar_tabela)
        layout.addWidget(self.campo_busca)

        # ---------------- Status da área + varredura ----------------
        self.rotulo_area = QLabel("")
        self.rotulo_area.setWordWrap(True)
        self.rotulo_area.setStyleSheet(
            f"color: {tema.COR_TEXTO_SECUNDARIO}; "
            f"background: {tema.COR_FUNDO_CARTAO}; "
            f"border: 1px solid {tema.COR_DIVISORIA}; "
            "border-radius: 6px; padding: 8px 12px;"
        )
        layout.addWidget(self.rotulo_area)
        self._atualizar_descricao_area()

        # ---------------- Tabela ----------------
        self.tabela = _TabelaInventario(ao_apagar=self._remover_selecionados)
        self.tabela.setHorizontalHeaderLabels(COLUNAS)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setAlternatingRowColors(False)
        self.tabela.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self.tabela.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for coluna in range(1, len(COLUNAS)):
            header.setSectionResizeMode(coluna, QHeaderView.ResizeMode.ResizeToContents)
        self.tabela.itemChanged.connect(self._ao_item_mudado)
        layout.addWidget(self.tabela, stretch=1)

        # ---------------- Resumo ----------------
        self.rotulo_resumo = QLabel("Resumo: tabela vazia.")
        self.rotulo_resumo.setWordWrap(True)
        self.rotulo_resumo.setStyleSheet(
            f"color: {tema.COR_TEXTO_SECUNDARIO}; font-size: {tema.FONTE_PEQUENA};"
        )
        layout.addWidget(self.rotulo_resumo)

    # ------------------------------------------------------------------
    # Preencher / ler a tabela
    # ------------------------------------------------------------------

    def _item_nome(self, linha: LinhaInventario) -> QTableWidgetItem:
        item = QTableWidgetItem(linha.nome)
        item.setData(Qt.ItemDataRole.UserRole, linha.slug)
        item.setForeground(tema._qcolor(tema.COR_TEXTO))
        return item

    def _item_conjunto(self, linha: LinhaInventario) -> QTableWidgetItem:
        item = QTableWidgetItem(linha.conjunto)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setForeground(tema._qcolor(tema.COR_TEXTO_SECUNDARIO))
        return item

    def _item_qtd(self, linha: LinhaInventario) -> QTableWidgetItem:
        item = QTableWidgetItem(str(linha.quantidade))
        item.setData(Qt.ItemDataRole.UserRole, linha.quantidade)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _item_preco(self, linha: LinhaInventario) -> QTableWidgetItem:
        item = QTableWidgetItem(_formatar_preco(linha.preco_plata))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setData(Qt.ItemDataRole.UserRole, linha.preco_plata)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(tema._qcolor(tema.COR_PLATA))
        return item

    def _item_ducados(self, linha: LinhaInventario) -> QTableWidgetItem:
        texto = "—" if linha.ducados is None else f"{linha.ducados}"
        item = QTableWidgetItem(texto)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setData(Qt.ItemDataRole.UserRole, linha.ducados)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setForeground(tema._qcolor(tema.COR_TEXTO_SECUNDARIO))
        return item

    def _item_subtotal(self, linha: LinhaInventario) -> QTableWidgetItem:
        item = QTableWidgetItem(_formatar_preco(linha.subtotal))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(tema._qcolor(tema.COR_PLATA))
        return item

    def _adicionar_linha(self, linha: LinhaInventario):
        linha_atual = self.tabela.rowCount()
        self.tabela.insertRow(linha_atual)
        self.tabela.setItem(linha_atual, 0, self._item_nome(linha))
        self.tabela.setItem(linha_atual, 1, self._item_conjunto(linha))
        self.tabela.setItem(linha_atual, 2, self._item_qtd(linha))
        self.tabela.setItem(linha_atual, 3, self._item_ducados(linha))
        self.tabela.setItem(linha_atual, 4, self._item_preco(linha))
        self.tabela.setItem(linha_atual, 5, self._item_subtotal(linha))
        self.tabela.setCellWidget(
            linha_atual, len(COLUNAS) - 1, self._item_vender(linha)
        )
        self._filtrar_tabela(self.campo_busca.text())

    def _item_vender(self, linha: LinhaInventario) -> QWidget:
        botao = QPushButton()
        botao.setIcon(_icone_vender())
        botao.setIconSize(QSize(16, 16))
        botao.setText("Vender")
        botao.setToolTip(f"Vender '{linha.nome}' no warframe.market")
        botao.setCursor(Qt.CursorShape.PointingHandCursor)
        # Estilo explícito: sobrescreve o padding do QSS global (que esmagava o
        # ícone) e usa o azul neon do tema (mesmo dos botões primários).
        botao.setStyleSheet(
            "QPushButton {"
            "    background: transparent;"
            f"    border: 1px solid {tema.COR_ACENTO};"
            "    border-radius: 4px;"
            f"    color: {tema.COR_ACENTO_HOVER};"
            "    padding: 1px 8px;"
            f"    font-size: {tema.FONTE_PEQUENA};"
            "    font-weight: 600;"
            "}"
            f"QPushButton:hover {{ background: {tema.COR_ACENTO_FRACO}; }}"
        )
        # Captura nome/slug na criação (não o índice da linha), que sobrevive
        # a remoções/reordenações da tabela.
        botao.clicked.connect(
            lambda _=False, nome=linha.nome, slug=linha.slug:
            self._vender_item(nome, slug)
        )
        # Centraliza o botão (ícone + texto) dentro da célula.
        moldura = QWidget()
        layout = QHBoxLayout(moldura)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(botao, 0, Qt.AlignmentFlag.AlignCenter)
        return moldura

    def _linhas_atuais(self) -> list[LinhaInventario]:
        linhas = []
        for linha in range(self.tabela.rowCount()):
            item_nome = self.tabela.item(linha, 0)
            if item_nome is None:
                continue
            nome = item_nome.text().strip()
            if not nome:
                continue
            item_qtd = self.tabela.item(linha, 2)
            quantidade = item_qtd.data(Qt.ItemDataRole.UserRole) if item_qtd else 1
            item_preco = self.tabela.item(linha, 4)
            preco = item_preco.data(Qt.ItemDataRole.UserRole) if item_preco else None
            item_ducados = self.tabela.item(linha, 3)
            ducados = item_ducados.data(Qt.ItemDataRole.UserRole) if item_ducados else None
            linhas.append(
                LinhaInventario(
                    nome=nome,
                    quantidade=quantidade,
                    preco_plata=preco,
                    slug=item_nome.data(Qt.ItemDataRole.UserRole),
                    ducados=ducados,
                )
            )
        return linhas

    # ------------------------------------------------------------------
    # Edição (recalcular na hora)
    # ------------------------------------------------------------------

    def _ao_item_mudado(self, item: QTableWidgetItem):
        if self._carregando:
            return
        if item.column() == 0:
            self._resolver_linha(item.row())
        elif item.column() == 2:
            self._recalcular_linha(item.row())
        self._atualizar_resumo()

    def _resolver_linha(self, linha: int):
        """Re-resolve nome editado: conjunto, preço (fuzzy no cache) e slug."""
        item_nome = self.tabela.item(linha, 0)
        nome = item_nome.text().strip()
        self._carregando = True
        try:
            if not nome:
                item_nome.setData(Qt.ItemDataRole.UserRole, None)
                self.tabela.item(linha, 1).setText("")
                item_ducados = self.tabela.item(linha, 3)
                item_ducados.setText("—")
                item_ducados.setData(Qt.ItemDataRole.UserRole, None)
                item_preco = self.tabela.item(linha, 4)
                item_preco.setText(_formatar_preco(None))
                item_preco.setData(Qt.ItemDataRole.UserRole, None)
                self.tabela.item(linha, 5).setText(_formatar_preco(None))
                return
            resolvido = resolver_preco(nome)
            item_nome.setData(Qt.ItemDataRole.UserRole, resolvido.slug)
            self.tabela.item(linha, 1).setText(nome_do_conjunto(nome))
            item_ducados = self.tabela.item(linha, 3)
            item_ducados.setText("—" if resolvido.ducados is None else f"{resolvido.ducados}")
            item_ducados.setData(Qt.ItemDataRole.UserRole, resolvido.ducados)
            item_preco = self.tabela.item(linha, 4)
            item_preco.setText(_formatar_preco(resolvido.preco_plata))
            item_preco.setData(Qt.ItemDataRole.UserRole, resolvido.preco_plata)
            self._recalcular_linha(linha)
        finally:
            self._carregando = False

    def _recalcular_linha(self, linha: int):
        """Re-lê a quantidade e atualiza o subtotal da linha."""
        item_qtd = self.tabela.item(linha, 2)
        try:
            quantidade = int(item_qtd.text().strip()) if item_qtd else 1
        except (TypeError, ValueError):
            quantidade = 1
        if quantidade < 1:
            quantidade = 1
        item_qtd.setData(Qt.ItemDataRole.UserRole, quantidade)
        item_preco = self.tabela.item(linha, 4)
        preco = item_preco.data(Qt.ItemDataRole.UserRole)
        subtotal = preco * quantidade if preco is not None else None
        self.tabela.item(linha, 5).setText(_formatar_preco(subtotal))

    # ------------------------------------------------------------------
    # Ações dos botões
    # ------------------------------------------------------------------

    def _carregar_exemplo(self):
        self._carregando = True
        try:
            self.tabela.setRowCount(0)
            for nome, quantidade in EXEMPLO_ITENS:
                linha = resolver_preco(nome)
                linha.quantidade = quantidade
                self._adicionar_linha(linha)
        finally:
            self._carregando = False
        self._atualizar_resumo()

    def _carregar_salvo(self):
        salvo = cache.obter_inventario_salvo()
        if not salvo:
            QMessageBox.information(self, "Nada salvo", "Não há inventário salvo ainda.")
            return
        if self.tabela.rowCount() > 0:
            resposta = QMessageBox.question(
                self,
                "Substituir tabela atual",
                "Carregar o inventário salvo substitui o que está na tela. "
                "Continuar?",
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return
        self._carregando = True
        try:
            self.tabela.setRowCount(0)
            for registro in salvo:
                self._adicionar_linha(
                    LinhaInventario(
                        nome=registro["nome"],
                        quantidade=registro["quantidade"],
                        preco_plata=registro["preco_plata"],
                        slug=registro["slug"],
                        ducados=registro.get("ducados"),
                    )
                )
        finally:
            self._carregando = False
        self.rotulo_area.setText(
            f"Inventário salvo carregado ({len(salvo)} itens)."
        )
        self._atualizar_resumo()

    def recarregar_do_banco(self):
        """Recarrega a tabela com o inventário salvo no banco, sem confirmação.

        Usado pelo auto-refresh: quando um ✓ é marcado no histórico a peça já
        entrou no inventário geral, então esta aba reflete na hora. Substitui o
        conteúdo atual da tabela (rascunho não salvo é descartado).
        """
        salvo = cache.obter_inventario_salvo()
        self._carregando = True
        try:
            self.tabela.setRowCount(0)
            for registro in salvo:
                self._adicionar_linha(
                    LinhaInventario(
                        nome=registro["nome"],
                        quantidade=registro["quantidade"],
                        preco_plata=registro["preco_plata"],
                        slug=registro["slug"],
                        ducados=registro.get("ducados"),
                    )
                )
        finally:
            self._carregando = False
        self.rotulo_area.setText(
            f"Inventário salvo recarregado ({len(salvo)} itens) — atualizado "
            "após o ✓ marcado no histórico."
        )
        self._atualizar_resumo()

    def _limpar(self):
        self._carregando = True
        try:
            self.tabela.setRowCount(0)
        finally:
            self._carregando = False
        self._atualizar_resumo()

    def _vender_item(self, nome: str, slug: str | None):
        """Abre a página do item no warframe.market pra vender."""
        if not slug:
            slug = cache.buscar_slug_por_nome(nome)
        if not slug:
            QMessageBox.information(
                self,
                "Não dá pra vender",
                f"'{nome}' não está no banco de preços — sem página pra abrir.",
            )
            return
        QDesktopServices.openUrl(QUrl(f"https://warframe.market/items/{slug}"))

    def _filtrar_tabela(self, texto: str):
        """Mostra só as linhas cujo item/conjunto contém a busca (case-insensitive)."""
        termo = texto.strip().lower()
        for linha in range(self.tabela.rowCount()):
            visivel = True
            if termo:
                item_nome = self.tabela.item(linha, 0)
                item_conjunto = self.tabela.item(linha, 1)
                nome = (item_nome.text() if item_nome else "")
                conjunto = (item_conjunto.text() if item_conjunto else "")
                visivel = termo in nome.lower() or termo in conjunto.lower()
            self.tabela.setRowHidden(linha, not visivel)

    def _remover_selecionados(self):
        if self._carregando:
            return
        linhas = sorted({indice.row() for indice in self.tabela.selectedIndexes()})
        if not linhas:
            return
        resposta = QMessageBox.question(
            self,
            "Remover itens",
            f"Remover {len(linhas)} item(ns) selecionado(s) da lista? "
            "Não afeta o histórico nem o banco de preços.",
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return
        self._carregando = True
        try:
            for linha in reversed(linhas):
                self.tabela.removeRow(linha)
        finally:
            self._carregando = False
        self._atualizar_resumo()

    def _salvar(self):
        linhas = self._linhas_atuais()
        if not linhas:
            QMessageBox.information(self, "Nada pra salvar", "A tabela está vazia.")
            return
        info_salvo = cache.obter_info_inventario_salvo()
        if info_salvo is not None:
            quantidade_salva, data_salva = info_salvo
            resposta = QMessageBox.question(
                self,
                "Mesclar com inventário salvo",
                f"Já existe um inventário geral ({quantidade_salva} itens, "
                f"atualizado em {data_salva}).\n\nSalvar agora MESCLA com o "
                "existente: itens iguais somam a quantidade e os demais "
                "continuam no inventário. Continuar?",
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return
        cache.salvar_inventario(linhas)
        total = total_geral(linhas)
        total_ducados = total_geral_ducados(linhas)
        mensagem = f"{len(linhas)} itens mesclados no inventário geral.\n\n"
        for resumo in calcular_resumo(linhas):
            linha_resumo = f"  {resumo.conjunto}: {resumo.quantidade}x"
            if resumo.subtotal is not None:
                linha_resumo += f" · {_formatar_preco(resumo.subtotal)}"
            if resumo.total_ducados is not None:
                linha_resumo += f" · {resumo.total_ducados} ducados"
            mensagem += linha_resumo + "\n"
        if total is not None:
            mensagem += f"\nTotal: {_formatar_preco(total)}"
        else:
            mensagem += "\nTotal: sem preços (atualize o banco de preços na aba Overlay)"
        if total_ducados is not None:
            mensagem += f" · {total_ducados} ducados"
        QMessageBox.information(self, "Inventário salvo", mensagem)

    # ------------------------------------------------------------------
    # Resumo (subtotais por conjunto + total)
    # ------------------------------------------------------------------

    def _atualizar_resumo(self):
        linhas = self._linhas_atuais()
        if not linhas:
            self.rotulo_resumo.setText(
                "Resumo: tabela vazia — use 'Carregar exemplo' ou a varredura."
            )
            return
        partes = []
        for resumo in calcular_resumo(linhas):
            texto = f"{resumo.conjunto}: {resumo.quantidade}x"
            if resumo.subtotal is not None:
                texto += f" · {_formatar_preco(resumo.subtotal)}"
            elif resumo.total_ducados is not None:
                texto += " · sem preço"
            if resumo.total_ducados is not None:
                texto += f" · {resumo.total_ducados} ducados"
            partes.append(texto)
        total = total_geral(linhas)
        total_ducados = total_geral_ducados(linhas)
        texto = "Resumo: " + " | ".join(partes)
        if total is not None:
            texto += f"\nTotal geral: {_formatar_preco(total)}"
        else:
            texto += "\nTotal geral: sem preços ainda."
        if total_ducados is not None:
            texto += f" · {total_ducados} ducados"
        self.rotulo_resumo.setText(texto)

    # ------------------------------------------------------------------
    # Varredura (F2: nomes 2D + dedup; selo de quantidade chega na F3)
    # ------------------------------------------------------------------

    def _chaves_atuais(self) -> set[str]:
        """Chaves de dedup de todas as linhas atuais da tabela (reflete edições)."""
        chaves = set()
        for linha in range(self.tabela.rowCount()):
            item_nome = self.tabela.item(linha, 0)
            if item_nome is None:
                continue
            nome = item_nome.text().strip()
            if not nome:
                continue
            chaves.add(chave_de_dedup(nome, item_nome.data(Qt.ItemDataRole.UserRole)))
        return chaves

    def _iniciar_varredura(self):
        if self._varredura is not None and self._varredura.isRunning():
            return
        if obter_grade_inventario() is None:
            QMessageBox.information(
                self,
                "Área não definida",
                "Defina a área da grade primeiro (botão 'Definir área da "
                "grade') com o jogo na tela de vendas.",
            )
            return

        intervalo = config.PADRAO_INTERVALO_VARREDURA_INVENTARIO_SEG
        try:
            intervalo = float(
                cache.obter_config(
                    "intervalo_varredura_inventario", config.PADRAO_INTERVALO_VARREDURA_INVENTARIO_SEG
                )
            )
        except (TypeError, ValueError):
            pass

        self._varredura = VarreduraInventario(intervalo=intervalo, parent=self)
        self._varredura.nomes.connect(self._ao_nomes_lidos)
        self._varredura.erro.connect(self._ao_erro_varredura)
        self._varredura.parada.connect(self._ao_varredura_parada)
        self._varredura.start()

        self.botao_iniciar.setEnabled(False)
        self.botao_finalizar.setEnabled(True)
        self.rotulo_area.setText(
            "Varrendo... role pela grade do inventário. Itens novos entram na "
            "lista conforme aparecem; finalize quando terminar."
        )

    def _finalizar_varredura(self):
        if self._varredura is not None and self._varredura.isRunning():
            # Não-bloqueante: o thread encerra na próxima passada e emite
            # `parada`, que restaura os botões em `_ao_varredura_parada`.
            self.botao_finalizar.setEnabled(False)
            self.botao_finalizar.setText("Parando…")
            self._varredura.parar()

    def parar_varredura(self):
        """Usado pela janela principal no fechamento (evita thread órfã)."""
        if self._varredura is not None and self._varredura.isRunning():
            self._varredura.parar()
            # No shutdown, sim, esperamos a thread encerrar antes de soltar a
            # referência — evita destruir a QThread com ela ainda rodando.
            self._varredura.wait(5000)

    def _ao_varredura_parada(self):
        self.botao_iniciar.setEnabled(True)
        self.botao_finalizar.setEnabled(False)
        self.botao_finalizar.setText("Finalizar varredura")
        self._atualizar_descricao_area()
        linhas = self._linhas_atuais()
        self.rotulo_area.setText(
            f"Varredura finalizada — {len(linhas)} item(ns) na lista. "
            "Revise e 'Salvar no banco'."
        )

    def _ao_erro_varredura(self, mensagem: str):
        self.rotulo_area.setText(f"▲ {mensagem}")

    def _ao_nomes_lidos(self, itens):
        """Acumula os itens lidos na última passada, deduplicando por item.

        Linhas já existentes (mesmo slug/nome) não são tocadas — o usuário
        pode editar à vontade que a varredura não sobrescreve.
        """
        chaves = self._chaves_atuais()
        novos = 0
        self._carregando = True
        try:
            for item in itens:
                chave = chave_de_dedup(item.nome, item.slug)
                if chave in chaves:
                    continue
                self._adicionar_linha(
                    LinhaInventario(
                        nome=item.nome,
                        quantidade=item.quantidade,
                        preco_plata=item.preco_plata,
                        slug=item.slug,
                        ducados=item.ducados,
                    )
                )
                chaves.add(chave)
                novos += 1
        finally:
            self._carregando = False
        if novos:
            self.rotulo_area.setText(
                f"Varrendo... {novos} novo(s) item(ns) adicionado(s) na última "
                "passada ({len(self._linhas_atuais())} na lista)."
            )
            self._atualizar_resumo()

    # ------------------------------------------------------------------
    # Área da grade (calibrador por retângulo)
    # ------------------------------------------------------------------

    def _atualizar_descricao_area(self):
        area = obter_grade_inventario()
        if area is None:
            self.rotulo_area.setText(
                "Área da grade: não definida. Clique em 'Definir área da grade', "
                "deixe o Warframe na tela de vendas e arraste o retângulo sobre "
                "a grade inteira."
            )
            return
        x0, y0, x1, y1 = area
        self.rotulo_area.setText(
            f"Área da grade salva: x {x0:.2f}..{x1:.2f} · y {y0:.2f}..{y1:.2f} "
            "(frações da janela). Se o OCR não ler nada, redemarque aqui."
        )

    def _definir_area(self):
        self.botao_definir_area.setEnabled(False)
        self.rotulo_area.setText(
            "Capturando em 3 segundos... deixe a tela de vendas/Inventory do "
            "Warframe visível!"
        )
        QTimer.singleShot(3000, self._executar_captura_area)

    def _executar_captura_area(self):
        nome_janela = cache.obter_config("nome_janela_jogo") or config.NOME_JANELA_JOGO
        imagem, achou_janela = capturar_janela_do_jogo(nome_janela=nome_janela)
        origem = (
            "janela do jogo"
            if achou_janela
            else "MONITOR inteiro (janela do jogo não encontrada)"
        )
        self.rotulo_area.setText(
            f"Capturado ({origem}). Arraste o retângulo sobre a grade inteira "
            "e clique em 'Salvar área'."
        )

        if self._painel_area is None:
            self._painel_area = PainelCalibracaoInventario(imagem)
            self._painel_area.area_salva.connect(self._na_area_salva)
            self.layout().addWidget(self._painel_area, 1)
        else:
            self._painel_area.definir_imagem(imagem)
        self.botao_definir_area.setEnabled(True)

    def _na_area_salva(self):
        self._atualizar_descricao_area()
