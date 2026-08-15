"""
Roda a atualização diária de preços numa QThread separada, pra não travar a
UI. Expõe sinais de progresso e conclusão que a Aba 1 usa pra mostrar a
animação e o aviso de sucesso/falha (Fase 6).

O cancelamento é cooperativo: a thread expõe `cancelar()`, que sinaliza um
`threading.Event`; a rotina async checa esse sinal a cada item e interrompe
sem tocar no banco (o cache anterior fica intacto).
"""
import asyncio
import threading
from datetime import date

from PySide6.QtCore import QThread, Signal

from app.dados import cache
from app.dados.cliente_api import (
    CancelamentoAtualizacao,
    atualizar_tudo,
)


class AtualizadorThread(QThread):
    progresso = Signal(int, int)      # (itens_feitos, total_itens)
    concluido = Signal(bool, str)     # (sucesso, mensagem)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pedido_cancelamento = threading.Event()

    def cancelar(self):
        """Pede a interrupção da atualização (não bloqueia)."""
        self._pedido_cancelamento.set()

    def run(self):
        self._pedido_cancelamento.clear()
        try:
            def avisar_progresso(feito, total):
                self.progresso.emit(feito, total)

            # Ducados são fixos por item: só buscamos dos que ainda não temos
            # (evita gastar ~1 request por item a cada atualização).
            slugs_com_ducados = cache.obter_slugs_com_ducados()
            itens_prime, itens_mods = asyncio.run(atualizar_tudo(
                callback_progresso=avisar_progresso,
                slugs_com_ducados=slugs_com_ducados,
                deve_parar=self._pedido_cancelamento.is_set,
            ))
            total_prime = cache.salvar_itens(itens_prime)
            total_mods = cache.salvar_mods(itens_mods)
            cache.salvar_config("ultima_atualizacao_mods", date.today().isoformat())
            self.concluido.emit(
                True,
                f"Banco atualizado: {total_prime} peças Prime e {total_mods} mods",
            )
        except CancelamentoAtualizacao:
            self.concluido.emit(False, "Atualização cancelada — banco anterior mantido.")
        except Exception as erro:
            self.concluido.emit(False, f"Falha ao atualizar — usando cache anterior ({erro})")
