"""
Calibração visual da área da grade do inventário (tela "Inventory/Sell").

Diferente da faixa de nomes (que é só uma faixa horizontal), a grade do
inventário ocupa um RETÂNGULO da janela — abra a imagem (captura ao vivo ou
arquivo) e ARRASTE o mouse pra demarcar o retângulo que cobre a grade inteira
visível. Ao salvar, a área fica gravada na tabela `config` e a varredura do
inventário passa a recortar exatamente ali.

O widget `PainelCalibracaoInventario` é reutilizado na aba "Inventário" da
janela principal (app/ui/aba_inventario.py).

Uso:
    python -m app.captura.calibrar_inventario_gui                 # captura a janela do jogo
    python -m app.captura.calibrar_inventario_gui --arquivo x.png # usa uma imagem salva
"""
import argparse
import sys
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.captura.calibrar_gui import pil_para_qpixmap
from app.captura.calibrar_inventario import (
    CHAVE_GRADE_INVENTARIO,
    CHAVE_GRADE_PROPORCAO,
    obter_grade_inventario,
)
from app.captura.screenshot import capturar_janela_do_jogo
from app.dados import cache

MIN_AREA_FRAC = 0.01  # área mínima do retângulo (frações da imagem)

INSTRUCOES_PADRAO = (
    "Arraste o mouse pra desenhar o retângulo sobre a GRADE inteira "
    "do inventário (todas as colunas visíveis).\n\n"
    "Clicar perto de uma borda ajusta só ela; clicar no meio cria um "
    "retângulo novo. Ctrl+S salva.\n\n"
    "Deixe o Warframe aberto na tela de vendas/Inventory antes de "
    "capturar."
)


class VisorRetangular(QWidget):
    """Mostra a captura e deixa o usuário desenhar o retângulo da grade."""

    area_alterada = Signal(float, float, float, float)  # x0, y0, x1, y1

    def __init__(self, imagem, parent=None):
        super().__init__(parent)
        self._imagem_pil = imagem
        self._pixmap = pil_para_qpixmap(imagem)
        self._x0, self._y0, self._x1, self._y1 = 0.0, 0.0, 1.0, 1.0
        self._arrastando = False
        self._borda = None  # "esq" | "dir" | "topo" | "base" | "nova"
        self._ancora = (0.0, 0.0)
        self.setMinimumSize(600, 380)

    def definir_area(self, x0, y0, x1, y1, emitir=True):
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        self._x0 = max(0.0, min(1.0, x0))
        self._y0 = max(0.0, min(1.0, y0))
        self._x1 = max(0.0, min(1.0, x1))
        self._y1 = max(0.0, min(1.0, y1))
        if self._x1 - self._x0 < MIN_AREA_FRAC:
            self._x1 = min(1.0, self._x0 + MIN_AREA_FRAC)
        if self._y1 - self._y0 < MIN_AREA_FRAC:
            self._y1 = min(1.0, self._y0 + MIN_AREA_FRAC)
        self.update()
        if emitir:
            self.area_alterada.emit(self._x0, self._y0, self._x1, self._y1)

    def area_em_fracoes(self):
        return (self._x0, self._y0, self._x1, self._y1)

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

    def _offset_horizontal(self):
        fator = self._fator_escala()
        iw = self._imagem_pil.size[0]
        return (self.width() - iw * fator) / 2.0

    def _display_para_imagem(self, x_display, y_display):
        fator = self._fator_escala()
        return (
            (x_display - self._offset_horizontal()) / fator,
            (y_display - self._offset_vertical()) / fator,
        )

    def _imagem_para_display(self, x_origem, y_origem):
        fator = self._fator_escala()
        return (
            self._offset_horizontal() + x_origem * fator,
            self._offset_vertical() + y_origem * fator,
        )

    def _proporcao(self, x_origem, y_origem):
        iw, ih = self._imagem_pil.size
        if iw <= 0 or ih <= 0:
            return 0.0, 0.0
        return (
            max(0.0, min(1.0, x_origem / iw)),
            max(0.0, min(1.0, y_origem / ih)),
        )

    # -- desenho -----------------------------------------------------------
    def paintEvent(self, evento):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        fator = self._fator_escala()
        iw, ih = self._imagem_pil.size
        largura, altura = iw * fator, ih * fator
        x = self._offset_horizontal()
        y = self._offset_vertical()
        painter.drawPixmap(int(x), int(y), int(largura), int(altura), self._pixmap)

        x0, y0 = self._imagem_para_display(self._x0 * iw, self._y0 * ih)
        x1, y1 = self._imagem_para_display(self._x1 * iw, self._y1 * ih)
        cor_preenchimento = QColor(0, 140, 255, 60)
        painter.fillRect(
            int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0)),
            cor_preenchimento,
        )
        painter.setPen(QPen(QColor(0, 140, 255), 2))
        painter.drawRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
        painter.end()

    # -- interação com o mouse ---------------------------------------------
    def mousePressEvent(self, evento):
        if evento.button() != Qt.MouseButton.LeftButton:
            return
        self._arrastando = True
        ix, iy = self._display_para_imagem(evento.position().x(), evento.position().y())
        iw, ih = self._imagem_pil.size
        margem = 12.0 / self._fator_escala()  # ~12px no display
        x0, y0 = self._x0 * iw, self._y0 * ih
        x1, y1 = self._x1 * iw, self._y1 * ih
        if abs(ix - x0) <= margem:
            self._borda = "esq"
        elif abs(ix - x1) <= margem:
            self._borda = "dir"
        elif abs(iy - y0) <= margem:
            self._borda = "topo"
        elif abs(iy - y1) <= margem:
            self._borda = "base"
        else:
            self._borda = "nova"
            self._ancora = (ix, iy)

    def mouseMoveEvent(self, evento):
        if not self._arrastando:
            return
        ix, iy = self._display_para_imagem(evento.position().x(), evento.position().y())
        iw, ih = self._imagem_pil.size
        px0, py0, px1, py1 = self._x0 * iw, self._y0 * ih, self._x1 * iw, self._y1 * ih
        tam_min = MIN_AREA_FRAC * min(iw, ih)

        if self._borda == "nova":
            ax, ay = self._ancora
            nx0, ny0 = self._proporcao(min(ax, ix), min(ay, iy))
            nx1, ny1 = self._proporcao(max(ax, ix), max(ay, iy))
            if (nx1 - nx0) >= MIN_AREA_FRAC and (ny1 - ny0) >= MIN_AREA_FRAC:
                self.definir_area(nx0, ny0, nx1, ny1)
        elif self._borda == "esq":
            novo = self._proporcao(min(ix, px1 - tam_min), iy)[0]
            self.definir_area(novo, self._y0, self._x1, self._y1)
        elif self._borda == "dir":
            novo = self._proporcao(max(ix, px0 + tam_min), iy)[0]
            self.definir_area(self._x0, self._y0, novo, self._y1)
        elif self._borda == "topo":
            novo = self._proporcao(ix, min(iy, py1 - tam_min))[1]
            self.definir_area(self._x0, novo, self._x1, self._y1)
        elif self._borda == "base":
            novo = self._proporcao(ix, max(iy, py0 + tam_min))[1]
            self.definir_area(self._x0, self._y0, self._x1, novo)

    def mouseReleaseEvent(self, evento):
        self._arrastando = False


class PainelCalibracaoInventario(QWidget):
    """Editor da área da grade: visor retangular arrastável + salvar.

    Reutilizável — embutido na aba "Inventário" da janela principal, na
    JanelaCalibracaoInventario standalone e na aba "Mods" (parâmetros
    chave_area/chave_proporcao/obter_area/titulo_area/instrucoes).
    """

    area_salva = Signal()
    fechar_pedido = Signal()

    def __init__(
        self,
        imagem,
        mostrar_botao_fechar=False,
        parent=None,
        chave_area=CHAVE_GRADE_INVENTARIO,
        chave_proporcao=CHAVE_GRADE_PROPORCAO,
        obter_area=obter_grade_inventario,
        titulo_area="grade do inventário",
        instrucoes=INSTRUCOES_PADRAO,
    ):
        super().__init__(parent)
        self._imagem = imagem
        self._chave_area = chave_area
        self._chave_proporcao = chave_proporcao
        self._obter_area = obter_area
        self._titulo_area = titulo_area

        layout_geral = QHBoxLayout(self)
        self._layout_geral = layout_geral

        self.visor = VisorRetangular(imagem)
        layout_geral.addWidget(self.visor, 3)

        painel = QWidget()
        layout_painel = QVBoxLayout(painel)
        layout_painel.setSpacing(8)
        layout_geral.addWidget(painel, 1)

        self._rotulo_imagem = QLabel(f"Imagem: {imagem.size[0]}x{imagem.size[1]}")
        self._rotulo_area = QLabel("Área: -")
        layout_painel.addWidget(self._rotulo_imagem)
        layout_painel.addWidget(self._rotulo_area)

        instrucoes = QLabel(instrucoes)
        instrucoes.setWordWrap(True)
        layout_painel.addWidget(instrucoes)

        linha_botoes = QHBoxLayout()
        self._botao_salvar = QPushButton("Salvar área")
        self._botao_salvar.setProperty("role", "primario")
        self._botao_salvar.clicked.connect(self._salvar)
        linha_botoes.addWidget(self._botao_salvar)
        if mostrar_botao_fechar:
            self._botao_fechar = QPushButton("Fechar")
            self._botao_fechar.clicked.connect(self.fechar_pedido.emit)
            linha_botoes.addWidget(self._botao_fechar)
        layout_painel.addLayout(linha_botoes)

        atalho_salvar = QShortcut(QKeySequence("Ctrl+S"), self)
        atalho_salvar.activated.connect(self._salvar)

        self.visor.area_alterada.connect(self._na_area_alterada)
        self._definir_area_inicial()
        self._na_area_alterada(*self.visor.area_em_fracoes())

    def _definir_area_inicial(self):
        """Começa com a área salva (ou a janela inteira, se ainda não houver)."""
        salva = self._obter_area()
        if salva:
            self.visor.definir_area(*salva, emitir=False)
        else:
            self.visor.definir_area(0.0, 0.0, 1.0, 1.0, emitir=False)

    def definir_imagem(self, imagem):
        """Troca a imagem em exibição (usado quando o usuário captura de novo)."""
        self._imagem = imagem
        indice = self._layout_geral.indexOf(self.visor)
        visor_novo = VisorRetangular(imagem)
        visor_novo.area_alterada.connect(self._na_area_alterada)
        if indice >= 0:
            self._layout_geral.takeAt(indice).widget().deleteLater()
            self._layout_geral.insertWidget(indice, visor_novo, 3)
        else:
            self._layout_geral.addWidget(visor_novo, 3)
        self.visor = visor_novo

        self._rotulo_imagem.setText(f"Imagem: {imagem.size[0]}x{imagem.size[1]}")
        self._definir_area_inicial()
        self._na_area_alterada(*self.visor.area_em_fracoes())

    def _na_area_alterada(self, x0, y0, x1, y1):
        iw, ih = self._imagem.size
        self._rotulo_area.setText(
            f"Área: x {round(x0 * iw)}..{round(x1 * iw)} · "
            f"y {round(y0 * ih)}..{round(y1 * ih)}  "
            f"({x0:.3f}, {y0:.3f}, {x1:.3f}, {y1:.3f})"
        )

    def _salvar(self):
        x0, y0, x1, y1 = self.visor.area_em_fracoes()
        iw, ih = self._imagem.size
        cache.salvar_config(self._chave_area, f"{x0:.4f},{y0:.4f},{x1:.4f},{y1:.4f}")
        cache.salvar_config(self._chave_proporcao, f"{iw / ih:.4f}")
        self.area_salva.emit()
        QMessageBox.information(
            self,
            "Área salva",
            f"Área da grade salva: x {round(x0 * iw)}..{round(x1 * iw)} · "
            f"y {round(y0 * ih)}..{round(y1 * ih)}\n\n"
            f"A varredura passa a recortar essa área da janela "
            f"({self._titulo_area}).",
        )


class JanelaCalibracaoInventario(QWidget):
    """Versão standalone (via `python -m app.captura.calibrar_inventario_gui`)."""

    def __init__(self, imagem, achou_janela=True):
        super().__init__()
        self.setWindowTitle("Calibração da área do inventário")
        self.resize(1200, 700)

        layout = QVBoxLayout(self)
        self.painel = PainelCalibracaoInventario(
            imagem, mostrar_botao_fechar=True
        )
        self.painel.fechar_pedido.connect(self.close)
        layout.addWidget(self.painel)


def main():
    parser = argparse.ArgumentParser(description="Calibração visual da área do inventário")
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
        print(
            "Capturando em 3 segundos... deixe a tela de vendas/Inventory "
            "do Warframe visível!"
        )
        time.sleep(3)
        imagem, achou_janela = capturar_janela_do_jogo()

    app = QApplication(sys.argv)
    janela = JanelaCalibracaoInventario(imagem, achou_janela=achou_janela)
    janela.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
