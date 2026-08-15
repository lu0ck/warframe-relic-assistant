"""
Liga as peças: hotkey pressionada -> captura tela -> OCR -> matching ->
mostra overlay -> salva no histórico se o usuário escolher um item.

Fica isolado num módulo próprio pra não inchar main.py nem as abas.
"""
from PySide6.QtCore import QObject, QTimer, Signal

from app import config
from app.captura.screenshot import (
    capturar_janela_do_jogo,
    recortar_faixa_dos_nomes,
    salvar_print_captura,
)
from app.captura.ocr import reconhecer_nomes_multiplos
from app.matching.comparador import reconhecer_todos
from app.matching.decisao import marcar_melhor_opcao
from app.modelos import OpcaoRecompensa
from app.dados import cache, historico
from app.ui.overlay_flutuante import OverlayFlutuante

MAX_ITENS_RELIGIA = 4  # uma abertura de relíquia mostra no máximo 4 recompensas


class FluxoDeCaptura(QObject):
    erro = Signal(str)

    def __init__(self, janela=None):
        super().__init__()
        self._janela = janela
        self._overlay_atual: OverlayFlutuante | None = None
        self._slot_embutido = None

    def _fechar_overlay_anterior(self):
        """Fecha e solta o overlay anterior antes de abrir um novo.

        Sem isso, um segundo disparo (ex.: Home apertado enquanto o auto-gatilho
        dispara) deixa o overlay velho visível com o timer rodando — e quando ele
        fecha sozinho emite `fechado`, salvando a sessão DE NOVO no histórico
        (linha duplicada). Desconectar os sinais antes de fechar evita esse-saving.
        """
        if self._overlay_atual is None:
            return
        try:
            self._overlay_atual.item_escolhido.disconnect()
            self._overlay_atual.fechado.disconnect()
        except RuntimeError:
            pass  # sinais já desconectados/destruídos
        self._overlay_atual.close()
        self._overlay_atual.deleteLater()
        self._overlay_atual = None

    def disparar(self):
        """Chamado pela hotkey. Roda tudo até mostrar o overlay."""
        try:
            self._fechar_overlay_anterior()

            nome_janela = cache.obter_config("nome_janela_jogo") or config.NOME_JANELA_JOGO
            indice_monitor = int(
                cache.obter_config("monitor_index", str(config.PADRAO_MONITOR_INDEX))
                or config.PADRAO_MONITOR_INDEX
            )
            duracao_segundos = int(
                cache.obter_config("duracao_overlay", str(config.PADRAO_DURACAO_OVERLAY_SEGUNDOS))
                or config.PADRAO_DURACAO_OVERLAY_SEGUNDOS
            )

            imagem, achou_janela = capturar_janela_do_jogo(
                nome_janela=nome_janela, indice_monitor_fallback=indice_monitor
            )
            if not achou_janela:
                self.erro.emit(
                    "Não encontrei a janela do Warframe (xdotool ausente ou nome da "
                    "janela diferente) — capturando o monitor inteiro como alternativa, "
                    "os recortes podem sair errados."
                )
            # Salva o print da tela de recompensa (pasta escolhida nas
            # Configurações) pra conferir depois se o OCR errou algo.
            salvar_print_captura(imagem)
            faixa = recortar_faixa_dos_nomes(imagem)
            textos = reconhecer_nomes_multiplos(faixa)
            reconhecidos = reconhecer_todos(textos)
            if not reconhecidos:
                self.erro.emit(
                    "Nada reconhecido na tela — confira se a tela de recompensa "
                    "está aberta e o jogo configurado em inglês."
                )
                return

            opcoes = [
                OpcaoRecompensa(
                    nome=r.nome_encontrado or f"(não reconhecido: {r.texto_ocr[:30]})",
                    preco_plata=r.preco_plata,
                    ducados=r.ducados,
                    slug=r.slug,
                )
                for r in reconhecidos
            ]
            opcoes = opcoes[:MAX_ITENS_RELIGIA]
            opcoes = marcar_melhor_opcao(opcoes)

            modo = cache.obter_config("modo_overlay", "Flutuante")
            y_frac = cache.obter_config("overlay_y_frac")
            try:
                y = float(y_frac) if y_frac is not None else config.PADRAO_OVERLAY_Y_FRAC
            except (TypeError, ValueError):
                y = config.PADRAO_OVERLAY_Y_FRAC

            # flag simples pra impedir que a sessão seja salva duas vezes: uma
            # ao clicar (item_escolhido) e outra ao fechar em seguida (fechado)
            estado = {"ja_registrado": False}

            def ao_escolher(opcao, ops=opcoes, estado=estado):
                estado["ja_registrado"] = True
                historico.salvar_sessao(ops, item_escolhido=opcao.nome)

            def ao_fechar(ops=opcoes, estado=estado):
                if not estado["ja_registrado"]:
                    historico.salvar_sessao(ops, item_escolhido=None)

            if modo == "Embutido na janela" and self._janela is not None:
                # Modo embutido: mostra os cards na aba Overlay da janela
                # principal e conecta o sinal de escolha para salvar histórico.
                aba = self._janela.aba_overlay
                if self._slot_embutido is not None:
                    try:
                        aba.recompensa_escolhida.disconnect(self._slot_embutido)
                    except (RuntimeError, TypeError):
                        pass
                self._slot_embutido = ao_escolher
                aba.recompensa_escolhida.connect(self._slot_embutido)
                token = aba.mostrar_recompensas(opcoes)
                # Auto-fecha como o overlay flutuante: depois da duração
                # configurada, registra a sessão (se nada foi clicado) e limpa
                # o painel. O token evita apagar uma captura mais nova.
                QTimer.singleShot(
                    duracao_segundos * 1000,
                    lambda: self._expiracao_embutido(aba, token, estado, ao_fechar),
                )
            else:
                self._overlay_atual = OverlayFlutuante(
                    opcoes,
                    indice_monitor=indice_monitor,
                    duracao_segundos=duracao_segundos,
                    y_frac=y,
                )
                self._overlay_atual.item_escolhido.connect(ao_escolher)
                self._overlay_atual.fechado.connect(ao_fechar)
                self._overlay_atual.show()
        except Exception as erro:
            self.erro.emit(str(erro))

    def _expiracao_embutido(self, aba, token, estado, ao_fechar):
        """Registra a sessão (se não escolheu) e limpa o painel embutido."""
        if not estado["ja_registrado"]:
            ao_fechar()
        aba.limpar_recompensas(token)
