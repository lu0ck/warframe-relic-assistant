"""
Fase D — gatilho automático via EE.log do Warframe.

O jogo (via Proton/Steam) escreve constantemente no arquivo EE.log. Quando a
tela de escolha de recompensa de uma relíquia abre, ele registra:

    Sys [Info]: VoidProjections: OpenVoidProjectionRewardScreenRMI

Essa classe fica numa thread própria "seguindo" o final do arquivo e emite um
signal quando essa linha aparece — o fluxo de captura roda então sozinho, sem
o usuário precisar apertar o hotkey.
"""
import os
import threading
import time

from PySide6.QtCore import QObject, Signal

from app import config


class LeitorDeLog(QObject):
    """Observa o EE.log em segundo plano e avisa quando a recompensa abre."""

    recompensa_detectada = Signal(str)
    erro = Signal(str)

    def __init__(self, caminho=None, linha_alvo=None, parent=None):
        super().__init__(parent)
        self._caminho = caminho or config.obter_caminho_ee_log()
        self._linha_alvo = linha_alvo or config.LINHA_ABERTURA_RECOMPENSA
        self._rodando = False
        self._thread = None
        self._inode = None

    def iniciar(self):
        if self._rodando:
            return
        self._rodando = True
        self._thread = threading.Thread(target=self._vigiar, daemon=True)
        self._thread.start()

    def parar(self):
        self._rodando = False
        # Espera a thread de leitura encerrar (curta: dorme 0,5s no pior caso)
        # — senão um parar()+iniciar() rápido deixava as duas rodando e a velha
        # podia emitir um gatilho fantasma antes de morrer.
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _vigiar(self):
        offset: int | None = None
        erro_avisado = False
        while self._rodando:
            try:
                if self._caminho is None:
                    if not erro_avisado:
                        self.erro.emit(
                            "Caminho do EE.log não encontrado. Configure-o nas "
                            "Configurações ou pela variável WF_EE_LOG_PATH."
                        )
                        erro_avisado = True
                    time.sleep(2.0)
                    continue
                if offset is None:
                    offset = self._posicao_inicial()
                    erro_avisado = False
                offset = self._ler_novos(offset)
            except FileNotFoundError:
                # app abriu antes do Warframe: o log ainda não existe (o jogo
                # o cria/recria ao iniciar). Espera e tenta de novo em vez de
                # desistir — antes o leitor morria de vez nesse caso.
                if not erro_avisado:
                    self.erro.emit("EE.log ainda não existe — aguardando o jogo criá-lo.")
                    erro_avisado = True
                offset = None
                time.sleep(2.0)
                continue
            except Exception as erro:  # log pode rotacionar/ficar inacessível
                if not erro_avisado:
                    self.erro.emit(str(erro))
                    erro_avisado = True
                offset = None  # reconstrói a posição quando o arquivo voltar
                time.sleep(2.0)
                continue
            time.sleep(0.5)

    def _posicao_inicial(self):
        # Começa do fim do arquivo pra não reprocessar o histórico inteiro.
        with open(self._caminho, "r", errors="replace") as arquivo:
            arquivo.seek(0, os.SEEK_END)
            self._inode = os.fstat(arquivo.fileno()).st_ino
            return arquivo.tell()

    def _ler_novos(self, offset):
        info = os.stat(self._caminho)
        # Se o arquivo foi RECRIADO (inode mudou — Proton faz isso quando o
        # jogo reinicia) ou encolheu (truncado), a posição guardada não vale
        # mais: volta pro início pra não perder a linha alvo do novo log.
        if self._inode is not None and info.st_ino != self._inode:
            self._inode = info.st_ino
            offset = 0
        elif offset > info.st_size:
            offset = 0
        with open(self._caminho, "r", errors="replace") as arquivo:
            arquivo.seek(offset)
            linhas = arquivo.readlines()
            novo_offset = arquivo.tell()

        for linha in linhas:
            if self._linha_alvo in linha:
                self.recompensa_detectada.emit(linha.strip())
        return novo_offset
