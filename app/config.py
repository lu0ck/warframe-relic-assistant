"""
Configurações e caminhos centrais do projeto.
Nenhum outro módulo deve montar caminho de arquivo na mão — sempre importar daqui.
"""
import os
from pathlib import Path

# Raiz do projeto (pasta que contém a pasta app/)
RAIZ_PROJETO = Path(__file__).resolve().parent.parent

# Onde ficam os dados que persistem entre execuções (banco, config do usuário)
PASTA_DADOS = RAIZ_PROJETO / "dados_locais"
PASTA_DADOS.mkdir(exist_ok=True)

CAMINHO_BANCO = PASTA_DADOS / "cache.db"

# Nome do app, usado em janelas/notificações
NOME_APP = "Assistente de Relíquias"

# Pasta padrão pros prints automáticos de cada captura da tela de recompensa
# (o usuário pode trocar nas Configurações). Pasta padrão: junto dos dados.
PADRAO_PASTA_PRINTS = PASTA_DADOS / "prints"

# Configurações padrão (usadas na primeira execução, antes de existir a tabela `config`)
PADRAO_HOTKEY = "<home>"
PADRAO_MONITOR_INDEX = 1  # no mss: 0 = todos combinados, 1 = monitor primário real
PADRAO_DURACAO_OVERLAY_SEGUNDOS = 12
# Posição vertical do overlay no monitor (fração da altura; 0.0=topo, 1.0=base).
# 0.35 deixa o overlay no terço superior do monitor — longe do clutter do jogo
# e mais perto dos itens visíveis.
PADRAO_OVERLAY_Y_FRAC = 0.35
# A API do warframe.market (v2) só devolve nomes de itens em inglês, então o
# OCR do jogo precisa estar lendo nomes em inglês (jogo configurado em EN)
# pra o fuzzy matching casar com confiança.

# API do warframe.market (v2 — usada pelo cliente em app/dados/cliente_api.py)
API_REQS_POR_SEGUNDO = 3  # limite documentado da API — nunca ultrapassar

# ---------------------------------------------------------------------------
# Região de recorte da tela de recompensa (Fase 2)
# Valores em PORCENTAGEM da JANELA DO JOGO (não da tela inteira!) — 0.0 a 1.0.
# A posição dos nomes muda conforme o TAMANHO da janela, então a faixa usada é
# decidida pela proporção da janela capturada (ver faixa_para_proporcao).
# Este padrão vale pra janela atual validada (1600x828); o calibrador (aba
# "Calibração") grava no banco a faixa exata da janela em uso.
# ---------------------------------------------------------------------------
FAIXA_NOMES_Y = (0.3252, 0.4007)  # (topo, base) — validado na janela 1600x828

# Dois calibres validados em janelas reais do usuário, no formato
# (proporção largura/altura, topo, base). Sem calibração salva pra proporção
# atual, interpola-se linearmente entre eles (usando o mais próximo fora da
# faixa).
CALIBRACOES_VALIDADAS: list[tuple[float, float, float]] = [
    (1026 / 642, 0.388, 0.443),    # janela 1026x642
    (1600 / 828, 0.3252, 0.4007),  # janela 1600x828
]
# Diferença de proporção aceita pra considerar a calibração salva válida pra
# janela atual (redimensionar alguns px não deve anular a calibração).
TOLERANCIA_PROPORCAO = 0.05


def faixa_para_proporcao(proporcao: float) -> tuple[float, float]:
    """Devolve a faixa (topo, base) interpolada pra uma proporção de janela."""
    pontos = sorted(CALIBRACOES_VALIDADAS)
    if proporcao <= pontos[0][0]:
        return (pontos[0][1], pontos[0][2])
    if proporcao >= pontos[-1][0]:
        return (pontos[-1][1], pontos[-1][2])
    for (p0, y0a, y1a), (p1, y0b, y1b) in zip(pontos, pontos[1:]):
        if p0 <= proporcao <= p1:
            fracao = (proporcao - p0) / (p1 - p0)
            return (y0a + fracao * (y0b - y0a), y1a + fracao * (y1b - y1a))
    return (pontos[-1][1], pontos[-1][2])


def obter_faixa_nomes_y(proporcao: float | None = None) -> tuple[float, float]:
    """Lê a faixa de nomes salva pelo calibrador visual (tabela `config`).

    A calibração salva só vale pra janelas de proporção parecida (a posição
    dos nomes muda com o tamanho da janela). Sem calibração válida, devolve a
    faixa interpolada pra proporção atual (ou o padrão FAIXA_NOMES_Y, se a
    proporção não for informada). A importação do cache é feita aqui dentro
    pra evitar import circular (cache.py importa config.py).
    """
    salvo = None
    proporcao_salva = None
    try:
        from app.dados import cache

        salvo = cache.obter_config("faixa_nomes_y")
        proporcao_salva = cache.obter_config("faixa_nomes_proporcao")
    except Exception:
        pass

    if salvo:
        try:
            y0, y1 = [float(valor) for valor in salvo.split(",")]
            if 0.0 <= y0 < y1 <= 1.0:
                usar_salvo = True
                if proporcao is not None and proporcao_salva:
                    try:
                        usar_salvo = (
                            abs(float(proporcao_salva) - proporcao) <= TOLERANCIA_PROPORCAO
                        )
                    except (TypeError, ValueError):
                        usar_salvo = True
                if usar_salvo:
                    return (y0, y1)
        except (TypeError, ValueError):
            pass

    if proporcao is not None:
        return faixa_para_proporcao(proporcao)
    return FAIXA_NOMES_Y

# Nomes são agrupados dinamicamente por proximidade horizontal (em vez de
# colunas fixas), porque o número de itens na tela varia (1 a 4, conforme o
# tamanho do squad). Esse é o espaço mínimo (em pixels da imagem ORIGINAL,
# antes de qualquer upscale) entre duas palavras pra considerá-las de itens
# diferentes.
#
# Calibrado num print real da tela de recompensa (1597px de largura): o gap
# entre os NOMES de itens diferentes fica em 33..51px, e o gap entre as
# palavras DE UM MESMO nome fica em 5..6px. Com 22px a separação funciona
# até em janelas menores; menos que isso arriscaria quebrar nomes longos.
ESPACO_MINIMO_ENTRE_ITENS_PX = 22

# ---------------------------------------------------------------------------
# Motor de OCR
# ---------------------------------------------------------------------------
# Qual motor usar no reconhecimento dos nomes: "paddle" (padrão) ou
# "tesseract". Dá pra forçar via variável de ambiente MOTOR_OCR=tesseract (útil
# pra A/B entre os dois motores). O paddle não usa upscale (fator 1) — o
# tesseract continua com FATOR_UPSCALE=4 próprio.
MOTOR_OCR = os.environ.get("MOTOR_OCR", "paddle").strip().lower()
# DEBUG: quando ligado (DEBUG_OCR=1), o motor de OCR salva as imagens da faixa
# (original e pré-processada) em dados_locais/debug/ e imprime no terminal o
# texto e a confiança de cada item reconhecido. Útil pra validar o que o OCR
# "enxergou" sem abrir o jogo.
DEBUG_OCR = os.environ.get("DEBUG_OCR", "").strip().lower() in ("1", "true", "sim")

# Nome da janela do jogo, usado pra localizar e capturar só ela (não o
# monitor inteiro) — necessário porque o jogo roda em janela, não fullscreen.
NOME_JANELA_JOGO = "Warframe"

# ---------------------------------------------------------------------------
# Varredura do inventário (aba "Inventário")
# ---------------------------------------------------------------------------
# Intervalo entre passadas da varredura contínua da grade (segundos). Pode ser
# sobrescrito pela tabela `config` (chave `intervalo_varredura_inventario`).
PADRAO_INTERVALO_VARREDURA_INVENTARIO_SEG = 1.0

# Intervalo entre passadas da varredura da grade de Mods (~800ms-1s). Pode ser
# sobrescrito pela tabela `config` (chave `intervalo_varredura_mods`).
PADRAO_INTERVALO_VARREDURA_MODS_SEG = 0.8

# ---------------------------------------------------------------------------
# Fase D — gatilho automático via EE.log (Proton/Steam)
# O jogo escreve no EE.log a linha `VoidProjections: OpenVoidProjectionRewardScreenRMI`
# quando a tela de escolha de recompensa da relíquia abre. O app "segue" o log
# e dispara a captura automaticamente, sem precisar apertar o hotkey.
#
# O caminho do EE.log não é fixo: ele fica no prefix Proton (compatdata) da
# instalação do jogo, que muda de máquina pra máquina. A ordem de resolução é:
#   1. variável de ambiente WF_EE_LOG_PATH (aponta direto pro EE.log);
#   2. chave `caminho_ee_log` gravada nas Configurações;
#   3. auto-detecção nas bibliotecas Steam mais comuns do Linux;
#   4. None — o leitor avisa e espera, sem derrubar o app.
# ---------------------------------------------------------------------------
_APPID_WARFRAME_STEAM = "230410"
_SUFIXO_EE_LOG = (
    f"compatdata/{_APPID_WARFRAME_STEAM}/pfx/drive_c/"
    "users/steamuser/AppData/Local/Warframe/EE.log"
)


def _procurar_ee_log() -> Path | None:
    raizes: list[Path] = [
        Path.home() / ".steam" / "steam" / "steamapps",
        Path.home() / ".local" / "share" / "Steam" / "steamapps",
    ]
    extra = os.environ.get("STEAM_LIBRARIES", "").strip()
    raizes += [Path(p) / "steamapps" for p in extra.split(":") if p.strip()]

    for pasta in ("/media", "/mnt", "/run/media"):
        origem = Path(pasta)
        if origem.is_dir():
            raizes += list(origem.glob("*/*/SteamLibrary/steamapps"))
            raizes += list(origem.glob("*/*/Steam/steamapps"))

    vistos: set[str] = set()
    for raiz in raizes:
        try:
            real = str(raiz.resolve())
        except OSError:
            continue
        if real in vistos:
            continue
        vistos.add(real)
        candidato = raiz / _SUFIXO_EE_LOG
        if candidato.exists():
            return candidato
    return None


CAMINHO_EE_LOG = _procurar_ee_log()


def obter_caminho_ee_log() -> Path | None:
    """Caminho efetivo do EE.log (config salva na UI tem prioridade)."""
    try:
        from app.dados import cache

        salvo = cache.obter_config("caminho_ee_log")
        if salvo:
            return Path(salvo)
    except Exception:
        pass
    return CAMINHO_EE_LOG

LINHA_ABERTURA_RECOMPENSA = "OpenVoidProjectionRewardScreenRMI"
# Espera a tela terminar de renderizar antes de capturar (segundos).
PADRAO_ATRASO_CAPTURA_APOS_ABERTURA_SEG = 2.0
# Pode ser desligado pela tela de configurações (0 = só hotkey manual).
PADRAO_GATILHO_AUTOMATICO_LIGADO = True
