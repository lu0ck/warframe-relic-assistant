"""
Decide qual das 4 opções é "a melhor".

Critério: maior preço de venda em platina. Ducados ficam mostrados como
referência, mas não entram na comparação — platina é líquida e comparável
entre itens; ducados só valem alguma coisa se você realmente for gastar no
Baro Ki'Teer, então misturar as duas escalas na mesma comparação confundiria
mais do que ajudaria. Se quiser mudar esse critério depois, é só mexer aqui.
"""
from app.modelos import OpcaoRecompensa


def marcar_melhor_opcao(opcoes: list[OpcaoRecompensa]) -> list[OpcaoRecompensa]:
    candidatas = [o for o in opcoes if o.preco_plata is not None]
    if not candidatas:
        for o in opcoes:
            o.e_melhor = False
        return opcoes

    melhor = max(candidatas, key=lambda o: o.preco_plata)
    for o in opcoes:
        o.e_melhor = (o is melhor)
    return opcoes
