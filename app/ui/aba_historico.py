"""
Aba 2 — Histórico de aberturas de relíquia, agrupado por dia.

Cada sessão mostra os itens, com a melhor opção destacada (★) e a opção que
você realmente clicou marcada (✓). Por item há ações: copiar o nome, editar
(corrigir nome errado do OCR), apagar o item, e vender no warframe.market
direto do histórico. Por sessão há um botão pra apagar tudo dela.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame, QPushButton,
    QGraphicsOpacityEffect, QHBoxLayout, QApplication, QInputDialog, QMessageBox,
    QDialog,
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Signal

from app.dados import cache, historico
from app.modelos import OpcaoRecompensa
from app.ui import tema
from app.ui.dialogo_venda import DialogoVenda


class AbaHistorico(QWidget):
    # Emitido quando um item vira (ou deixa de ser) o ✓ escolhido de uma
    # sessão — a janela principal usa pra atualizar a aba Inventário na hora
    # (a peça marcada já entrou/saiu do inventário geral no banco).
    inventario_alterado = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # A animação de entrada só roda na primeira construção. Depois disso,
        # `recarregar()` é chamado a cada ação (✓, editar, apagar, + item) e a
        # cada vez que a aba é aberta — re-animar faria o conteúdo todo sumir
        # e "remostrar" (tela escurecendo/piscando) a cada clique.
        self._animou_entrada = False

        layout_raiz = QVBoxLayout(self)
        layout_raiz.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout_raiz.setSpacing(10)
        layout_raiz.setContentsMargins(20, 20, 20, 20)

        cabecalho = QLabel("Histórico")
        cabecalho.setProperty("data-role", "titulo")
        layout_raiz.addWidget(cabecalho)

        descricao = QLabel(
            f"Suas aberturas de relíquia agrupadas por dia. "
            f"<span style='color:{tema.COR_MELHOR}'>★ melhor escolha</span> · "
            f"<span style='color:{tema.COR_ACENTO}'>✓ item escolhido</span> "
            f"(clique no <b>✓</b> ao lado do item pra marcar qual você pegou; "
            f"use <b>+ item</b> pra adicionar manualmente um item que o OCR não captou)."
        )
        descricao.setWordWrap(True)
        descricao.setStyleSheet(f"color: {tema.COR_TEXTO_SECUNDARIO};")
        layout_raiz.addWidget(descricao)

        linha_topo = QHBoxLayout()
        botao_criar_sessao = QPushButton("+ Criar sessão")
        botao_criar_sessao.setToolTip(
            "Cria uma sessão vazia com a data/hora de agora, pra registrar "
            "manualmente uma abertura que o OCR não captou. Depois é só usar "
            "'+ item' nela."
        )
        botao_criar_sessao.clicked.connect(self._criar_sessao)
        linha_topo.addWidget(botao_criar_sessao)
        botao_atualizar = QPushButton("Recarregar")
        botao_atualizar.setProperty("role", "primario")
        botao_atualizar.clicked.connect(self.recarregar)
        linha_topo.addWidget(botao_atualizar)
        linha_topo.addStretch(1)
        layout_raiz.addLayout(linha_topo)

        self._area_rolagem = QScrollArea()
        self._area_rolagem.setWidgetResizable(True)
        layout_raiz.addWidget(self._area_rolagem)

        self._conteudo = QWidget()
        self._conteudo.setStyleSheet("background: transparent;")
        self._layout_conteudo = QVBoxLayout(self._conteudo)
        self._layout_conteudo.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout_conteudo.setSpacing(10)
        self._area_rolagem.setWidget(self._conteudo)

        self.recarregar()

    def showEvent(self, evento):
        # Recarrega sempre que a aba é aberta — senão a sessão recém-capturada
        # só apareceria depois de clicar em "Recarregar".
        super().showEvent(evento)
        self.recarregar()

    def recarregar(self):
        # limpa o conteúdo atual
        while self._layout_conteudo.count():
            item = self._layout_conteudo.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        sessoes = historico.listar_historico_completo()

        if not sessoes:
            vazio = QLabel("Nenhum registro ainda. Abra uma relíquia com o overlay ativo pra começar.")
            vazio.setWordWrap(True)
            vazio.setStyleSheet(f"color: {tema.COR_TEXTO_MUTED}; padding: 20px;")
            self._layout_conteudo.addWidget(vazio)
        else:
            grupos = historico.agrupar_por_dia(sessoes)
            for dia, sessoes_do_dia in grupos.items():
                self._layout_conteudo.addWidget(self._construir_cartao_dia(dia, sessoes_do_dia))

        self._animar_entrada_primeira_vez()

    def _animar_entrada_primeira_vez(self):
        if self._animou_entrada:
            return
        self._animou_entrada = True
        self._animar_entrada(self._conteudo)

    def _construir_cartao_dia(self, dia: str, sessoes_do_dia: list[dict]) -> QFrame:
        cartao = QFrame()
        cartao.setProperty("role", "cartao-dia")
        layout = QVBoxLayout(cartao)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Soma platina + ducados APENAS dos itens que o usuário marcou
        # como escolhido (✓) no jogo. Itens "só exibidos" (que o OCR
        # reconheceu mas o jogador não pegou) não contam — o objetivo é
        # mostrar quanto rendeu de fato na prática. Soma zero em
        # qualquer um dos campos não é exibida pra não poluir o título.
        soma_plata = 0
        soma_ducados = 0
        for s in sessoes_do_dia:
            for it in s["itens"]:
                if not it.get("foi_escolhido"):
                    continue
                if it.get("preco_plata") is not None:
                    soma_plata += it["preco_plata"]
                if it.get("ducados") is not None:
                    soma_ducados += it["ducados"]

        titulo_texto = f"⌖ {dia}  ·  {len(sessoes_do_dia)} relíquia(s)"
        if soma_plata > 0 or soma_ducados > 0:
            extras = []
            if soma_plata > 0:
                extras.append(
                    f"<span style='color:{tema.COR_PLATA}; font-weight:600'>✓ {soma_plata:.0f}p</span>"
                )
            if soma_ducados > 0:
                extras.append(
                    f"<span style='color:{tema.COR_DUCADOS}'>◆ {soma_ducados} duc</span>"
                )
            titulo_texto += "  ·  " + "  ·  ".join(extras)

        titulo_dia = QLabel(titulo_texto)
        titulo_dia.setTextFormat(Qt.TextFormat.RichText)
        titulo_dia.setStyleSheet(
            f"font-weight: 600; font-size: {tema.FONTE_SUBTITULO}; color: {tema.COR_TEXTO};"
        )
        layout.addWidget(titulo_dia)

        for sessao in sessoes_do_dia:
            layout.addWidget(self._construir_linha_sessao(sessao))

        return cartao

    def _construir_linha_sessao(self, sessao: dict) -> QFrame:
        linha = QFrame()
        linha.setProperty("role", "cartao-sessao")
        layout = QVBoxLayout(linha)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        cabecalho = QHBoxLayout()
        hora = sessao["data_hora"][11:16]
        rotulo_hora = QLabel(f"◷ {hora}")
        rotulo_hora.setStyleSheet(f"font-size: {tema.FONTE_PEQUENA}; color: {tema.COR_TEXTO_SECUNDARIO};")
        cabecalho.addWidget(rotulo_hora)
        cabecalho.addStretch(1)

        botao_adicionar = QPushButton("+ item")
        botao_adicionar.setToolTip("Adicionar manualmente um item que o OCR não captou")
        botao_adicionar.setCursor(Qt.CursorShape.PointingHandCursor)
        botao_adicionar.clicked.connect(
            lambda _=False, sid=sessao["id"]: self._adicionar_item(sid)
        )
        cabecalho.addWidget(botao_adicionar)

        botao_apagar_sessao = QPushButton("Apagar sessão")
        botao_apagar_sessao.setProperty("role", "perigo")
        botao_apagar_sessao.setToolTip("Remove esta abertura inteira do histórico")
        botao_apagar_sessao.setCursor(Qt.CursorShape.PointingHandCursor)
        botao_apagar_sessao.clicked.connect(
            lambda _=False, sid=sessao["id"]: self._apagar_sessao(sid)
        )
        cabecalho.addWidget(botao_apagar_sessao)
        layout.addLayout(cabecalho)

        for item in sessao["itens"]:
            layout.addLayout(self._construir_linha_item(item, sessao))

        return linha

    def _construir_linha_item(self, item: dict, sessao: dict) -> QHBoxLayout:
        """Monta uma linha de item no histórico: ✓ clicável, nome, preço,
        e ações. Tudo sem largura fixa — usa sizeHint() dos próprios widgets
        pra não cortar texto nem ícones."""
        relica_id = sessao["id"]
        e_melhor = bool(item["e_melhor"])
        foi_escolhido = bool(item["foi_escolhido"])
        preco = f"{item['preco_plata']:.0f}p" if item["preco_plata"] is not None else "sem preço"

        linha_item = QHBoxLayout()
        linha_item.setSpacing(6)

        # Botão ✓ clicável: alterna o "item escolhido" desta sessão. Vai com
        # espaço no início da linha pra ficar visualmente agrupado ao nome.
        botao_check = QPushButton("✓" if foi_escolhido else "○")
        botao_check.setCheckable(True)
        botao_check.setChecked(foi_escolhido)
        botao_check.setToolTip(
            "Marca qual item você pegou. Clique pra alternar (só um por sessão)."
        )
        botao_check.setCursor(Qt.CursorShape.PointingHandCursor)
        botao_check.setFixedWidth(28)
        if foi_escolhido:
            botao_check.setStyleSheet(
                f"color: {tema.COR_FUNDO_JANELA}; "
                f"background-color: {tema.COR_ACENTO}; "
                f"border: 1px solid {tema.COR_ACENTO}; "
                "font-weight: 700; border-radius: 4px; padding: 2px 0;"
            )
        else:
            botao_check.setStyleSheet(
                f"color: {tema.COR_TEXTO_MUTED}; "
                f"background-color: transparent; "
                f"border: 1px solid {tema.COR_BORDA}; "
                "border-radius: 4px; padding: 2px 0;"
            )
        item_id = item["id"]
        botao_check.clicked.connect(
            lambda _=False, sid=relica_id, iid=item_id, chk=botao_check:
                self._alternar_escolhido(sid, iid, chk)
        )
        linha_item.addWidget(botao_check)

        # ★ melhor escolha (somente visual, não clicável).
        if e_melhor:
            selo_melhor = QLabel("★")
            selo_melhor.setFixedWidth(18)
            selo_melhor.setAlignment(Qt.AlignmentFlag.AlignCenter)
            selo_melhor.setStyleSheet(
                f"color: {tema.COR_MELHOR}; font-weight: 700; font-size: {tema.FONTE_CORPO};"
            )
            linha_item.addWidget(selo_melhor)

        # Nome — ocupa o espaço restante.
        rotulo = QLabel(item["nome"])
        rotulo.setStyleSheet(
            f"font-weight: 600; color: {tema.COR_MELHOR};" if e_melhor
            else f"color: {tema.COR_TEXTO};"
        )
        rotulo.setMinimumWidth(120)
        rotulo.setSizePolicy(rotulo.sizePolicy().horizontalPolicy(), rotulo.sizePolicy().verticalPolicy())
        linha_item.addWidget(rotulo, stretch=1)

        # Preço — SEM largura fixa: usa o tamanho natural do texto.
        rotulo_preco = QLabel(preco)
        rotulo_preco.setStyleSheet(f"color: {tema.COR_PLATA}; font-weight: 600;")
        rotulo_preco.setMinimumWidth(60)
        rotulo_preco.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        linha_item.addWidget(rotulo_preco)

        # Ações: aqui também sem largura fixa — deixa o botão crescer conforme
        # o texto ("Copiar", "Editar", "Apagar", "Vender"). Padding interno
        # já é do QSS base (7px 14px).
        nome_item = item["nome"]

        def _criar_acao(texto, dica, ao_clicar, primario=False, perigo=False):
            botao = QPushButton(texto)
            botao.setToolTip(dica)
            botao.setCursor(Qt.CursorShape.PointingHandCursor)
            if primario:
                botao.setProperty("role", "primario")
            if perigo:
                botao.setProperty("role", "perigo")
            botao.clicked.connect(lambda _=False, f=ao_clicar: f())
            return botao

        botao_copiar = _criar_acao(
            "Copiar", f"Copiar '{nome_item}'",
            lambda n=nome_item: QApplication.clipboard().setText(n),
        )
        linha_item.addWidget(botao_copiar)

        botao_editar = _criar_acao(
            "Editar", f"Editar nome de '{nome_item}'",
            lambda iid=item_id: self._editar_item(iid),
        )
        linha_item.addWidget(botao_editar)

        botao_apagar = _criar_acao(
            "Apagar", f"Apagar '{nome_item}' do histórico",
            lambda iid=item_id: self._apagar_item(iid),
            perigo=True,
        )
        linha_item.addWidget(botao_apagar)

        botao_vender = _criar_acao(
            "Vender", f"Publicar venda de '{nome_item}' no warframe.market",
            lambda i=item: self._vender_item(i),
            primario=True,
        )
        linha_item.addWidget(botao_vender)

        return linha_item

    def _alternar_escolhido(self, relica_id: int, item_id: int, botao_check) -> None:
        """Alterna o ✓ de "item escolhido".

        O signal `clicked` de um botão `checkable` dispara DEPOIS do Qt ter
        feito o toggle automático — então `isChecked()` já reflete o NOVO
        estado. Aqui só usamos esse estado: se ficou marcado, marca este
        item; se desmarcou (clique no ✓ pra tirar), NENHUM item fica
        escolhido nadaquela sessão."""
        novo_marcado = botao_check.isChecked()

        # Atualiza o visual do botão imediatamente pra refletir o novo estado
        # (o recarregar() abaixo também refaria, mas isso evita o flash).
        if novo_marcado:
            botao_check.setText("✓")
            botao_check.setStyleSheet(
                f"color: {tema.COR_FUNDO_JANELA}; "
                f"background-color: {tema.COR_ACENTO}; "
                f"border: 1px solid {tema.COR_ACENTO}; "
                "font-weight: 700; border-radius: 4px; padding: 2px 0;"
            )
            novo_id = item_id
        else:
            botao_check.setText("○")
            botao_check.setStyleSheet(
                f"color: {tema.COR_TEXTO_MUTED}; "
                f"background-color: transparent; "
                f"border: 1px solid {tema.COR_BORDA}; "
                "border-radius: 4px; padding: 2px 0;"
            )
            novo_id = None

        historico.definir_item_escolhido(relica_id, novo_id)
        self.recarregar()
        self.inventario_alterado.emit()

    def _criar_sessao(self):
        """Cria uma sessão vazia na data/hora atual e recarrega a lista.

        A sessão nova aparece no topo do dia de hoje — o usuário adiciona os
        itens com "+ item" e pode apagar com "Apagar sessão" se criou sem querer.
        """
        novo_id = historico.criar_sessao()
        self.recarregar()

    def _adicionar_item(self, relica_id: int) -> None:
        """Abre o diálogo de adicionar item e, se confirmado, salva o item na
        sessão e recarrega o histórico."""
        from app.ui.dialogo_adicionar_item import DialogoAdicionarItem

        dialogo = DialogoAdicionarItem(parent=self)
        dialogo.item_confirmado.connect(
            lambda texto: self._ao_item_adicionado(relica_id, texto)
        )
        dialogo.exec()

    def _ao_item_adicionado(self, relica_id: int, texto: str) -> None:
        item = historico.adicionar_item(relica_id, texto)
        if item is None:
            return
        # Feedback: diz como foi salvo (preço/slug podem ter ficado NULL).
        nome = item["nome"]
        if item["preco_plata"] is not None:
            QMessageBox.information(
                self, "Item adicionado",
                f"'{nome}' salvo na sessão.\n"
                f"Preço: {item['preco_plata']:.0f}p"
                + (f" · ◆ {item['ducados']} ducados" if item["ducados"] is not None else "")
                + (f"\n<b>★ melhor</b> da sessão" if item["e_melhor"] else ""),
            )
        else:
            QMessageBox.information(
                self, "Item adicionado",
                f"'{nome}' salvo na sessão (sem preço/ducados no cache).",
            )
        self.recarregar()

    def _editar_item(self, item_id: int):
        item = self._buscar_item(item_id)
        if item is None:
            return
        nome_antigo = item["nome"]

        # Antes usávamos QInputDialog.getText(...) (one-liner), mas o widget
        # interno dele vem com largura default curta (~270px) — nomes como
        # "Neo Saryn Prime Chassis Blueprint" ficam cortados e o usuário não
        # vê a continuação. Usamos a API imperativa aqui só pra forçar
        # setMinimumWidth e dar espaço pro texto.
        dialog = QInputDialog(self)
        dialog.setWindowTitle("Editar item")
        dialog.setLabelText("Corrigir nome (o OCR pode ter errado):")
        dialog.setTextValue(nome_antigo)
        dialog.setMinimumWidth(520)
        dialog.setMinimumHeight(180)  # evita corte vertical do label/texto
        ok = dialog.exec() == QDialog.DialogCode.Accepted
        novo_nome = dialog.textValue()

        if ok and novo_nome.strip():
            historico.editar_item(item_id, novo_nome)
            # Feedback: mostra como o nome foi resolvido contra o cache.
            atualizado = self._buscar_item(item_id)
            if atualizado is not None:
                nome_novo = atualizado["nome"]
                if nome_novo != novo_nome.strip():
                    QMessageBox.information(
                        self, "Item atualizado",
                        f"Nome corrigido pra: {nome_novo}\n"
                        f"Preço/ducados/slug também atualizados a partir do banco.",
                    )
                elif atualizado["preco_plata"] != item["preco_plata"]:
                    QMessageBox.information(
                        self, "Item atualizado",
                        f"Preço atualizado: {atualizado['preco_plata']:.0f}p.",
                    )
            self.recarregar()

    def _apagar_item(self, item_id: int):
        if QMessageBox.question(
            self, "Apagar item", "Remover este item do histórico?",
        ) == QMessageBox.StandardButton.Yes:
            historico.apagar_item(item_id)
            self.recarregar()

    def _apagar_sessao(self, relica_id: int):
        if QMessageBox.question(
            self, "Apagar sessão", "Remover esta abertura inteira do histórico?",
        ) == QMessageBox.StandardButton.Yes:
            historico.apagar_sessao(relica_id)
            self.recarregar()

    def _vender_item(self, item: dict):
        slug = item.get("slug")
        if not slug:
            slug = cache.buscar_slug_por_nome(item["nome"])
        if not slug:
            QMessageBox.information(
                self, "Não dá pra vender",
                "Este item não foi reconhecido no banco de preços — sem slug não "
                "é possível publicar a venda.",
            )
            return
        opcao = OpcaoRecompensa(
            nome=item["nome"],
            preco_plata=item["preco_plata"],
            ducados=item["ducados"],
            e_melhor=bool(item["e_melhor"]),
            slug=slug,
        )
        DialogoVenda(opcao, parent=self).exec()

    def _buscar_item(self, item_id: int) -> dict | None:
        for sessao in historico.listar_historico_completo():
            for item in sessao["itens"]:
                if item["id"] == item_id:
                    return item
        return None

    def _animar_entrada(self, widget: QWidget):
        efeito = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(efeito)
        animacao = QPropertyAnimation(efeito, b"opacity", widget)
        animacao.setDuration(220)
        animacao.setStartValue(0.0)
        animacao.setEndValue(1.0)
        animacao.setEasingCurve(QEasingCurve.Type.OutCubic)
        animacao.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        widget._animacao_entrada_ref = animacao  # evita coleta de lixo prematura
