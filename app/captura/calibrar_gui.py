"""
Calibração visual da faixa de nomes — acabe com o chute de pixels.

Abra a imagem do jogo (captura da janela do Warframe, ou um arquivo) e
ARRASTE o mouse pra desenhar a faixa exatamente em cima dos nomes dos itens.
O OCR roda ao vivo: você vê na hora o que o recorte está lendo e quais itens
casaram no warframe.market. Ao salvar, a faixa fica gravada no banco
(tabela config) e o fluxo automático do jogo passa a usá-la sem reiniciar.

O widget `PainelCalibracao` também é reutilizado como a aba "Calibração" da
janela principal (app/ui/aba_calibracao.py) — o editor fica dentro do app.

Uso:
    python -m app.captura.calibrar_gui                 # captura a janela do jogo
    python -m app.captura.calibrar_gui --arquivo x.png # usa uma imagem salva
"""
import argparse
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.captura.screenshot import capturar_janela_do_jogo
from app.captura.ocr import reconhecer_nomes_multiplos
from app.config import obter_faixa_nomes_y
from app.dados import cache
from app.matching.comparador import reconhecer_todos


def pil_para_qpixmap(imagem) -> QPixmap:
    """Converte uma PIL Image RGB pra QPixmap (com cópia do buffer, segura)."""
    imagem = imagem.convert("RGB")
    dados = imagem.tobytes("raw", "RGB")
    qimagem = QImage(
        dados, imagem.width, imagem.height, imagem.width * 3,
        QImage.Format.Format_RGB888,
    )
    return QPixmap.fromImage(qimagem.copy())


class VisorDaImagem(QWidget):
    """Mostra a captura e deixa o usuário desenhar a faixa arrastando o mouse."""

    faixa_alterada = Signal(float, float)

    def __init__(self, imagem, parent=None):
        super().__init__(parent)
        self._imagem_pil = imagem
        self._pixmap = pil_para_qpixmap(imagem)
        self._y0 = 0.0
        self._y1 = 1.0
        self._arrastando = False
        self._borda = None
        self._ancora = 0.0
        self.setMinimumSize(600, 380)

    def definir_faixa(self, y0, y1, emitir=True):
        self._y0 = max(0.0, min(1.0, y0))
        self._y1 = max(0.0, min(1.0, y1))
        if self._y1 - self._y0 < 0.005:
            self._y1 = min(1.0, self._y0 + 0.005)
        self.update()
        if emitir:
            self.faixa_alterada.emit(self._y0, self._y1)

    def faixa_em_fracoes(self):
        return (self._y0, self._y1)

    # -- mapeamento entre display (widget) e imagem original ---------------
    def _fator_escala(self):
        largura, altura = self.width(), self.height()
        iw, ih = self._imagem_pil.size
        if largura <= 0 or altura <= 0 or iw <= 0 or ih <= 0:
            return 1.0
        return min(largura / iw, altura / ih)

    def _offset_vertical(self):
        fator = self._fator_escala()
        ih = self._imagem_pil.size[1]
        return (self.height() - ih * fator) / 2.0

    def _display_para_imagem(self, y_display):
        fator = self._fator_escala()
        return (y_display - self._offset_vertical()) / fator

    def _imagem_para_display(self, y_origem):
        fator = self._fator_escala()
        return self._offset_vertical() + y_origem * fator

    def _proporcao(self, y_origem):
        ih = self._imagem_pil.size[1]
        if ih <= 0:
            return 0.0
        return max(0.0, min(1.0, y_origem / ih))

    # -- desenho -----------------------------------------------------------
    def paintEvent(self, evento):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        fator = self._fator_escala()
        iw, ih = self._imagem_pil.size
        largura, altura = iw * fator, ih * fator
        x = (self.width() - largura) / 2.0
        y = self._offset_vertical()
        painter.drawPixmap(int(x), int(y), int(largura), int(altura), self._pixmap)

        y0 = self._imagem_para_display(self._y0 * ih)
        y1 = self._imagem_para_display(self._y1 * ih)
        cor_preenchimento = QColor(0, 140, 255, 70)
        painter.fillRect(0, int(y0), self.width(), max(1, int(y1 - y0)), cor_preenchimento)
        painter.setPen(QPen(QColor(0, 140, 255), 2))
        painter.drawLine(0, int(y0), self.width(), int(y0))
        painter.drawLine(0, int(y1), self.width(), int(y1))
        painter.end()

    # -- interação com o mouse ---------------------------------------------
    def mousePressEvent(self, evento):
        if evento.button() != Qt.MouseButton.LeftButton:
            return
        self._arrastando = True
        y = self._display_para_imagem(evento.position().y())
        ih = self._imagem_pil.size[1]
        y0 = self._y0 * ih
        y1 = self._y1 * ih
        margem = 12.0 / self._fator_escala()  # ~12px no display
        if abs(y - y0) <= margem:
            self._borda = "topo"
        elif abs(y - y1) <= margem:
            self._borda = "base"
        else:
            self._borda = "nova"
            self._ancora = y

    def mouseMoveEvent(self, evento):
        if not self._arrastando:
            return
        y = self._display_para_imagem(evento.position().y())
        ih = self._imagem_pil.size[1]

        if self._borda == "nova":
            novo0 = self._proporcao(min(self._ancora, y))
            novo1 = self._proporcao(max(self._ancora, y))
            if novo1 - novo0 >= 0.01:
                self.definir_faixa(novo0, novo1)
        elif self._borda == "topo":
            novo = self._proporcao(y)
            if novo < self._y1 - 0.005:
                self.definir_faixa(novo, self._y1)
        elif self._borda == "base":
            novo = self._proporcao(y)
            if novo > self._y0 + 0.005:
                self.definir_faixa(self._y0, novo)

    def mouseReleaseEvent(self, evento):
        self._arrastando = False


class PainelCalibracao(QWidget):
    """
    Editor da faixa de nomes: visor arrastável + OCR ao vivo + ajuste fino.
    Reutilizável — embutido na janela principal (aba "Calibração") e na
    JanelaCalibracao standalone.
    """

    faixa_salva = Signal(float, float)
    fechar_pedido = Signal()

    def __init__(self, imagem, achou_janela=True, mostrar_botao_fechar=False, parent=None):
        super().__init__(parent)
        self._imagem = imagem

        layout_geral = QHBoxLayout(self)
        self._layout_geral = layout_geral

        self.visor = VisorDaImagem(imagem)
        layout_geral.addWidget(self.visor, 3)

        painel = QWidget()
        layout_painel = QVBoxLayout(painel)
        layout_painel.setSpacing(8)
        layout_geral.addWidget(painel, 1)

        self._rotulo_imagem = QLabel(f"Imagem: {imagem.size[0]}x{imagem.size[1]}")
        self._rotulo_faixa = QLabel("Faixa: -")
        layout_painel.addWidget(self._rotulo_imagem)
        layout_painel.addWidget(self._rotulo_faixa)

        self._aviso_monitor = QLabel(
            "▲ Captura do MONITOR INTEIRO (janela do Warframe não encontrada).\n"
            "Isso só serve pra testar — o layout é diferente da janela do jogo.\n"
            "Para calibrar de verdade: abra o Warframe na tela de recompensa "
            "(ou use a aba Calibração com o jogo aberto)."
        )
        self._aviso_monitor.setStyleSheet(
            "background-color: rgba(224, 111, 122, 0.12); "
            "color: #e09a8f; padding: 10px 12px; border-radius: 6px; "
            "border: 1px solid rgba(224, 111, 122, 0.35);"
        )
        self._aviso_monitor.setWordWrap(True)
        self._aviso_monitor.hide()
        layout_painel.addWidget(self._aviso_monitor)

        instrucoes = QLabel(
            "Arraste o mouse pra desenhar a faixa sobre os nomes dos itens.\n"
            "Clicar perto de uma borda ajusta só ela.\n"
            "Clicar no meio cria uma faixa nova. Ctrl+S salva."
        )
        instrucoes.setWordWrap(True)
        layout_painel.addWidget(instrucoes)

        grupo_ajuste = QGroupBox("Ajuste fino (px)")
        formulario = QFormLayout(grupo_ajuste)
        formulario.addRow("Topo:", self._linha_de_nudges("topo"))
        formulario.addRow("Base:", self._linha_de_nudges("base"))
        layout_painel.addWidget(grupo_ajuste)

        linha_botoes = QHBoxLayout()
        self._botao_testar = QPushButton("Testar OCR")
        self._botao_testar.clicked.connect(self._atualizar_ocr)
        self._botao_salvar = QPushButton("Salvar faixa")
        self._botao_salvar.clicked.connect(self._salvar)
        linha_botoes.addWidget(self._botao_testar)
        linha_botoes.addWidget(self._botao_salvar)
        if mostrar_botao_fechar:
            self._botao_fechar = QPushButton("Fechar")
            self._botao_fechar.clicked.connect(self.fechar_pedido.emit)
            linha_botoes.addWidget(self._botao_fechar)
        layout_painel.addLayout(linha_botoes)

        self._resultados = QTextEdit()
        self._resultados.setReadOnly(True)
        self._resultados.setFont(QFont("monospace", 9))
        layout_painel.addWidget(self._resultados, 1)

        # OCR ao vivo com debounce (rodar a cada movimento do mouse é lento).
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._atualizar_ocr)
        self.visor.faixa_alterada.connect(self._na_faixa_alterada)

        atalho_salvar = QShortcut(QKeySequence("Ctrl+S"), self)
        atalho_salvar.activated.connect(self._salvar)

        self._aplicar_aviso(achou_janela)
        # começa com a faixa salva (ou a padrão/interpolada pra esta janela)
        self.visor.definir_faixa(*obter_faixa_nomes_y(imagem.size[0] / imagem.size[1]))
        self._na_faixa_alterada(self.visor.faixa_em_fracoes()[0], self.visor.faixa_em_fracoes()[1])
        self._debounce.start()

    def _aplicar_aviso(self, achou_janela: bool):
        self._aviso_monitor.setVisible(not achou_janela)

    def definir_imagem(self, imagem, achou_janela=True):
        """Troca a imagem em exibição (usado quando o usuário captura de novo)."""
        self._imagem = imagem
        indice = self._layout_geral.indexOf(self.visor)
        visor_novo = VisorDaImagem(imagem)
        visor_novo.faixa_alterada.connect(self._na_faixa_alterada)
        if indice >= 0:
            self._layout_geral.takeAt(indice).widget().deleteLater()
            self._layout_geral.insertWidget(indice, visor_novo, 3)
        else:
            self._layout_geral.addWidget(visor_novo, 3)
        self.visor = visor_novo

        self._rotulo_imagem.setText(f"Imagem: {imagem.size[0]}x{imagem.size[1]}")
        self._aplicar_aviso(achou_janela)
        self._resultados.clear()
        self.visor.definir_faixa(*obter_faixa_nomes_y(imagem.size[0] / imagem.size[1]))
        self._debounce.start()

    def _linha_de_nudges(self, qual):
        linha = QHBoxLayout()
        for passo in (5, 1):
            botao_menos = QPushButton(f"-{passo}")
            botao_mais = QPushButton(f"+{passo}")
            botao_menos.clicked.connect(lambda _=False, q=qual, p=passo: self._nudge(q, -p))
            botao_mais.clicked.connect(lambda _=False, q=qual, p=passo: self._nudge(q, p))
            linha.addWidget(botao_menos)
            linha.addWidget(botao_mais)
        return linha

    def _nudge(self, qual, passo_px):
        altura = self._imagem.size[1]
        y0, y1 = self.visor.faixa_em_fracoes()
        delta = passo_px / altura if altura else 0.0
        if qual == "topo":
            y0 = max(0.0, min(y1 - 0.005, y0 + delta))
        else:
            y1 = min(1.0, max(y0 + 0.005, y1 + delta))
        self.visor.definir_faixa(y0, y1)

    def _na_faixa_alterada(self, y0, y1):
        altura = self._imagem.size[1]
        self._rotulo_faixa.setText(
            f"Faixa: y {round(y0 * altura)}..{round(y1 * altura)}  ({y0:.4f}, {y1:.4f})"
        )
        self._debounce.start()

    def _atualizar_ocr(self):
        y0, y1 = self.visor.faixa_em_fracoes()
        altura = self._imagem.size[1]
        faixa = self._imagem.crop(
            (0, int(altura * y0), self._imagem.size[0], int(altura * y1))
        )
        textos = reconhecer_nomes_multiplos(faixa)
        linhas = [f"— {len(textos)} item(ns) reconhecido(s) —"]
        for texto in textos:
            linhas.append(f"  OCR: {texto!r}")
        for resultado in reconhecer_todos(textos):
            if resultado.nome_encontrado is None:
                linhas.append(f"  sem match ({resultado.confianca:.0f}%)")
            else:
                preco = f"{resultado.preco_plata:.1f}p" if resultado.preco_plata is not None else "-"
                ducados = f"{resultado.ducados} duc" if resultado.ducados is not None else "-"
                linhas.append(
                    f"  -> {resultado.nome_encontrado} | {preco} | {ducados} | "
                    f"{resultado.confianca:.0f}%"
                )
        self._resultados.setPlainText("\n".join(linhas))

    def _salvar(self):
        y0, y1 = self.visor.faixa_em_fracoes()
        altura = self._imagem.size[1]
        largura = self._imagem.size[0]
        cache.salvar_config("faixa_nomes_y", f"{y0:.4f},{y1:.4f}")
        # guarda a proporção da janela usada, pra não aplicar essa calibração
        # numa janela de tamanho diferente (a posição dos nomes muda com ela)
        cache.salvar_config("faixa_nomes_proporcao", f"{largura / altura:.4f}")
        self.faixa_salva.emit(y0, y1)
        QMessageBox.information(
            self,
            "Faixa salva",
            f"Faixa salva: y {round(y0 * altura)}..{round(y1 * altura)} "
            f"({y0:.4f}, {y1:.4f})\n\nVale pro fluxo automático do jogo "
            f"sem reiniciar o app.",
        )


class JanelaCalibracao(QWidget):
    """Versão standalone (via `python -m app.captura.calibrar_gui`)."""

    def __init__(self, imagem, achou_janela=True):
        super().__init__()
        self.setWindowTitle("Calibração da faixa de nomes")
        self.resize(1200, 700)

        layout = QVBoxLayout(self)
        self.painel = PainelCalibracao(
            imagem, achou_janela=achou_janela, mostrar_botao_fechar=True
        )
        self.painel.fechar_pedido.connect(self.close)
        layout.addWidget(self.painel)


def main():
    parser = argparse.ArgumentParser(description="Calibração visual da faixa de nomes")
    parser.add_argument(
        "--arquivo", type=str, default=None,
        help="usar uma imagem salva em vez de capturar a tela",
    )
    args = parser.parse_args()

    if args.arquivo:
        from PIL import Image

        imagem = Image.open(args.arquivo).convert("RGB")
        achou_janela = True
    else:
        imagem, achou_janela = capturar_janela_do_jogo()

    app = QApplication(sys.argv)
    janela = JanelaCalibracao(imagem, achou_janela=achou_janela)
    janela.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
