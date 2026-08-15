import signal
import sys

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from app import config
from app.dados import cache
from app.ui.janela_principal import ABA_CONFIGURACAO, JanelaPrincipal
from app.ui.bandeja import Bandeja, icone_app
from app.ui.tema import aplicar_tema
from app.automacao.hotkey import OuvinteHotkey
from app.automacao.fluxo_captura import FluxoDeCaptura
from app.automacao.leitor_log import LeitorDeLog


class PonteHotkey(QObject):
    """
    O listener de teclado roda numa thread própria do pynput, não na thread
    do Qt — então não pode chamar direto código de UI. Esse objeto existe só
    pra repassar o disparo pra thread principal via signal/slot do Qt, que já
    cuida da fila entre threads sozinho.
    """
    disparado = Signal()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(config.NOME_APP)
    app.setWindowIcon(icone_app())
    aplicar_tema(app)

    cache.criar_tabelas()

    # Concilia os ✓ do histórico com o inventário geral: sessões gravadas por
    # versões antigas do app registraram o item escolhido sem adicioná-lo ao
    # inventário. Rodar sempre no startup é barato (no máximo uma checagem por
    # item marcado) e conserta retroativamente.
    reconciliados = cache.reconciliar_escolhidos()
    if reconciliados:
        print(
            f"Conciliação do inventário: {reconciliados} item(ns) marcado(s) "
            "✓ adicionado(s) ao inventário geral."
        )

    janela = JanelaPrincipal()
    janela.show()
    janela.aba_overlay.verificar_e_atualizar_se_necessario()

    fluxo = FluxoDeCaptura(janela=janela)
    fluxo.erro.connect(lambda msg: janela.aba_overlay.status_cache.setText(f"▲ Erro na captura: {msg}"))

    def ao_recompensa_no_log(_linha):
        # A tela abre e o texto demora um instante pra renderizar: captura
        # só depois do atraso, pra não fotografar a animação de entrada.
        atraso = cache.obter_config(
            "atraso_captura_apos_abertura", config.PADRAO_ATRASO_CAPTURA_APOS_ABERTURA_SEG
        )
        try:
            atraso = float(atraso)
        except (TypeError, ValueError):
            atraso = config.PADRAO_ATRASO_CAPTURA_APOS_ABERTURA_SEG
        QTimer.singleShot(int(atraso * 1000), fluxo.disparar)

    leitor_log = LeitorDeLog()
    leitor_log.recompensa_detectada.connect(ao_recompensa_no_log)
    leitor_log.erro.connect(
        lambda msg: print(f"Aviso: problema no EE.log ({msg}). Use o hotkey se o gatilho automático não disparar.")
    )

    def atualizar_gatilho():
        """Liga/desliga o gatilho automático conforme a configuração (vale na
        hora, inclusive se o caminho do EE.log mudar nas Configurações)."""
        nonlocal leitor_log
        gatilho_auto = cache.obter_config(
            "gatilho_automatico", config.PADRAO_GATILHO_AUTOMATICO_LIGADO
        )
        leitor_log.parar()
        if str(gatilho_auto) in ("0", "false", "False"):
            return
        leitor_log = LeitorDeLog()
        leitor_log.recompensa_detectada.connect(ao_recompensa_no_log)
        leitor_log.erro.connect(
            lambda msg: print(f"Aviso: problema no EE.log ({msg}). Use o hotkey se o gatilho automático não disparar.")
        )
        leitor_log.iniciar()

    atualizar_gatilho()

    ponte = PonteHotkey()
    ponte.disparado.connect(fluxo.disparar)

    def iniciar_ouvinte():
        nonlocal ouvinte
        try:
            if ouvinte is not None:
                ouvinte.parar()
            hotkey = cache.obter_config("hotkey", config.PADRAO_HOTKEY) or config.PADRAO_HOTKEY
            ouvinte = OuvinteHotkey(hotkey, lambda: ponte.disparado.emit())
            ouvinte.iniciar()
        except Exception as erro:
            print(f"Aviso: não foi possível iniciar o listener de hotkey ({erro}).")
            print("Isso é esperado em ambientes sem X11 (ex: sandbox de teste).")

    ouvinte = None
    janela.aba_configuracao.salvo.connect(
        lambda _hotkey: (iniciar_ouvinte(), atualizar_gatilho())
    )

    def ao_abrir():
        janela.showNormal()
        janela.raise_()
        janela.activateWindow()

    def ao_configurar():
        janela.abrir_na_aba(ABA_CONFIGURACAO)

    def ao_sair():
        # Fechar a janela encerra o app (closeEvent aceita e para as threads).
        janela.close()

    tray = Bandeja(
        ao_abrir=ao_abrir,
        ao_atualizar=janela.aba_overlay.iniciar_atualizacao,
        ao_configurar=ao_configurar,
        ao_sair=ao_sair,
    )
    tray.mostrar()

    iniciar_ouvinte()

    # O loop de eventos do Qt prende a thread principal e o Ctrl+C do terminal
    # fica "pendente" (o handler Python só roda ao executar bytecode). Restaurar
    # o comportamento padrão do SIGINT faz o ^C encerrar o processo na hora.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
