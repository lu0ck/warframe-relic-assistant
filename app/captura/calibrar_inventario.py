"""
Recorte da grade do inventário (tela "Inventory/Sell" do jogo).

A área que mostra a grade é demarcada pelo próprio usuário arrastando um
retângulo sobre a captura (app/captura/calibrar_inventario_gui.py). A região
fica na tabela `config` como frações da janela capturada (chave
`grade_inventario` = "x0,y0,x1,y1"), junto com a proporção largura/altura da
janela em que foi demarcada — assim a calibração não vale pra uma janela de
tamanho diferente (mesmo critério da faixa de nomes).
"""
from app.config import TOLERANCIA_PROPORCAO

CHAVE_GRADE_INVENTARIO = "grade_inventario"          # "x0,y0,x1,y1" (frações 0..1)
CHAVE_GRADE_PROPORCAO = "grade_inventario_proporcao"  # proporção da janela demarcada


def obter_grade_inventario(proporcao: float | None = None) -> tuple[float, float, float, float] | None:
    """Lê a área salva pelo calibrador do inventário.

    Devolve (x0, y0, x1, y1) em frações da imagem capturada, ou None se não
    houver calibração salva (ou se ela foi feita numa janela de proporção
    diferente da informada).
    """
    from app.dados import cache

    salvo = cache.obter_config(CHAVE_GRADE_INVENTARIO)
    if not salvo:
        return None
    try:
        x0, y0, x1, y1 = [float(valor) for valor in salvo.split(",")]
    except (TypeError, ValueError):
        return None
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        return None

    if proporcao is not None:
        proporcao_salva = cache.obter_config(CHAVE_GRADE_PROPORCAO)
        if proporcao_salva:
            try:
                if abs(float(proporcao_salva) - proporcao) > TOLERANCIA_PROPORCAO:
                    return None
            except (TypeError, ValueError):
                pass
    return (x0, y0, x1, y1)


def recortar_grade_inventario(imagem):
    """Recorta a área da grade do inventário da imagem da janela.

    Devolve (recorte, area): `area` é a tupla de frações (x0, y0, x1, y1) ou
    None se não houver calibração salva pra esta proporção (recorte = None).
    """
    largura, altura = imagem.size
    area = obter_grade_inventario(largura / altura)
    if area is None:
        return None, None
    x0, y0, x1, y1 = area
    recorte = imagem.crop(
        (int(largura * x0), int(altura * y0), int(largura * x1), int(altura * y1))
    )
    return recorte, area
