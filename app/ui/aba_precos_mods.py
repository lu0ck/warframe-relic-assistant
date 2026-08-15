"""
Aba "Mods Preços" — navegador do banco de preços de mods.

Mesma cara da aba "Itens Prime", só que sobre o cache de mods (mods_cache):
  - filtro por nome (substring case-insensitive);
  - ordenação clicável no cabeçalho (nome / preço);
  - botão "do mais caro → mais barato" e "do mais barato → mais caro";
  - filtro de faixa de preço em platina;
  - paginação (100 por página);
  - copiar nome com duplo-clique na linha.

Mod não tem ducados, então são só duas colunas.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QSpinBox, QApplication,
)

from app.dados import cache
from app.ui import tema

ITENS_POR_PAGINA = 100


class AbaPrecosMods(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ordenar_por = "preco_plata"
        self._decrescente = True  # por padrão do mais caro pro mais barato
        self._pagina = 0
        self._total = 0

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # ---------------- Título + legenda ----------------
        titulo = QLabel("Mods Preços")
        titulo.setProperty("data-role", "titulo")
        layout.addWidget(titulo)

        descricao = QLabel(
            "Preços de platina dos mods no cache (warframe.market). Clique no "
            "cabeçalho pra ordenar; use o filtro de nome e a faixa de platina "
            "pra achar os mods que valem mais no momento. Duplo-clique na "
            "linha copia o nome."
        )
        descricao.setWordWrap(True)
        descricao.setStyleSheet(
            f"color: {tema.COR_TEXTO_SECUNDARIO}; font-size: {tema.FONTE_PEQUENA};"
        )
        layout.addWidget(descricao)

        # ---------------- Filtros ----------------
        filtros = QHBoxLayout()
        filtros.setSpacing(8)

        filtros.addWidget(QLabel("Nome:"))
        self.campo_nome = QLineEdit()
        self.campo_nome.setPlaceholderText("ex: continuity, maim, truth…")
        self.campo_nome.textChanged.connect(self._ao_filtro_mudar)
        filtros.addWidget(self.campo_nome, stretch=1)

        filtros.addWidget(QLabel("Preço min:"))
        self.campo_min = QSpinBox()
        self.campo_min.setRange(0, 9999)
        self.campo_min.setSuffix("p")
        self.campo_min.setSpecialValueText("mín")
        self.campo_min.valueChanged.connect(self._ao_filtro_mudar)
        filtros.addWidget(self.campo_min)

        filtros.addWidget(QLabel("max:"))
        self.campo_max = QSpinBox()
        self.campo_max.setRange(0, 9999)
        self.campo_max.setSuffix("p")
        self.campo_max.setSpecialValueText("máx")
        self.campo_max.setValue(0)  # 0 = "máx" (sem limite)
        self.campo_max.valueChanged.connect(self._ao_filtro_mudar)
        filtros.addWidget(self.campo_max)

        self.botao_mais_caro = QPushButton("▼ Mais caro")
        self.botao_mais_caro.setProperty("role", "primario")
        self.botao_mais_caro.clicked.connect(self._ordenar_mais_caro)
        filtros.addWidget(self.botao_mais_caro)

        self.botao_mais_barato = QPushButton("▲ Mais barato")
        self.botao_mais_barato.clicked.connect(self._ordenar_mais_barato)
        filtros.addWidget(self.botao_mais_barato)

        layout.addLayout(filtros)

        # ---------------- Status bar (contagem) ----------------
        self.rotulo_status = QLabel("")
        self.rotulo_status.setStyleSheet(
            f"color: {tema.COR_TEXTO_SECUNDARIO}; font-size: {tema.FONTE_PEQUENA};"
        )
        layout.addWidget(self.rotulo_status)

        # ---------------- Tabela ----------------
        self.tabela = QTreeWidget()
        self.tabela.setColumnCount(2)
        self.tabela.setHeaderLabels(["Mod", "Preço (platina)"])
        self.tabela.setRootIsDecorated(False)
        self.tabela.setUniformRowHeights(True)
        self.tabela.setAlternatingRowColors(False)
        self.tabela.setItemsExpandable(False)
        self.tabela.setSortingEnabled(False)  # ordenação manual (clicar cabeçalho)
        self.tabela.header().setSectionsClickable(True)
        self.tabela.header().sectionClicked.connect(self._ao_clicar_cabecalho)
        self.tabela.itemDoubleClicked.connect(self._ao_duplo_clique_item)

        header = self.tabela.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tabela, stretch=1)

        # ---------------- Paginação ----------------
        paginacao = QHBoxLayout()
        self.botao_prev = QPushButton("‹ Anterior")
        self.botao_prev.clicked.connect(self._pagina_anterior)
        self.botao_prox = QPushButton("Próxima ›")
        self.botao_prox.clicked.connect(self._proxima_pagina)
        self.rotulo_pagina = QLabel("")
        self.rotulo_pagina.setStyleSheet(f"color: {tema.COR_TEXTO_SECUNDARIO};")
        paginacao.addWidget(self.botao_prev)
        paginacao.addStretch(1)
        paginacao.addWidget(self.rotulo_pagina)
        paginacao.addStretch(1)
        paginacao.addWidget(self.botao_prox)
        layout.addLayout(paginacao)

        self.recarregar()

    # ------------------------------------------------------------------
    # Filtros / paginação
    # ------------------------------------------------------------------

    def _ao_filtro_mudar(self, *args):
        self._pagina = 0
        self.recarregar()

    def _proxima_pagina(self):
        ultima = max(0, (self._total - 1) // ITENS_POR_PAGINA)
        if self._pagina < ultima:
            self._pagina += 1
            self.recarregar()

    def _pagina_anterior(self):
        if self._pagina > 0:
            self._pagina -= 1
            self.recarregar()

    def _ordenar_mais_caro(self):
        self._ordenar_por = "preco_plata"
        self._decrescente = True
        self._pagina = 0
        self._destacar_botao_ordem()
        self.recarregar()

    def _ordenar_mais_barato(self):
        self._ordenar_por = "preco_plata"
        self._decrescente = False
        self._pagina = 0
        self._destacar_botao_ordem()
        self.recarregar()

    def _destacar_botao_ordem(self):
        self.botao_mais_caro.setProperty(
            "role",
            "primario" if self._ordenar_por == "preco_plata" and self._decrescente else "",
        )
        self.botao_mais_barato.setProperty(
            "role",
            "primario" if self._ordenar_por == "preco_plata" and not self._decrescente else "",
        )
        from PySide6.QtWidgets import QStyle
        self.botao_mais_caro.style().unpolish(self.botao_mais_caro)
        self.botao_mais_caro.style().polish(self.botao_mais_caro)
        self.botao_mais_barato.style().unpolish(self.botao_mais_barato)
        self.botao_mais_barato.style().polish(self.botao_mais_barato)

    def _ao_clicar_cabecalho(self, coluna: int):
        colunas = {0: "nome", 1: "preco_plata"}
        novo_campo = colunas.get(coluna)
        if novo_campo is None:
            return
        if novo_campo == self._ordenar_por:
            self._decrescente = not self._decrescente
        else:
            self._ordenar_por = novo_campo
            self._decrescente = False if novo_campo == "nome" else True
        self._pagina = 0
        self._destacar_botao_ordem()
        self.recarregar()

    # ------------------------------------------------------------------
    # Recarregar
    # ------------------------------------------------------------------

    def recarregar(self):
        filtro_nome = self.campo_nome.text().strip() or None
        pmin = self.campo_min.value() or None
        pmax = self.campo_max.value() or None
        if pmax == 0:
            pmax = None

        mods, total = cache.listar_mods(
            ordenar_por=self._ordenar_por,
            decrescente=self._decrescente,
            limite=ITENS_POR_PAGINA,
            offset=self._pagina * ITENS_POR_PAGINA,
            filtro_nome=filtro_nome,
            preco_min=pmin,
            preco_max=pmax,
            # Sem filtro de faixa, mostra também os mods sem preço.
            somente_com_preco=(pmin is not None or pmax is not None),
        )
        self._total = total

        self.tabela.clear()
        for mod in mods:
            row = QTreeWidgetItem([
                mod.nome,
                f"{mod.preco_plata:.0f}p" if mod.preco_plata is not None else "—",
            ])
            row.setForeground(0, tema._qcolor(tema.COR_TEXTO))
            row.setForeground(1, tema._qcolor(tema.COR_PLATA))
            row.setData(0, Qt.ItemDataRole.UserRole, mod.nome)
            row.setToolTip(0, f"{mod.nome}\nslug: {mod.slug}\n(duplo-clique pra copiar)")
            self.tabela.addTopLevelItem(row)

        texto_status = f"● {total} mod(ns) no cache"
        if total > 0 and self._ordenar_por == "preco_plata":
            todos, _ = cache.listar_mods(
                ordenar_por=self._ordenar_por,
                decrescente=self._decrescente,
                limite=1, offset=0,
                filtro_nome=filtro_nome,
                preco_min=pmin, preco_max=pmax,
                somente_com_preco=(pmin is not None or pmax is not None),
            )
            if todos and todos[0].preco_plata is not None:
                if self._decrescente:
                    texto_status += f"  ·  ⤓ mais caro: {todos[0].preco_plata:.0f}p"
                else:
                    texto_status += f"  ·  ⤒ mais barato: {todos[0].preco_plata:.0f}p"
        self.rotulo_status.setText(texto_status)

        ultima = max(0, (self._total - 1) // ITENS_POR_PAGINA)
        self.botao_prev.setEnabled(self._pagina > 0)
        self.botao_prox.setEnabled(self._pagina < ultima)
        if self._total > 0:
            self.rotulo_pagina.setText(
                f"página {self._pagina + 1} de {ultima + 1}"
            )
        else:
            self.rotulo_pagina.setText("")

        self._destacar_botao_ordem()

    # ------------------------------------------------------------------
    # Copiar mod (duplo-clique na linha copia o nome)
    # ------------------------------------------------------------------

    def _ao_duplo_clique_item(self, item: QTreeWidgetItem, coluna: int):
        nome = item.data(0, Qt.ItemDataRole.UserRole)
        if nome:
            QApplication.clipboard().setText(nome)
            texto_anterior = self.rotulo_status.text()
            self.rotulo_status.setText(
                f"● '{nome[:50]}' copiado pra área de transferência."
            )
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: self.rotulo_status.setText(texto_anterior))
