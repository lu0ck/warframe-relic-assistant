# Assistente de Relíquias — Warframe (Linux)

Mostra, em cima da tela de recompensa da relíquia, qual item vale mais pra
vender em platina (pela API do warframe.market) e quantos ducados cada um
vale. Ativação: **automática** pelo `EE.log` do jogo ou manual pela tecla
**Home**.

Funciona via OCR da tela — o app "enxerga" os nomes dos itens, cruza com os
preços baixados da API e exibe a melhor escolha num overlay, sem injetar nada
no jogo.

## Recursos

- **Overlay automático** na tela de recompensa: melhor escolha em destaque,
  preço médio de platina e ducados de cada item (raridade da relíquia).
- **Gatilho automático** pelo `EE.log` (Proton/Steam) — captura sozinho quando
  a tela de escolha abre. Resistente a truncamento e relançamento do jogo.
- **Gatilho manual** pelo hotkey (padrão: `Home`), configurável.
- **Banco local de preços** com 584 peças Prime + mods, atualizado
  diariamente pela API v2.
- **Venda assistida**: clique no card e o app abre a página do item no
  navegador com o item/preço/quantidade já copiados pra colar — a publicação
  acontece na sua conta, pelo navegador, sem guardar nenhuma credencial.
- **Histórico** de aberturas agrupado por dia, com opção de marcar o item
  escolhido e mergir no inventário.
- **Inventário** (OCR da tela de vendas/Inventory): grade, quantidades,
  valor por conjunto e merge no inventário geral.
- **Mods** (OCR da tela de Mods): varredura da grade com deduplicação por mod,
  preço atual, resumo e merge no inventário geral.
- **Bandeja do sistema**: ícone enquanto o app está em uso, com atalhos de
  atualizar banco e configurações.

## Requisitos

- Linux com Python **3.10+** e `xdotool` (pra capturar só a janela do jogo).
- Warframe rodando via **Proton/Steam** (pro gatilho automático) e com o
  idioma em **inglês** — o OCR precisa casar com os nomes em inglês da API.
- Motor de OCR **PaddleOCR** (padrão) — o `paddlepaddle` é pesado; como
  alternativa existe o modo **Tesseract** (veja abaixo).

## Instalação

```bash
sudo apt install tesseract-ocr xdotool python3-venv
cd warframe-relic-assistant
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

A primeira carga do PaddleOCR pode demorar alguns minutos (baixa modelos).

## Como rodar

```bash
source venv/bin/activate
python -m app.main
```

O app abre a janela principal e aparece na **bandeja do sistema** enquanto
está em uso. Na primeira execução ele baixa os preços atuais (584 itens,
~5-7 min) — acompanhe na aba **Overlay**. Depois é só jogar: o overlay aparece
sozinho (ou com **Home**).

## Usando como app do sistema

O app é um programa **normal**: abre quando você quer usar e encerra quando
você fecha.

- Abra pelo **menu de aplicativos** (procure por "Assistente de Relíquias",
  com o ícone de relíquia) ou rode `./iniciar.sh`.
- Enquanto está aberto, ele aparece na **bandeja** (perto do relógio) com
  atalhos rápidos: Abrir, Atualizar banco agora, Configurações e Sair.
- **Fechar a janela encerra o app de verdade** — ele não fica rodando em
  segundo plano consumindo recursos. O ícone da bandeja some junto.
- Quer usar de novo? Abra pelo menu novamente.

Para aparecer no menu de aplicativos, instale a entrada `.desktop`:

```bash
cat > ~/.local/share/applications/assistente-reliquias.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Assistente de Relíquias
Exec=/caminho/para/o/projeto/iniciar.sh
Icon=/caminho/para/o/projeto/icones/assistente-reliquias.svg
Terminal=false
Categories=Utility;Game;
EOF
chmod +x ~/.local/share/applications/assistente-reliquias.desktop
```

(substitua `/caminho/para/o/projeto` pelo caminho real da pasta.)

## O caminho do EE.log (gatilho automático)

O `EE.log` fica dentro do prefix Proton (`compatdata/230410`) da instalação do
jogo, então o caminho varia de máquina pra máquina. O app resolve nessa ordem:

1. **Variável de ambiente `WF_EE_LOG_PATH`** apontando direto pro `EE.log`;
2. **Configurações do app** (campo "Caminho do EE.log");
3. **Auto-detecção** nas bibliotecas Steam mais comuns do Linux (inclui
   `STEAM_LIBRARIES` separada por `:` com bibliotecas extras);
4. Nada encontrado → o app avisa na bandeja e fica aguardando; configure na
   tela de Configurações ou use o hotkey manual.

## Calibrar (faça antes de confiar no reconhecimento)

A posição vertical dos nomes na tela de recompensa muda com o **tamanho da
janela do jogo**. O app já tem dois pontos validados (1026×642 e 1600×828) e
interpola entre eles automaticamente — normalmente não precisa de nada. Se o
OCR não estiver lendo os nomes na sua resolução:

1. Abra o Warframe (em inglês).
2. Jogue até a tela **"Fenda do Void/Prêmios"** de fim de missão.
3. Use a aba **"Calibração"** dentro do app (botão "Capturar janela do jogo
   agora", 3s pra posicionar, arraste a faixa em cima dos nomes e salve). A
   calibração vale na hora e é associada à proporção da janela em uso.
4. Alternativa CLI: `python -m app.captura.calibrar` — captura, salva
   `calibracao/faixa_nomes.png` e imprime o que reconheceu.

> Dica: calibre sempre com a janela do **jogo** aberta na tela de recompensa
> (não com um print do monitor inteiro) — é o que o gatilho automático captura.

## Janela principal (8 abas)

- **Overlay:** status do banco de preços e botão de atualização forçada.
- **Histórico:** sessões de abertura agrupadas por dia.
- **Itens Prime:** consulta das peças Prime com preço e ducados.
- **Mods Preços:** preços de mods no cache do warframe.market.
- **Inventário:** varredura da tela de vendas/Inventory.
- **Calibração:** ajuste visual da faixa de nomes.
- **Configurações:** hotkey, monitor do overlay, duração, nome da janela do
  jogo, gatilho automático (liga/desliga, atraso e caminho do `EE.log`),
  pasta dos prints e posição do overlay.
- **Mods:** inventário de mods (Fase Mods, abaixo).

### Fase Mods — inventário de mods

1. Com o jogo na tela de Mods, clique em **"Definir área da grade"** e arraste
   o retângulo sobre a grade inteira (a área fica salva por janela).
2. **"Iniciar varredura"** roda o OCR ~0,8s por passada: role a grade pra
   acumular os mods (mesmo mod lido duas vezes junta a quantidade).
3. Revise a tabela, veja o resumo (total + top 5 + mods sem preço) e:
   - **"Salvar"** grava o retrato na tabela de mods;
   - **"Mesclar no inventário geral"** soma os mods na aba Inventário.

Sem o jogo aberto, **"Carregar exemplo"** popula a tabela com dados falsos e o
`python -m app.captura.gerar_print_mods --reconhecer` valida o pipeline de OCR.

## Variáveis de ambiente

| Variável | Função |
|----------|--------|
| `WF_EE_LOG_PATH` | Caminho direto pro `EE.log` (ignora a auto-detecção). |
| `STEAM_LIBRARIES` | Bibliotecas Steam extras, separadas por `:`. |
| `MOTOR_OCR` | `paddle` (padrão) ou `tesseract` — útil pra comparar os motores. |
| `DEBUG_OCR` | `1` salva as imagens da faixa e imprime texto/confiança do OCR. |

## Testes

```bash
venv/bin/python -m unittest tests.test_inventario_mods -v
```

## Avisos

- Projeto **não oficial** — não tem afiliação com a Digital Extremes nem com o
  warframe.market. Use por sua conta e risco.
- Nenhuma credencial é armazenada: as vendas são feitas pelo navegador com a
  sua conta. O banco local (`dados_locais/`) guarda apenas preços e suas
  configurações.

## Licença

Licença **MIT** — você pode usar, modificar e distribuir livremente, **desde
que mantenha o aviso de copyright e a permissão** (dando os créditos ao autor).
Veja o arquivo [`LICENSE`](LICENSE).
