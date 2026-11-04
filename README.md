# ECG WXML API

API em Python/FastAPI que converte ECGs WinCardio em **SVG vetorial, PDF vetorial, PNG, JPEG ou ZIP**. A versão **1.1.0** inclui visualizador web reutilizável com zoom de 100% a 1600%, arraste e rolagem, além de Docker Compose, tela de upload em português, Swagger, conversor de linha de comando e testes.

**Para visualizar o traçado dentro de outro sistema, use SVG.** O traçado é produzido diretamente em vetores, sem gerar PDF nem imagem de pixels no caminho. O navegador redesenha as linhas ao ampliar; todos os pontos da janela são preservados. O PDF continua disponível para exportação. A API preserva `format=pdf` como padrão por compatibilidade, enquanto a tela de demonstração começa em SVG contínuo.

Veja **[INTEGRACAO_WEB.md](INTEGRACAO_WEB.md)** para o contrato HTTP, componente de visualização, exemplo HTML/JavaScript completo, proxy de backend, CORS, qualidade e escalas.

O layout foi construído a partir da imagem e do WXML fornecidos: quatro linhas de três derivações (DI/DII/DIII, aVR/aVL/aVF, V1/V2/V3, V4/V5/V6), faixa de ritmo DII e cabeçalho do exame. A página é A4 vertical. É uma reprodução do arranjo, **não uma cópia idêntica pixel a pixel da exportação proprietária**.

## Rodar com Docker

Requisitos: Docker Engine e Docker Compose v2.

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Abra **http://localhost:8000** para enviar o exame. Swagger: **http://localhost:8000/docs**. Saúde: **http://localhost:8000/health**.

```bash
docker compose logs -f ecg-api
docker compose down
```

O Compose publica em `127.0.0.1` por padrão. Para acesso pela rede local, configure `ECG_BIND_IP=0.0.0.0`, preencha `ECG_API_KEY` e recrie o serviço com `docker compose up -d`. Abra pelo IP do servidor, por exemplo `http://IP_DO_SERVIDOR:8000`. A chave é enviada pelo campo da tela ou pelo cabeçalho `X-API-Key`; não fica gravada no navegador.

Para conectar outro container à API, use o nome `ecg-api` como hostname quando ambos estiverem na mesma rede Docker. O container executa sem root, com sistema de arquivos somente leitura e `/tmp` limitado para o upload multipart.

## Rodar sem Docker

Python 3.12:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

No Windows, a ativação PowerShell é `.venv\Scripts\Activate.ps1`. PDFium é fornecido pelo pacote `pypdfium2`; não é necessário instalar Poppler, Ghostscript ou o WinCardio para executar a API.

## Exemplos da API

O corpo é `multipart/form-data`, com o campo **file**. As opções são parâmetros da URL. Use `curl.exe` no PowerShell se `curl` for um alias.

```bash
# PDF com o arranjo da referência
curl --fail-with-body -X POST \
  'http://localhost:8000/convert?format=pdf' \
  -F 'file=@exame.wxml' -o ecg.pdf

# PNG em 200 DPI
curl --fail-with-body -X POST \
  'http://localhost:8000/convert?format=png&dpi=200' \
  -F 'file=@exame.wxml' -o ecg.png

# PDF de todas as amostras de todas as derivações
curl --fail-with-body -X POST \
  'http://localhost:8000/convert?format=pdf&layout=complete' \
  -F 'file=@exame.wxml' -o ecg-completo.pdf

# PDF + uma imagem PNG por página + metadata.json
curl --fail-with-body -X POST \
  'http://localhost:8000/convert?format=zip&layout=complete&dpi=150' \
  -F 'file=@exame.wxml' -o ecg.zip

# Inspecionar metadados sem gerar o traçado
curl --fail-with-body -X POST \
  'http://localhost:8000/inspect' -F 'file=@exame.wxml'

# Quando ECG_API_KEY estiver configurada
curl --fail-with-body -X POST \
  'http://localhost:8000/convert?format=pdf' \
  -H 'X-API-Key: SUA_CHAVE' -F 'file=@exame.wxml' -o ecg.pdf
```

### Opções de `/convert`

| Parâmetro | Padrão | Comportamento |
|---|---|---|
| `format` | `pdf` | `svg`, `pdf`, `png`, `jpeg`, `zip` |
| `layout` | `reference` | Início dos 12 canais e ritmo longo. `complete` percorre os canais em páginas sucessivas. |
| `record` | todos | Índice de ordem do registro no XML, começando em 1; não é o atributo `Numero`. |
| `offset_seconds` | `0` | Início da janela dentro do registro. Em `complete`, percorre deste ponto até o final. |
| `dpi` | `200` | 72 a 300 para imagens; não muda a geometria do PDF. |
| `grid` | `gray` | Cinza pontilhado ou `red` contínuo. |
| `rhythm` | `DII` | Derivação usada na faixa longa. |
| `anonymize` | `false` | Oculta identificação do paciente, número do exame e série. Mantém data/hora e dados do sinal; não é desidentificação completa. |

Novidades da versão 1.1: `format=svg`; `layout=continuous` para SVG; e `duration_seconds` (opcional, maior que zero e até 60), usado apenas na janela contínua. `reference` e `complete` também funcionam em SVG. No modo `complete`, um único SVG contém as folhas empilhadas, sem descartar páginas. `continuous` mostra os 12 canais inteiros, uma linha por derivação; exige selecionar `record` se o XML possuir vários registros. A janela contínua tem largura máxima de 1500 mm; use `duration_seconds` e `offset_seconds` para registros mais longos.

```bash
# Visualização vetorial no sistema, sem passar por PDF
curl --fail-with-body -X POST \
  'http://localhost:8000/convert?format=svg&layout=continuous' \
  -F 'file=@exame.wxml' -o ecg.svg

# Arranjo da referência, também vetorial
curl --fail-with-body -X POST \
  'http://localhost:8000/convert?format=svg&layout=reference' \
  -F 'file=@exame.wxml' -o folha.svg

python cli.py exame.wxml ecg.svg --layout continuous
python cli.py exame.wxml janela.svg --layout continuous --offset-seconds 2 --duration-seconds 3
```

PNG/JPEG aceita somente resultado de **uma página**. Para vários registros, selecione `record=1&layout=reference` ou use PDF/ZIP. A API rejeita a combinação de imagem única e várias páginas, em vez de descartar páginas. O ZIP inclui `ecg.pdf`, `ecg-001.png`, etc. e `metadata.json` com os intervalos de amostras renderizados.

`/inspect` também aceita `anonymize=true`. Os metadados incluem a frequência cardíaca que já estava no XML; não há cálculo automático de FC.

### Respostas e erros

- `200`: binário do arquivo, `Content-Disposition: attachment`, `Cache-Control: no-store`; `/inspect` retorna JSON.
- `401`: chave inválida quando a autenticação está habilitada.
- `413`: arquivo maior que 10 MiB ou corpo multipart maior que 10 MiB + 64 KiB.
- `415`: extensão diferente de `.xml`/`.wxml` (comparação sem diferenciar maiúsculas).
- `422`: XML inválido, perfil incompatível, DTD/entidades, escala ausente, amostras inconsistentes ou parâmetros incompatíveis.

O limite do corpo é conferido também em transferências sem Content-Length. Há limite de 1.000.000 de amostras totais, 30 registros e 50 páginas por conversão. O ZIP possui orçamento de 60 megapixels; reduza DPI ou use PDF se exceder. Duas renderizações são permitidas simultaneamente por processo, e o acesso ao PDFium é protegido por lock. Mais workers Uvicorn criam processos independentes; ajuste o limite de memória proporcionalmente.

## Conversor local e cliente Python

```bash
python cli.py exame.wxml ecg.pdf
python cli.py exame.wxml ecg.png --dpi 200
python cli.py exame.wxml completo.pdf --layout complete
python cli.py exame.wxml conjunto.zip --layout complete --dpi 150
python cli.py exame.wxml ecg.png --record 1 --offset-seconds 2 --rhythm DII

# Arquivo sintético incluído para testar sem dados reais
python cli.py examples/synthetic.wxml teste.pdf

# Cliente que usa apenas a biblioteca padrão do Python
python examples/client.py exame.wxml ecg.pdf
```

## Geometria e integridade do sinal

O perfil observado declara `TaxaAmostragem="600 amostras por segundo"`, `Sensibilidade="200/1mV"`, `Velocidade=25` e `Ganho=10` por canal. Cada canal contém 4.400 inteiros, ou **7,333 segundos** neste exame.

A conversão usa diretamente as unidades declaradas, também no SVG:

```text
t_segundos = índice_amostra / taxa_amostragem
amplitude_mV = valor_amostra / unidades_por_mV
x_mm = t_segundos * velocidade_mm_por_segundo
y_mm = amplitude_mV * ganho_mm_por_mV
```

Portanto 600 intervalos de amostra ocupam 25 mm e 200 unidades correspondem a 10 mm para as escalas deste arquivo. A grade tem passos de 1 mm e destaques a cada 5 mm. Não se suaviza, reamostra, centraliza, normaliza ou aplica filtros ao sinal. Todas as amostras da janela entram no caminho vetorial. O fundo e o traçado são compartilhados entre as saídas: as imagens são rasterizadas do PDF.

Os quadros menores têm aproximadamente 60,667 mm de largura e 40 mm de altura; a faixa longa tem 184 mm. Com 25 mm/s e 600 Hz, o layout `reference` apresenta as primeiras 1.456 amostras de cada canal (2,427 s) e até 4.416 amostras na faixa longa (7,36 s). Para o arquivo recebido, a faixa DII mostra as 4.400 amostras, e os demais canais mostram apenas a primeira janela. **Use `complete` para visualizar integralmente todas as derivações.** Neste exame, são quatro páginas; a última cobre as 32 amostras finais nos quadros menores. Espaço vazio em janelas parciais é intencional.

O rodapé informa os intervalos usados; os tempos de fim indicam o limite exclusivo da janela, isto é, `quantidade/taxa`. Se o sinal ultrapassar os 20 mm acima/abaixo da linha central, ele será recortado na borda e o PDF exibirá um aviso. A API não reduz o ganho automaticamente para esconder esse caso.

Imprima o PDF em **100% / tamanho real**, sem ajustar à página. A escala física na tela depende do zoom e da calibração do monitor. O PNG carrega metadados de DPI, mas programas de imagem podem ignorá-los.

## Perfil suportado e limites de equivalência

- Raiz `WinCardio Tipo="exame"`, `Paciente`, `Exame/Registros/Registro/Canais/Canal` e amostras inteiras separadas por `;`, inclusive dentro de CDATA.
- Metadados de amostragem e sensibilidade nos atributos de `Registros`; velocidade e ganho explícitos. Não há valores clínicos de escala assumidos quando o XML omite esses campos.
- Exatamente 12 derivações. `I`, `II` e `III` são aliases de `DI`, `DII` e `DIII`; comparação de nomes não diferencia maiúsculas. Canais extras/desconhecidos, duplicados e faltantes são rejeitados.
- Aceita ponto ou vírgula decimal em parâmetros numéricos. Os canais devem ter o mesmo comprimento, compatível com `AmostrasPorBloco` quando declarado. Perfis comprimidos, cifrados, binários, com namespaces ou outras estruturas não são implementados.
- `Filtro60Hz` e `FiltroMuscular` aparecem como elementos vazios no arquivo recebido e seus nomes aparecem na imagem original. A presença desses elementos é exibida como declaração do XML; a API não recria algoritmos de filtro proprietários nem comprova qual processamento foi feito na aquisição.
- `CanalRitmo=1` consta no arquivo, enquanto a imagem usa DII. Como a indexação desse campo não foi confirmada por uma especificação pública, ele é preservado nos metadados e **não determina o canal automaticamente**. O padrão explícito é `rhythm=DII`.
- O atributo proprietário `Security` não é validado; a conversão não atesta autenticidade ou assinatura do exame.
- Fontes do PDF suportam acentos portugueses via WinAnsi. Caracteres fora dessa codificação são substituídos por `?`, com aviso na página quando aplicável. Campos muito extensos são reduzidos/abreviados no cabeçalho; `/inspect` conserva até 240 caracteres por campo.
- O código não produz diagnóstico, medidas de PR/QRS/QT, interpretação ou laudo automático. O nome/arranjo e dados são extraídos do exame; não se usa a imagem de referência para inventar sinal.

Antes de incorporar a conversão ao fluxo de laudos, compare diferentes exames reais com a exportação original, verificando tempo, amplitude, derivações, polaridade e comportamento dos filtros. Este projeto foi validado tecnicamente com **um WXML real** e casos sintéticos; não é software clinicamente homologado. A identidade visual, posições e traçado exportado pelo programa original podem diferir.

## Dados e integração

Não há banco de dados, armazenamento permanente nem chamada a serviço externo. Uploads podem passar pelo temporário multipart e são fechados após a leitura; os resultados são gerados em memória e retornados ao cliente. O container limita `/tmp` e desabilita logs de acesso do Uvicorn. Ao publicar uma rota externa, configure TLS, autenticação e limites também no proxy. A autenticação por chave é opcional apenas para o uso local; é responsabilidade da implantação habilitá-la para o acesso de terceiros. Swagger e `/health` permanecem públicos. Para acesso direto do frontend em outra origem, configure `ECG_CORS_ORIGINS` com origens explícitas separadas por vírgulas. Prefira um proxy autenticado no backend da aplicação, mantendo a chave compartilhada fora do JavaScript entregue ao navegador.

Você pode chamar `/convert` a partir de FastAPI, Java/Tomcat, jobs ou outro backend; não precisa executar o WinCardio. Para persistir o PDF no sistema de laudos, grave o binário recebido no armazenamento já utilizado pela aplicação e relacione-o ao exame original. O nome de download é genérico (`ecg.pdf`), sem dados do paciente.

## Testes

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Os testes verificam calibração, perfil inválido, DTD/entidades, incoerência de amostras, cobertura integral entre páginas, autenticação, limites de upload, PDF A4, PNG/JPEG e seus DPI, ZIP, anonimização parcial, recorte de amplitudes e renderização paralela protegida. O arquivo de exemplo é **sintético**; os anexos pessoais não fazem parte do código distribuído.

Veja `VALIDACAO.md` para os resultados desta entrega. O Dockerfile/Compose é fornecido, mas não foi executado no ambiente de desenvolvimento desta entrega porque não havia Docker disponível.

## Referências de implementação

- FastAPI, upload de arquivos: https://fastapi.tiangolo.com/tutorial/request-files/
- ReportLab, coordenadas do canvas: https://docs.reportlab.com/reportlab/userguide/ch2_graphics/
- pypdfium2, rasterização e restrição de threads do PDFium: https://pypdfium2.readthedocs.io/en/stable/python_api.html
- Manual do WinCardio: https://micromed.ind.br/micromedstore/Manual-Wincardio-USB.pdf

Essas referências orientam as bibliotecas/uso do equipamento; o parser WXML foi implementado a partir do arquivo recebido, sem um XSD/especificação pública do formato.
