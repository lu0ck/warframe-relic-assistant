"""Testes do inventário de Mods, do OCR da tela de Offerings e de listar_mods.

Sem pytest: roda com o unittest da stdlib. Do topo do repositório:

    venv/bin/python -m unittest tests.test_inventario_mods -v

Os testes de banco (listar_mods) usam um SQLite temporário — nunca tocam o
cache.db real do usuário.
"""
import tempfile
import time
import unittest
from types import SimpleNamespace

from app.dados import cache
from app.dados.inventario_mods import (
    LinhaMod,
    calcular_resumo_mods,
    chave_de_dedup_mod,
    resumo_por_mod,
    top_mods,
)
from app.dados.mods_syndicate import MODS_DE_SYNDICATE, MODS_SINDICATO_POR_NOME
from app.captura.mods_ocr import (
    _limpar_texto_celula,
    _matchar,
    _sindicate_dominante,
)
from app.modelos import ItemCache


def _pool_arbiters() -> list[ItemCache]:
    return [
        ItemCache(nome=nome, preco_plata=10.0, ducados=None, slug="x")
        for nome in MODS_DE_SYNDICATE["Arbiters of Hexis"]
    ]


class TestResumoMods(unittest.TestCase):
    def test_total_e_sem_preco(self):
        linhas = [
            LinhaMod("Vitality", 10, None),
            LinhaMod("Flow", 3, 20.0),
            LinhaMod("Serration", 2, 5.0),
        ]
        resumo = calcular_resumo_mods(linhas)
        self.assertEqual(resumo.total_com_preco, 70.0)
        self.assertEqual(resumo.quantidade_sem_preco, 1)

    def test_total_vazio(self):
        resumo = calcular_resumo_mods([])
        self.assertEqual(resumo.total_com_preco, 0.0)
        self.assertEqual(resumo.quantidade_sem_preco, 0)


class TestResumoPorMod(unittest.TestCase):
    def test_agrupa_pelo_mesmo_slug(self):
        linhas = [
            LinhaMod("Split Chamber", 3, 150.0, "split_chamber"),
            LinhaMod("Split Chamber", 2, 150.0, "split_chamber"),
        ]
        detalhe = resumo_por_mod(linhas)
        self.assertEqual(len(detalhe), 1)
        self.assertEqual(detalhe[0].quantidade, 5)
        self.assertEqual(detalhe[0].subtotal, 750.0)

    def test_agrupa_sem_slug_pelo_nome(self):
        linhas = [
            LinhaMod("Vitality", 4, None),
            LinhaMod("Vitality", 6, None),
        ]
        detalhe = resumo_por_mod(linhas)
        self.assertEqual(len(detalhe), 1)
        self.assertEqual(detalhe[0].quantidade, 10)
        self.assertIsNone(detalhe[0].subtotal)

    def test_ordena_do_mais_valioso_e_sem_preco_no_fim(self):
        linhas = [
            LinhaMod("B", 1, 5.0, "b"),
            LinhaMod("A", 1, 100.0, "a"),
            LinhaMod("C", 1, None, None),
        ]
        detalhe = resumo_por_mod(linhas)
        self.assertEqual([r.nome for r in detalhe], ["A", "B", "C"])
        self.assertEqual(detalhe[-1].subtotal, None)


class TestTopMods(unittest.TestCase):
    def test_ignora_sem_preco_e_respeita_limite(self):
        linhas = [
            LinhaMod("A", 1, 100.0, "a"),
            LinhaMod("B", 1, 50.0, "b"),
            LinhaMod("C", 1, None, None),
        ]
        top = top_mods(linhas, limite=1)
        self.assertEqual([r.nome for r in top], ["A"])


class TestDedup(unittest.TestCase):
    def test_slug_e_nome_nao_colidem(self):
        self.assertEqual(chave_de_dedup_mod("Flow", "flow"), "slug:flow")
        self.assertEqual(chave_de_dedup_mod("Flow"), "nome:flow")
        self.assertNotEqual(chave_de_dedup_mod("Flow"), chave_de_dedup_mod("Flow", "flow"))

    def test_normaliza_nome(self):
        self.assertEqual(chave_de_dedup_mod("  Split   Chamber "), "nome:splitchamber")


class TestLimparTextoDaBanda(unittest.TestCase):
    def test_remove_numeros_do_nome(self):
        self.assertEqual(_limpar_texto_celula("Split Chamber 5"), "Split Chamber")
        self.assertEqual(_limpar_texto_celula("Chaos 9"), "Chaos")

    def test_remove_simbolos_soltos(self):
        # '&' é lido como token de símbolo e vai fora; o nome real é
        # "Calm & Frenzy", que o fuzzy casa normalmente.
        self.assertEqual(_limpar_texto_celula("% Calm & Frenzy"), "Calm Frenzy")
        self.assertEqual(_limpar_texto_celula("% Chaos"), "Chaos")


class TestMatcharComGuardas(unittest.TestCase):
    """Guardas calibradas no print exemplomods.png (syndicate dominante:
    Arbiters of Hexis)."""

    def setUp(self):
        self.pool = _pool_arbiters()

    def test_fragmento_curto_nao_mata_candidato_composto(self):
        # 'Wear'/'kin'/'arge'/'itn' são lixo curto de 1 palavra — o fuzzy
        # casaria com mods compostos (Warding Thurible, Seeking Shuriken...) a
        # confiança alta; a guarda de concatenação curta precisa barrar.
        for lixo in ("Wear", "kin", "arge", "itn", "sas", "Sis"):
            self.assertIsNone(_matchar(lixo, self.pool), f"{lixo!r} não devia casar")

    def test_concatenacao_longa_de_nome_composto(self):
        # 'AvengingeTruth' e 'GildedTrath' são nomes compostos lidos SEM espaço
        # (concatenação longa) — devem casar com o nome de 2 palavras.
        resultado = _matchar("AvengingeTruth", self.pool)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.nome_encontrado, "Avenging Truth")
        resultado = _matchar("GildedTrath", self.pool)
        self.assertEqual(resultado.nome_encontrado, "Gilded Truth")

    def test_ocr_ruim_porem_reconhecivel(self):
        self.assertEqual(_matchar("Calin Frenzy", self.pool).nome_encontrado, "Calm & Frenzy")
        self.assertEqual(_matchar("Firious Javelin", self.pool).nome_encontrado, "Furious Javelin")
        self.assertEqual(_matchar("Chaos Sphere", self.pool).nome_encontrado, "Chaos Sphere")

    def test_palavra_unica_curta_exige_confianca(self):
        self.assertEqual(_matchar("Capacitance", self.pool).nome_encontrado, "Capacitance")

    def test_vazio_ou_curto_demais(self):
        self.assertIsNone(_matchar("", self.pool))
        self.assertIsNone(_matchar("a", self.pool))
        self.assertIsNone(_matchar("ae", self.pool))


class TestSindicateDominante(unittest.TestCase):
    def test_maioria_decide(self):
        celulas = [
            {"resultado": SimpleNamespace(nome_encontrado="Blade of Truth")},
            {"resultado": SimpleNamespace(nome_encontrado="Gilded Truth")},
            {"resultado": SimpleNamespace(nome_encontrado="Entropy Spike")},
            {"resultado": SimpleNamespace(nome_encontrado="Avenging Truth")},
            {"resultado": SimpleNamespace(nome_encontrado="Blade of Truth")},
            {"resultado": None},
        ]
        self.assertEqual(_sindicate_dominante(celulas), "Arbiters of Hexis")

    def test_sem_matches_devolve_none(self):
        self.assertIsNone(_sindicate_dominante([{"resultado": None}]))

    def test_mod_compartilhado_vota_em_ambas(self):
        # Seeking Shuriken é vendido por Arbiters E Red Veil — vota nas duas.
        self.assertEqual(
            MODS_SINDICATO_POR_NOME.get("seekingshuriken"),
            ("Arbiters of Hexis", "Red Veil"),
        )


class TestListarMods(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db")
        self.banco_original = cache.CAMINHO_BANCO
        cache.CAMINHO_BANCO = self.temp_db.name
        cache.criar_tabelas()
        cache.salvar_mods([
            SimpleNamespace(slug="vitality", nome="Vitality", preco_plata=5.0),
            SimpleNamespace(slug="continuity", nome="Continuity", preco_plata=20.0),
            SimpleNamespace(slug="sem_preco", nome="SemPreco", preco_plata=None),
        ])

    def tearDown(self):
        cache.CAMINHO_BANCO = self.banco_original
        self.temp_db.close()

    def test_ordena_por_preco_decrescente_null_no_fim(self):
        mods, total = cache.listar_mods()
        self.assertEqual(total, 3)
        self.assertEqual([m.nome for m in mods], ["Continuity", "Vitality", "SemPreco"])
        self.assertIsNone(mods[-1].preco_plata)

    def test_filtro_por_nome_e_paginacao(self):
        mods, total = cache.listar_mods(filtro_nome="ity")
        self.assertEqual(total, 2)
        self.assertEqual({m.nome for m in mods}, {"Vitality", "Continuity"})

        mods, total = cache.listar_mods(limite=1, offset=0)
        self.assertEqual(total, 3)
        self.assertEqual(len(mods), 1)

    def test_somente_com_preco(self):
        mods, total = cache.listar_mods(somente_com_preco=True)
        self.assertEqual(total, 2)
        self.assertTrue(all(m.preco_plata is not None for m in mods))


class TestUIModsImportaLimpo(unittest.TestCase):
    """Regressão: aba_mods usava resumo_por_mod sem importar (NameError a
    cada passada da varredura)."""

    def test_resumo_por_mod_disponivel_no_modulo_da_aba(self):
        from app.ui import aba_mods

        self.assertTrue(callable(aba_mods.resumo_por_mod))


class TestPararNaoBloqueante(unittest.TestCase):
    """Regressão: parar() esperava até 5s a passada de OCR na thread da UI
    (congelava o 'Finalizar varredura'). Agora retorna na hora."""

    def setUp(self):
        import app.automacao.varredura_mods as vm

        self.modulo = vm
        self._orig = (
            vm.capturar_janela_do_jogo,
            vm.recortar_grade_mods,
            vm.reconhecer_itens_mods,
        )
        vm.capturar_janela_do_jogo = lambda **kw: (None, False)
        vm.recortar_grade_mods = lambda imagem: (None, None)
        vm.reconhecer_itens_mods = lambda recorte: []

    def tearDown(self):
        m = self.modulo
        m.capturar_janela_do_jogo, m.recortar_grade_mods, m.reconhecer_itens_mods = self._orig

    def test_parar_retorna_sem_esperar_o_ocr(self):
        varredura = self.modulo.VarreduraMods(intervalo=0.3)
        varredura.start()
        time.sleep(0.05)
        inicio = time.monotonic()
        varredura.parar()
        decorrido = time.monotonic() - inicio
        varredura.wait(5000)
        self.assertLess(decorrido, 0.5)


class TestAvisoSemPrecos(unittest.TestCase):
    """Regressão: quando a tela/área não tem preços em standing (ou nada casa),
    reconhecer_itens_mods deve EXPLICAR o porquê em `avisos`, não só devolver
    uma lista vazia silenciosa."""

    def setUp(self):
        from app.captura import mods_ocr as mocr
        import PIL.Image as PILImage

        self.mocr = mocr
        self.PILImage = PILImage
        self._orig = (mocr._resultado_bruto, mocr._candidatos_mods_por_nome,
                      mocr._reconhecer_banda)

    def tearDown(self):
        (self.mocr._resultado_bruto, self.mocr._candidatos_mods_por_nome,
         self.mocr._reconhecer_banda) = self._orig

    def test_sem_precos_avisa_e_retorna_vazio(self):
        self.mocr._resultado_bruto = lambda imagem, salvar_debug=False: {
            "text_word": [],
            "rec_scores": [],
            "text_word_boxes": [],
        }
        avisos = []
        itens = self.mocr.reconhecer_itens_mods(
            self.PILImage.new("RGB", (600, 400)), avisos=avisos
        )
        self.assertEqual(itens, [])
        self.assertTrue(avisos)
        self.assertIn("standing", avisos[0])
        self.assertIn("Offerings", avisos[0])

    def test_precos_mas_nenhum_nome_casa_avisa(self):
        self.mocr._resultado_bruto = lambda imagem, salvar_debug=False: {
            "text_word": [["25.000"]],
            "rec_scores": [1.0],
            "text_word_boxes": [[(100, 100, 180, 120)]],
        }
        self.mocr._candidatos_mods_por_nome = lambda: {
            "vitality": SimpleNamespace(
                nome="Vitality", slug="vitality", preco_plata=5.0, ducados=None
            )
        }
        self.mocr._reconhecer_banda = lambda faixa: "xyz"
        avisos = []
        itens = self.mocr.reconhecer_itens_mods(
            self.PILImage.new("RGB", (600, 400)), avisos=avisos
        )
        self.assertEqual(itens, [])
        self.assertTrue(avisos)
        self.assertIn("nenhum nome casou", avisos[0])


class TestLeituraDiretaDeNomes(unittest.TestCase):
    """Fallback da tela de Mods (grade SEM preço em standing): os nomes são
    lidos direto do recorte e cada um vira preço no cache — em vez de a
    leitura voltar vazia por não haver âncora de preço."""

    def setUp(self):
        from app.captura import mods_ocr as mocr
        import PIL.Image as PILImage

        self.mocr = mocr
        self.PILImage = PILImage
        self._orig = (mocr._resultado_bruto, mocr._candidatos_mods_por_nome,
                      mocr._reconhecer_banda)

    def tearDown(self):
        (self.mocr._resultado_bruto, self.mocr._candidatos_mods_por_nome,
         self.mocr._reconhecer_banda) = self._orig

    @staticmethod
    def _cache_4_mods():
        return {
            "acid shells": SimpleNamespace(
                nome="Acid Shells", slug="acid_shells", preco_plata=10.0,
                ducados=None),
            "electromagnetic shielding": SimpleNamespace(
                nome="Electromagnetic Shielding",
                slug="electromagnetic_shielding", preco_plata=5.0,
                ducados=None),
            "vulcan blitz": SimpleNamespace(
                nome="Vulcan Blitz", slug="vulcan_blitz", preco_plata=5.0,
                ducados=None),
            "medi-ray": SimpleNamespace(
                nome="Medi-Ray", slug="medi_ray", preco_plata=8.0,
                ducados=None),
        }

    def test_sem_preco_le_nomes_direto_e_busca_no_cache(self):
        # Grade 690x477 simulando a tela de Mods: 2 fileiras de nomes, selos
        # de rank numéricos e a barra de busca no topo.
        linhas = [
            (["NAME", "SEARCH"], 0.99,
             [(350, 2, 405, 18), (550, 2, 615, 18)]),      # barra de busca
            (["9"], 0.99, [(240, 96, 260, 110)]),           # selo de rank
            (["Acid", "Shells"], 0.99,
             [(60, 108, 80, 134), (105, 108, 135, 134)]),
            (["Electromagnetic", "Shielding"], 0.99,
             [(235, 108, 260, 134), (295, 108, 315, 134)]),
            (["Vulcan", "Blitz"], 0.99,
             [(60, 278, 110, 304), (115, 278, 145, 304)]),
            (["Medi-Ray"], 0.99, [(250, 278, 315, 304)]),
        ]
        self.mocr._resultado_bruto = lambda imagem, salvar_debug=False: {
            "text_word": [l[0] for l in linhas],
            "rec_scores": [l[1] for l in linhas],
            "text_word_boxes": [l[2] for l in linhas],
        }
        self.mocr._candidatos_mods_por_nome = self._cache_4_mods
        avisos = []
        itens = self.mocr.reconhecer_itens_mods(
            self.PILImage.new("RGB", (690, 477)), avisos=avisos
        )
        self.assertEqual(
            {i.nome: i.preco_plata for i in itens},
            {
                "Acid Shells": 10.0,
                "Electromagnetic Shielding": 5.0,
                "Vulcan Blitz": 5.0,
                "Medi-Ray": 8.0,
            },
        )
        self.assertEqual(avisos, [])

    def test_lixo_de_ui_e_rank_nao_vira_item(self):
        # Só barra de busca, selos de rank e ruído: nada deve virar item.
        linhas = [
            (["NAME", "SEARCH"], 0.99,
             [(350, 2, 405, 18), (550, 2, 615, 18)]),
            (["9", "51"], 0.99,
             [(240, 96, 260, 110), (400, 96, 425, 110)]),
            (["Y"], 0.99, [(300, 278, 315, 304)]),
        ]
        self.mocr._resultado_bruto = lambda imagem, salvar_debug=False: {
            "text_word": [l[0] for l in linhas],
            "rec_scores": [l[1] for l in linhas],
            "text_word_boxes": [l[2] for l in linhas],
        }
        self.mocr._candidatos_mods_por_nome = self._cache_4_mods
        itens = self.mocr.reconhecer_itens_mods(
            self.PILImage.new("RGB", (690, 477))
        )
        self.assertEqual(itens, [])


if __name__ == "__main__":
    unittest.main()
