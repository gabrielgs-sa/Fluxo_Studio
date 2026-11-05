# Fluxo Studio

**Crie, organize e compartilhe fluxogramas para projetos e processos.**

O Fluxo Studio transforma etapas, decisões e conexões de um projeto em um diagrama visual editável. Cada fluxograma pode ser criado na interface gráfica ou descrito em um arquivo JSON; o mesmo arquivo pode ser reaberto para continuar a edição e exportado para PDF ou SVG.

Use o programa para planejar jornadas, documentar processos, apresentar etapas de um projeto e comunicar caminhos de decisão com clareza.

## Conteúdo

- [Recursos](#recursos)
- [Requisitos e instalação](#requisitos-e-instalação)
- [Primeiros passos](#primeiros-passos)
- [Interface gráfica](#interface-gráfica)
- [Comandos do terminal](#comandos-do-terminal)
- [Formato do fluxograma](#formato-do-fluxograma)
- [Estrutura do projeto](#estrutura-do-projeto)

## Recursos

- Criação de fluxogramas para projetos e processos, começando com um canvas vazio ou com o exemplo incluído.
- Edição visual de etapas, conexões, estilos, rótulos e legendas.
- Organização das etapas por arraste, zoom com a roda do mouse e navegação arrastando o fundo do canvas.
- Conexões com direção, pontos de origem e destino ajustáveis, rótulos e traçado contínuo ou tracejado.
- Formas de etapa retangulares, cápsulas e losangos, com estilos para etapas normais, alternativas, manuais e encerradas.
- Histórico para desfazer e refazer alterações.
- Salvamento dos projetos em JSON e exportação de diagramas em PDF ou SVG.
- Interface em tema escuro ou claro.

## Requisitos e instalação

O projeto usa Python 3.10 ou superior.

No Windows, instale as dependências conforme o modo de uso:

```powershell
# Interface gráfica
py -3 -m pip install PySide6

# Opcional: exportação para PDF
py -3 -m pip install reportlab
```

O SVG é gerado pelo próprio projeto. Para instalar as duas dependências de uma vez:

```powershell
py -3 -m pip install PySide6 reportlab
```

Execute os comandos a partir da pasta do projeto, onde estão `main.py`, `gui.py` e `fluxograma.py`.

## Primeiros passos

### Abrir a interface com o exemplo

```powershell
py -3 .\main.py gui
```

O programa abre o fluxograma de exemplo incluído em `fluxo.json`. O exemplo serve como referência e pode ser reaberto pelo botão **Abrir exemplo**.

### Criar um fluxograma do zero

Na interface, selecione **Novo**, adicione etapas, conecte-as e salve o projeto. Novos fluxos são salvos por padrão em `Documentos\Fluxo Studio`; use **Abrir** para continuar um projeto salvo.

Também é possível criar um arquivo vazio pelo terminal:

```powershell
py -3 .\main.py novo .\meu_projeto.json --titulo "Plano do projeto"
py -3 .\main.py gui .\meu_projeto.json
```

Se o arquivo indicado ainda não existir, a interface abre um fluxograma vazio. Salve-o pela própria interface para definir onde o projeto será armazenado.

### Gerar PDF e SVG

```powershell
py -3 .\main.py gerar .\fluxo.json -o .\fluxo.pdf -o .\fluxo.svg
```

Para definir o tema e o tamanho da página do PDF:

```powershell
py -3 .\main.py gerar .\fluxo.json -o .\fluxo.pdf --tema claro --pagina A4
```

Sem `-o`, o comando gera um PDF com o mesmo nome do arquivo JSON. O tema pode ser `dark`, `escuro`, `light` ou `claro`. O tamanho de página padrão é `auto`.

## Interface gráfica

| Ação | Como usar |
| --- | --- |
| Criar, abrir ou salvar | Use **Novo**, **Abrir**, **Abrir exemplo**, **Salvar** ou **Salvar como** na barra superior. |
| Mover uma etapa | Arraste a etapa para a posição desejada. |
| Navegar pelo diagrama | Arraste uma área vazia do canvas. |
| Aproximar ou afastar | Role a roda do mouse sobre a área que deseja inspecionar. Os botões `+`, `-` e **Ajustar à tela** também controlam a visualização. |
| Criar uma conexão | Ative **Conectar etapas**, selecione a etapa de origem e depois a de destino. |
| Editar uma conexão | Selecione a seta no diagrama ou na lista **Setas**. Altere o rótulo, a origem, o destino e o traçado; também é possível inverter a direção. |
| Alterar o visual | Selecione uma etapa para ajustar forma e estilo. Em **Padrões visuais**, escolha o padrão das novas etapas e setas ou aplique-o ao fluxograma inteiro. |
| Editar a legenda | Selecione um item para atualizar seu símbolo ou significado; também é possível adicionar e remover itens. |
| Desfazer ou refazer | Use os botões correspondentes ou os atalhos abaixo. |
| Exportar | Use **Exportar PDF** ou **Exportar SVG**. |

### Atalhos de teclado

| Atalho | Ação |
| --- | --- |
| `Ctrl+N` | Novo fluxograma |
| `Ctrl+O` | Abrir um fluxograma salvo |
| `Ctrl+S` | Salvar |
| `Ctrl+Shift+S` | Salvar como |
| `Ctrl+Z` | Desfazer |
| `Ctrl+Y` ou `Ctrl+Shift+Z` | Refazer |

## Comandos do terminal

Consulte a ajuda completa com:

```powershell
py -3 .\main.py --help
```

| Comando | Descrição |
| --- | --- |
| `py -3 .\main.py gui [arquivo.json]` | Abre a interface gráfica. Sem arquivo, usa `fluxo.json`. |
| `py -3 .\main.py novo arquivo.json --titulo "Título"` | Cria um JSON vazio para começar um fluxograma. |
| `py -3 .\main.py editar arquivo.json` | Abre o editor interativo no terminal. |
| `py -3 .\main.py listar arquivo.json` | Exibe as etapas, posições, conexões e legenda. |
| `py -3 .\main.py gerar arquivo.json` | Gera um PDF ao lado do arquivo JSON. |
| `py -3 .\main.py gerar arquivo.json -o saida.svg` | Gera SVG; a opção `-o` pode ser repetida para gerar vários arquivos. |

No editor do terminal, digite `ajuda` para ver os comandos disponíveis. É possível criar e editar etapas e setas, remover elementos, renomear etapas, configurar molduras e legendas, alterar os metadados, desfazer alterações, gerar arquivos, ativar a geração automática e salvar o projeto.

## Formato do fluxograma

O arquivo JSON é a fonte editável do projeto. Ele contém metadados, etapas, conexões, molduras e itens da legenda. Um exemplo mínimo:

```json
{
  "meta": {
    "title": "Plano do projeto",
    "eyebrow": "Entrega",
    "description": "Etapas principais do projeto",
    "theme": "dark"
  },
  "nodes": [
    {"id": "inicio", "title": "Início", "cx": 300, "y": 20, "shape": "stadium"},
    {"id": "planejamento", "title": "Planejamento", "below": "inicio", "gap": 50},
    {"id": "concluido", "title": "Projeto concluído", "below": "planejamento", "gap": 50, "shape": "stadium"}
  ],
  "edges": [
    {"src": "inicio", "dst": "planejamento"},
    {"src": "planejamento", "dst": "concluido", "label": "Aprovado"}
  ],
  "frames": [],
  "legend": [["normal", "Etapa do projeto"]]
}
```

Os identificadores das etapas são usados pelas conexões e pelas regras de posicionamento. As etapas podem ser posicionadas em relação a outra usando `below`, `above`, `right_of` ou `left_of`, ou por coordenadas absolutas usando `x`, `y`, `cx` e `cy`. O programa verifica referências inexistentes e posições circulares antes de salvar ou gerar o diagrama.

## Estrutura do projeto

| Arquivo | Responsabilidade |
| --- | --- |
| `main.py` | Comandos do terminal, validação do JSON, editor CLI e integração da interface. |
| `gui.py` | Interface gráfica e edição visual interativa. |
| `fluxograma.py` | Layout do diagrama e geração de PDF e SVG. |
| `fluxo.json` | Fluxograma de exemplo incluído no projeto. |
