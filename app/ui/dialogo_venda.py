"""
Diálogo de preparação de venda no warframe.market.

Ao clicar no botão de venda (💱) no histórico, este diálogo abre. Ele consulta
o menor preço atual do warframe.market em background pra sugerir o valor,
e o usuário publica pelo navegador: o botão "Abrir página do item" copia
item/slug/preço/quantidade pra área de transferência e abre a página do item
(publicação automática pela API v2 está bloqueada — a API mudou de schema e
rejeita ordens, então o caminho oficial é pelo navegador).
"""
import asyncio
from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QDoubleSpinBox,
)

from app.dados.cliente_api import buscar_menor_preco_venda
from app.modelos import OpcaoRecompensa
from app.ui import tema
import httpx


class BuscadorPrecoThread(QThread):
    preco_obtido = Signal(float)

    def __init__(self, slug: str, parent=None):
        super().__init__(parent)
        self._slug = slug

    def run(self):
        try:
            async def _buscar():
                async with httpx.AsyncClient(timeout=10.0) as cliente:
                    return await buscar_menor_preco_venda(cliente, self._slug)
            preco = asyncio.run(_buscar())
            if preco is not None:
                self.preco_obtido.emit(preco)
        except Exception:
            pass


class DialogoVenda(QDialog):
    def __init__(self, opcao: OpcaoRecompensa, parent=None):
        super().__init__(parent)
        self._opcao = opcao

        self.setWindowTitle("Preparar venda no warframe.market")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        titulo = QLabel("Preparar venda no warframe.market")
        titulo.setProperty("data-role", "subtitulo")
        layout.addWidget(titulo)

        nome = QLabel(opcao.nome)
        nome.setWordWrap(True)
        nome.setStyleSheet(f"color: {tema.COR_PLATA}; font-weight: 600;")
        layout.addWidget(nome)

        if opcao.preco_plata is not None:
            sugerido = max(1.0, opcao.preco_plata)
        else:
            sugerido = 5.0

        linha_preco = QHBoxLayout()
        rotulo_preco = QLabel("Preço (platina)")
        rotulo_preco.setStyleSheet(f"color: {tema.COR_TEXTO_SECUNDARIO};")
        linha_preco.addWidget(rotulo_preco)
        linha_preco.addStretch(1)
        self.campo_preco = QDoubleSpinBox()
        self.campo_preco.setRange(1, 9999)
        self.campo_preco.setDecimals(0)
        self.campo_preco.setValue(sugerido)
        self.campo_preco.setSuffix("p")
        self.campo_preco.setFixedWidth(110)
        linha_preco.addWidget(self.campo_preco)
        layout.addLayout(linha_preco)

        linha_quantidade = QHBoxLayout()
        rotulo_qtd = QLabel("Quantidade")
        rotulo_qtd.setStyleSheet(f"color: {tema.COR_TEXTO_SECUNDARIO};")
        linha_quantidade.addWidget(rotulo_qtd)
        linha_quantidade.addStretch(1)
        self.campo_quantidade = QSpinBox()
        self.campo_quantidade.setRange(1, 999)
        self.campo_quantidade.setValue(1)
        self.campo_quantidade.setFixedWidth(110)
        linha_quantidade.addWidget(self.campo_quantidade)
        layout.addLayout(linha_quantidade)

        self.aviso = QLabel("Consultando preço atualizado na API...")
        self.aviso.setWordWrap(True)
        self.aviso.setStyleSheet(
            f"color: {tema.COR_ALERTA}; font-size: {tema.FONTE_PEQUENA}; "
            "background: rgba(224, 154, 111, 0.08); "
            "border: 1px solid rgba(224, 154, 111, 0.25); "
            "border-radius: 6px; padding: 8px 10px;"
        )
        layout.addWidget(self.aviso)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {tema.COR_MELHOR}; font-size: {tema.FONTE_PEQUENA};")
        layout.addWidget(self.status)

        botoes = QHBoxLayout()
        botoes.addStretch(1)
        self.botao_cancelar = QPushButton("Cancelar")
        self.botao_cancelar.clicked.connect(self.reject)
        # Abre a página do item no navegador padrão e já deixa no clipboard o
        # item/slug/preço/quantidade pra você colar direto no formulário de
        # venda do warframe.market. A publicação automática pela API v2 está
        # bloqueada (a API mudou o schema e rejeita ordens), então este é o
        # caminho oficial pra vender.
        self.botao_abrir_pagina = QPushButton("Abrir página do item")
        self.botao_abrir_pagina.setProperty("role", "primario")
        self.botao_abrir_pagina.setToolTip(
            "Abre a página do item no navegador e copia item/preço/quantidade "
            "pra área de transferência — você cola na hora de preencher a venda."
        )
        self.botao_abrir_pagina.clicked.connect(self._abrir_no_navegador)
        botoes.addWidget(self.botao_abrir_pagina)
        layout.addLayout(botoes)

        if opcao.slug is None:
            self.aviso.setText("Item não reconhecido — sem slug pra abrir a página.")
            self.botao_abrir_pagina.setEnabled(False)
        else:
            # Busca o preço real na API em background
            self._buscador = BuscadorPrecoThread(opcao.slug, self)
            self._buscador.preco_obtido.connect(self._ao_receber_preco_atual)
            self._buscador.start()

    def _ao_receber_preco_atual(self, preco: float):
        self.campo_preco.setValue(max(1.0, preco))
        self.aviso.setText(f"● Menor preço atual na API: {preco:.0f}p (sugerido).")

    def _abrir_no_navegador(self):
        """Copia os dados pra clipboard e abre a página do item no navegador.

        Formato do clipboard (uma linha por campo — pronto pra colar):
            Item: Saryn Prime Chassis Blueprint
            Slug: saryn_prime_chassis_blueprint
            Preço: 12p
            Quantidade: 1
        """
        if self._opcao.slug is None:
            self.status.setText(
                "▲ Este item não tem slug conhecido — não dá pra abrir a página."
            )
            self.status.setStyleSheet(
                f"color: {tema.COR_ALERTA}; font-size: {tema.FONTE_PEQUENA};"
                f"background: rgba(224, 154, 111, 0.08); "
                f"border: 1px solid rgba(224, 154, 111, 0.30); "
                f"border-radius: 6px; padding: 8px 10px;"
            )
            return

        preco = int(self.campo_preco.value())
        quantidade = int(self.campo_quantidade.value())
        texto_clipboard = (
            f"Item: {self._opcao.nome}\n"
            f"Slug: {self._opcao.slug}\n"
            f"Preço: {preco}p\n"
            f"Quantidade: {quantidade}\n"
        )
        QApplication.clipboard().setText(texto_clipboard)

        # Abre a página do item no navegador padrão do sistema. Como o
        # site não aceita pré-preenchimento via URL, abrimos na página
        # do item — o usuário clica em "Sell" e cola os dados do
        # clipboard nos campos.
        url = QUrl(f"https://warframe.market/items/{self._opcao.slug}")
        QDesktopServices.openUrl(url)

        self.status.setText(
            f"● Página aberta no navegador. Item/preço/quantidade copiados "
            f"({self._opcao.nome} · {preco}p · {quantidade}x) — cole no formulário."
        )
        self.status.setStyleSheet(
            f"color: {tema.COR_MELHOR}; font-size: {tema.FONTE_PEQUENA};"
            f"background: rgba(63, 219, 110, 0.10); "
            f"border: 1px solid rgba(63, 219, 110, 0.30); "
            f"border-radius: 6px; padding: 8px 10px;"
        )

    def closeEvent(self, evento):
        if hasattr(self, "_buscador") and self._buscador.isRunning():
            # quit() não interrompe o loop asyncio da thread; sem wait() o
            # QThread era destruído ainda rodando ("Destroyed while thread is
            # still running") e abortava o app.
            self._buscador.quit()
            self._buscador.wait()
        super().closeEvent(evento)

    def keyPressEvent(self, evento):
        if evento.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(evento)
