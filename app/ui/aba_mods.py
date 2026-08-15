"""
Aba "Mods" — análise da tela de Offerings das Syndicates (o que vale a pena).

Fluxo completo de leitura:
  - "Definir área da grade" marca o retângulo sobre a grade de Offerings
    (reusa o calibrador por retângulo do Inventário, parametrizado pra mods);
  - "Iniciar varredura" roda o OCR da grade numa thread própria (intervalo
    ~0.8s), LIMA a tabela e acumula os mods lidos desta leitura;
  - "Finalizar varredura" para o loop; a tabela fica editável pra revisão;
  - "+ Adicionar Mod" cadastra um mod digitado; "Carregar exemplo" popula com
    dados falsos pra conferir layout.

É uma análise da tela atual: cada nova varredura começa a tabela do zero (a
tela de Offerings mostra 1 cópia de cada mod, então quantidade é sempre 1). Não
há inventário salvo — o preço vem do cache de mods (warframe.market).
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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
from app.automacao.varredura_mods import VarreduraMods
from app.captura.calibrar_inventario_gui import PainelCalibracaoInventario
from app.captura.calibrar_mods import (
    CHAVE_GRADE_MODS,
    CHAVE_GRADE_MODS_PROPORCAO,
    obter_grade_mods,
)
from app.captura.screenshot import capturar_janela_do_jogo
from app.dados import cache
from app.dados.inventario_mods import (
    LinhaMod,
    calcular_resumo_mods,
    chave_de_dedup_mod,
    resolver_preco_mod,
    resumo_por_mod,
    top_mods,
)
from app.ui import tema

COLUNAS = ["Mod", "Qtd", "Preço unit", "Valor"]

# Dados falsos pra validar a UI sem o jogo: nomes reais de mods (incluindo os
# de uma palavra só — Vitality, Flow etc.) resolvidos contra o cache local
# quando o download diário de mods já tiver rodado.
EXEMPLO_MODS = [
    ("Vitality", 4),
    ("Flow", 2),
    ("Streamline", 1),
    ("Redirection", 3),
    ("Continuity", 2),
    ("Intensify", 1),
    ("Stretch", 2),
    ("Split Chamber", 1),
    ("Point Blank", 1),
    ("Hunter Munitions", 1),
]

INSTRUCOES_MODS = (
    "Arraste o mouse pra desenhar o retângulo sobre a GRADE de Offerings "
    "inteira (todas as colunas visíveis).\n\n"
    "Clicar perto de uma borda ajusta só ela; clicar no meio cria um "
    "retângulo novo. Ctrl+S salva.\n\n"
    "Deixe o Warframe aberto na tela de Offerings de uma Syndicate antes de "
    "capturar."
)


def _formatar_preco(preco: float | None) -> str:
    if preco is None:
        return "Sem preço"
    return f"{preco:g}p"


class _TabelaMods(QTableWidget):
    """Tabela da varredura de mods; a tecla Delete remove as linhas selecionadas."""

    def __init__(self, ao_apagar, parent=None):
        super().__init__(0, len(COLUNAS), parent)
        self._ao_apagar = ao_apagar

    def keyPressEvent(self, evento):
        if evento.key() == Qt.Key.Key_Delete:
            self._ao_apagar()
            return
        super().keyPressEvent(evento)


class AbaMods(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._carregando = False
        self._painel_area: PainelCalibracaoInventario | None = None
        self._varredura: VarreduraMods | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        titulo = QLabel("Mods")
        titulo.setProperty("data-role", "titulo")
        layout.addWidget(titulo)

        descricao = QLabel(
            "Análise da tela de Offerings da Syndicate: defina a área da grade "
            "e use 'Iniciar varredura' — o app lê o nome de cada mod do card e "
            "mostra o preço de platina do cache de mods (baixado junto com as "
            "Peças Prime na primeira abertura do dia). Cada nova varredura "
            "limpa a tabela (a tela mostra 1 cópia de cada mod)."
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

        # ---------------- Linha de dados ----------------
        linha_dados = QHBoxLayout()
        linha_dados.setSpacing(8)
        self.botao_adicionar = QPushButton("+ Adicionar Mod")
        self.botao_adicionar.clicked.connect(self._adicionar_mod)
        self.botao_exemplo = QPushButton("Carregar exemplo")
        self.botao_exemplo.clicked.connect(self._carregar_exemplo)
        self.botao_remover = QPushButton("Remover selecionado")
        self.botao_remover.clicked.connect(self._remover_selecionados)
        self.botao_limpar = QPushButton("Limpar")
        self.botao_limpar.clicked.connect(self._limpar)
        linha_dados.addWidget(self.botao_adicionar)
        linha_dados.addWidget(self.botao_exemplo)
        linha_dados.addWidget(self.botao_remover)
        linha_dados.addWidget(self.botao_limpar)
        linha_dados.addStretch(1)
        layout.addLayout(linha_dados)

        # ---------------- Busca ----------------
        self.campo_busca = QLineEdit()
        self.campo_busca.setPlaceholderText("🔍 Buscar mod…")
        self.campo_busca.setClearButtonEnabled(True)
        self.campo_busca.textChanged.connect(self._filtrar_tabela)
        layout.addWidget(self.campo_busca)

        # ---------------- Status da área ----------------
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
        self.tabela = _TabelaMods(ao_apagar=self._remover_selecionados)
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

    def _item_nome(self, linha: LinhaMod) -> QTableWidgetItem:
        item = QTableWidgetItem(linha.nome)
        item.setData(Qt.ItemDataRole.UserRole, linha.slug)
        item.setForeground(tema._qcolor(tema.COR_TEXTO))
        return item

    def _item_qtd(self, linha: LinhaMod) -> QTableWidgetItem:
        item = QTableWidgetItem(str(linha.quantidade))
        item.setData(Qt.ItemDataRole.UserRole, linha.quantidade)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _item_preco(self, linha: LinhaMod) -> QTableWidgetItem:
        item = QTableWidgetItem(_formatar_preco(linha.preco_plata))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setData(Qt.ItemDataRole.UserRole, linha.preco_plata)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(tema._qcolor(tema.COR_PLATA))
        return item

    def _item_subtotal(self, linha: LinhaMod) -> QTableWidgetItem:
        item = QTableWidgetItem(_formatar_preco(linha.subtotal))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(tema._qcolor(tema.COR_PLATA))
        return item

    def _adicionar_linha(self, linha: LinhaMod):
        linha_atual = self.tabela.rowCount()
        self.tabela.insertRow(linha_atual)
        self.tabela.setItem(linha_atual, 0, self._item_nome(linha))
        self.tabela.setItem(linha_atual, 1, self._item_qtd(linha))
        self.tabela.setItem(linha_atual, 2, self._item_preco(linha))
        self.tabela.setItem(linha_atual, 3, self._item_subtotal(linha))
        self._filtrar_tabela(self.campo_busca.text())

    def _linhas_atuais(self) -> list[LinhaMod]:
        linhas = []
        for linha in range(self.tabela.rowCount()):
            item_nome = self.tabela.item(linha, 0)
            if item_nome is None:
                continue
            nome = item_nome.text().strip()
            if not nome:
                continue
            item_qtd = self.tabela.item(linha, 1)
            quantidade = item_qtd.data(Qt.ItemDataRole.UserRole) if item_qtd else 1
            item_preco = self.tabela.item(linha, 2)
            preco = item_preco.data(Qt.ItemDataRole.UserRole) if item_preco else None
            linhas.append(
                LinhaMod(
                    nome=nome,
                    quantidade=quantidade,
                    preco_plata=preco,
                    slug=item_nome.data(Qt.ItemDataRole.UserRole),
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
        elif item.column() == 1:
            self._recalcular_linha(item.row())
        self._atualizar_resumo()

    def _resolver_linha(self, linha: int):
        """Re-resolve nome editado: preço (fuzzy no cache de mods) e slug."""
        item_nome = self.tabela.item(linha, 0)
        nome = item_nome.text().strip()
        self._carregando = True
        try:
            if not nome:
                item_nome.setData(Qt.ItemDataRole.UserRole, None)
                item_preco = self.tabela.item(linha, 2)
                item_preco.setText(_formatar_preco(None))
                item_preco.setData(Qt.ItemDataRole.UserRole, None)
                self.tabela.item(linha, 3).setText(_formatar_preco(None))
                return
            resolvido = resolver_preco_mod(nome)
            item_nome.setData(Qt.ItemDataRole.UserRole, resolvido.slug)
            item_preco = self.tabela.item(linha, 2)
            item_preco.setText(_formatar_preco(resolvido.preco_plata))
            item_preco.setData(Qt.ItemDataRole.UserRole, resolvido.preco_plata)
            self._recalcular_linha(linha)
        finally:
            self._carregando = False

    def _recalcular_linha(self, linha: int):
        """Re-lê a quantidade e atualiza o valor da linha."""
        item_qtd = self.tabela.item(linha, 1)
        try:
            quantidade = int(item_qtd.text().strip()) if item_qtd else 1
        except (TypeError, ValueError):
            quantidade = 1
        if quantidade < 1:
            quantidade = 1
        item_qtd.setData(Qt.ItemDataRole.UserRole, quantidade)
        item_preco = self.tabela.item(linha, 2)
        preco = item_preco.data(Qt.ItemDataRole.UserRole)
        subtotal = preco * quantidade if preco is not None else None
        self.tabela.item(linha, 3).setText(_formatar_preco(subtotal))

    # ------------------------------------------------------------------
    # Ações dos botões
    # ------------------------------------------------------------------

    def _adicionar_mod(self):
        texto, ok = QInputDialog.getText(
            self,
            "Adicionar Mod",
            "Nome do mod (ex.: Vitality, Split Chamber):",
        )
        if not ok:
            return
        linha = resolver_preco_mod(texto)
        if not linha.nome:
            return
        self._carregando = True
        try:
            self._adicionar_linha(linha)
        finally:
            self._carregando = False
        self.rotulo_area.setText(
            f"'{linha.nome}' adicionado"
            + (f" ({_formatar_preco(linha.preco_plata)})" if linha.preco_plata is not None
               else " — sem preço no cache de mods.")
        )
        self._atualizar_resumo()

    def _carregar_exemplo(self):
        self._carregando = True
        try:
            self.tabela.setRowCount(0)
            for nome, quantidade in EXEMPLO_MODS:
                linha = resolver_preco_mod(nome)
                linha.quantidade = quantidade
                self._adicionar_linha(linha)
        finally:
            self._carregando = False
        self._atualizar_resumo()

    def _limpar(self):
        self._carregando = True
        try:
            self.tabela.setRowCount(0)
        finally:
            self._carregando = False
        self._atualizar_resumo()

    def _remover_selecionados(self):
        if self._carregando:
            return
        linhas = sorted({indice.row() for indice in self.tabela.selectedIndexes()})
        if not linhas:
            return
        resposta = QMessageBox.question(
            self,
            "Remover mods",
            f"Remover {len(linhas)} mod(ns) selecionado(s) da lista? "
            "Não afeta o banco de preços.",
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

    def _filtrar_tabela(self, texto: str):
        termo = texto.strip().lower()
        for linha in range(self.tabela.rowCount()):
            visivel = True
            if termo:
                item_nome = self.tabela.item(linha, 0)
                nome = item_nome.text() if item_nome else ""
                visivel = termo in nome.lower()
            self.tabela.setRowHidden(linha, not visivel)

    # ------------------------------------------------------------------
    # Resumo
    # ------------------------------------------------------------------

    def _atualizar_resumo(self):
        linhas = self._linhas_atuais()
        if not linhas:
            self.rotulo_resumo.setText(
                "Resumo: tabela vazia — use '+ Adicionar Mod', 'Carregar "
                "exemplo' ou a varredura."
            )
            return
        total = calcular_resumo_mods(linhas)
        partes = [f"TOTAL: {_formatar_preco(total.total_com_preco)}"]

        top = top_mods(linhas, limite=5)
        if top:
            nomes = " | ".join(
                f"{r.nome}: {r.quantidade}x · {_formatar_preco(r.subtotal)}"
                for r in top
            )
            partes.append(f"Top mods: {nomes}")
            if len(resumo_por_mod(linhas)) > len(top):
                partes.append("(demais mods somam no total acima)")

        if total.quantidade_sem_preco:
            partes.append(
                f"{total.quantidade_sem_preco} mod(s) sem preço "
                f"(valem 0 — atualize o banco na aba Overlay)"
            )
        self.rotulo_resumo.setText("\n".join(partes))

    # ------------------------------------------------------------------
    # Área da grade (calibrador por retângulo, reusado do Inventário)
    # ------------------------------------------------------------------

    def _atualizar_descricao_area(self):
        area = obter_grade_mods()
        if area is None:
            self.rotulo_area.setText(
                "Área da grade: não definida. Clique em 'Definir área da grade', "
                "deixe o Warframe na tela de Offerings e arraste o retângulo "
                "sobre a grade inteira."
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
            "Capturando em 3 segundos... deixe a tela de Offerings do Warframe "
            "visível!"
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
            f"Capturado ({origem}). Arraste o retângulo sobre a grade de mods "
            "inteira e clique em 'Salvar área'."
        )

        if self._painel_area is None:
            self._painel_area = PainelCalibracaoInventario(
                imagem,
                chave_area=CHAVE_GRADE_MODS,
                chave_proporcao=CHAVE_GRADE_MODS_PROPORCAO,
                obter_area=obter_grade_mods,
                titulo_area="grade de mods",
                instrucoes=INSTRUCOES_MODS,
            )
            self._painel_area.area_salva.connect(self._na_area_salva)
            self.layout().addWidget(self._painel_area, 1)
        else:
            self._painel_area.definir_imagem(imagem)
        self.botao_definir_area.setEnabled(True)

    def _na_area_salva(self):
        self._atualizar_descricao_area()

    # ------------------------------------------------------------------
    # Varredura contínua (OCR da grade de mods)
    # ------------------------------------------------------------------

    def _iniciar_varredura(self):
        if obter_grade_mods() is None:
            QMessageBox.warning(
                self,
                "Área não definida",
                "Defina a área da grade primeiro ('Definir área da grade'), "
                "deixando o Warframe na tela de Offerings.",
            )
            return
        # Nova varredura começa do zero: a tabela é uma análise da tela atual.
        self._limpar()
        intervalo = config.PADRAO_INTERVALO_VARREDURA_MODS_SEG
        try:
            intervalo = float(
                cache.obter_config(
                    "intervalo_varredura_mods",
                    config.PADRAO_INTERVALO_VARREDURA_MODS_SEG,
                )
            )
        except (TypeError, ValueError):
            pass
        self._varredura = VarreduraMods(intervalo=intervalo)
        self._varredura.nomes.connect(self._ao_nomes_lidos)
        self._varredura.erro.connect(self._ao_erro_varredura)
        self._varredura.parada.connect(self._ao_varredura_parada)
        self._varredura.start()
        self._definir_varredura_ativa(True)

    def _finalizar_varredura(self):
        if self._varredura is not None:
            # Não-bloqueante: o thread encerra na próxima passada e emite
            # `parada`, que restaura os botões em `_ao_varredura_parada`.
            self.botao_finalizar.setEnabled(False)
            self.botao_finalizar.setText("Parando…")
            self._varredura.parar()

    def parar_varredura(self):
        """Interrompe a varredura (usada no fechamento da janela)."""
        if self._varredura is not None:
            self._varredura.parar()
            # No shutdown, sim, esperamos a thread encerrar antes de soltar a
            # referência — evita destruir a QThread com ela ainda rodando.
            self._varredura.wait(5000)
            self._varredura = None
            self._definir_varredura_ativa(False)

    def _definir_varredura_ativa(self, ativa: bool):
        self.botao_iniciar.setEnabled(not ativa)
        self.botao_finalizar.setEnabled(ativa)
        # Destaque visual: o botão de ação ativa vira "primario".
        self.botao_finalizar.setProperty("role", "primario" if ativa else "")
        self.botao_iniciar.setProperty("role", "" if ativa else "primario")
        for botao in (self.botao_iniciar, self.botao_finalizar):
            botao.style().unpolish(botao)
            botao.style().polish(botao)
        self.rotulo_area.setText(
            "Varrendo… role a lista de Offerings e aguarde a 1ª leitura."
            if ativa
            else "Varredura parada."
        )

    def _ao_varredura_parada(self):
        self._varredura = None
        self._definir_varredura_ativa(False)
        self.botao_finalizar.setText("Finalizar varredura")

    def _ao_erro_varredura(self, mensagem: str):
        self.rotulo_area.setText(f"Varredura: {mensagem}")

    def _ao_nomes_lidos(self, itens):
        """Acumula os mods desta passada, deduplicando contra a tabela."""
        if self._varredura is None:
            return
        vistos = {chave_de_dedup_mod(l.nome, l.slug) for l in self._linhas_atuais()}
        novos = 0
        self._carregando = True
        try:
            for item in itens:
                chave = chave_de_dedup_mod(item.nome, item.slug)
                if chave in vistos:
                    continue
                vistos.add(chave)
                novos += 1
                self._adicionar_linha(
                    LinhaMod(
                        nome=item.nome,
                        quantidade=item.quantidade,
                        preco_plata=item.preco_plata,
                        slug=item.slug,
                    )
                )
        finally:
            self._carregando = False
        self._atualizar_resumo()
        if novos:
            self.rotulo_area.setText(
                f"Varredura: {novos} mod(s) novo(s) nesta passada "
                f"(total na tabela: {self.tabela.rowCount()})."
            )
