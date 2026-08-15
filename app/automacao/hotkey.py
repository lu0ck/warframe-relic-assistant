"""
Hotkey global manual — dispara a captura durante a tela de recompensa.

Usa pynput.keyboard.Listener (não GlobalHotKeys, que é pra combinações tipo
ctrl+alt+h; aqui a ideia é uma tecla única, tipo Home). Isso precisa de uma
sessão X11 de verdade pra funcionar — não roda dentro de um sandbox sem tela.
"""
from pynput import keyboard


def resolver_tecla(nome: str):
    """
    Converte um nome de tecla em texto (ex: '<home>', 'f9', 'a') no objeto
    que o pynput espera. Teclas especiais usam <nome>; teclas de caractere
    único vão direto.
    """
    nome_limpo = nome.strip().strip("<>").lower()
    tecla_especial = getattr(keyboard.Key, nome_limpo, None)
    if tecla_especial is not None:
        return tecla_especial
    if len(nome_limpo) == 1:
        return keyboard.KeyCode.from_char(nome_limpo)
    raise ValueError(
        f"Tecla '{nome}' não reconhecida. Use um nome de tecla especial do pynput "
        f"(ex: '<home>', '<f9>') ou um único caractere (ex: 'j')."
    )


class OuvinteHotkey:
    def __init__(self, nome_tecla: str, callback):
        self._tecla_alvo = resolver_tecla(nome_tecla)
        self._callback = callback
        self._listener: keyboard.Listener | None = None

    def _ao_pressionar(self, tecla):
        if tecla == self._tecla_alvo:
            self._callback()

    def iniciar(self):
        self._listener = keyboard.Listener(on_press=self._ao_pressionar)
        self._listener.start()

    def parar(self):
        if self._listener:
            self._listener.stop()
            self._listener = None

    def reconfigurar(self, nome_tecla: str):
        """Troca a tecla alvo em tempo de execução (usado pela tela de configurações)."""
        nova_tecla = resolver_tecla(nome_tecla)
        ativo = self._listener is not None and self._listener.running
        if ativo:
            self.parar()
        self._tecla_alvo = nova_tecla
        if ativo:
            self.iniciar()
