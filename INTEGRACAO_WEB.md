# Integração do traçado no sistema - versão 1.1.0

## Qual formato utilizar

| Objetivo | Formato indicado | Comportamento ao ampliar |
|---|---|---|
| Visualizar o ECG dentro do sistema | **SVG** | O navegador redesenha linhas, grade e texto em vetores; sem pixelização de uma imagem bitmap de origem. |
| Exportar/imprimir | PDF | Vetorial, com escala física em milímetros. |
| Integração que só aceita imagens convencionais | PNG em 300 DPI | Aproximadamente 2480 x 3508 pixels em A4; continua tendo resolução finita. |
| Foto/imagem comprimida | JPEG | Pode introduzir artefatos; PNG ou SVG são preferíveis para linhas finas. |

A imagem de referência possui 2480 x 3508 pixels; o PNG da primeira entrega possuía 1654 x 2339, por ter sido gerado em 200 DPI. Aumentar para 300 DPI aproxima a resolução de pixels da referência, mas **SVG é o caminho recomendado para zoom dentro do sistema**.

SVG não altera o sinal adquirido: 600 Hz continuam sendo 600 Hz. O zoom não recupera informação inexistente, não homologa equivalência clínica e não replica filtros proprietários. A espessura aparente/antialiasing também depende do navegador e da tela. Este projeto não promete uma cópia pixel a pixel do traçado exportado pelo WinCardio.

## Contrato HTTP

```http
POST /convert?format=svg&layout=continuous&record=1
Content-Type: multipart/form-data; boundary=...
X-API-Key: chave-se-configurada

file: arquivo .wxml ou .xml
```

Resposta de sucesso:

```http
HTTP/1.1 200 OK
Content-Type: image/svg+xml
Content-Disposition: inline; filename="ecg.svg"
Cache-Control: no-store
X-ECG-Pages: 1
X-ECG-Layout: continuous
```

O corpo é o XML SVG UTF-8, não JSON, base64 ou PDF. **Não** chame `response.json()` para esta rota: use `response.blob()` e carregue o SVG no visualizador. O exemplo faz isso e trata erros HTTP antes de interpretar a resposta como imagem.

As rotas de PDF/PNG/JPEG/ZIP continuam iguais; selecione explicitamente `format=pdf` quando quiser exportar. O valor padrão da API continua sendo PDF para preservar integrações anteriores.

### Layouts SVG

- `layout=reference`: folha semelhante à referência, 12 quadros com o início dos canais e faixa longa de DII. Não mostra todas as amostras nos quadros menores.
- `layout=continuous`: **recomendado para examinar todos os canais**. Uma linha por derivação, com todas as amostras restantes do registro, sem dividir em folhas. É exclusivo de SVG. No exame fornecido, cada linha contém as 4.400 amostras (7,333 s).
- `layout=complete`: todas as folhas de ECG empilhadas em um único SVG. Útil para preservar o arranjo da referência e percorrer integralmente os canais. A faixa longa pode repetir intervalos entre folhas; cada janela informa seu intervalo.

`record` é a ordem de entrada no XML, a partir de 1. Em `continuous`, arquivos com vários registros exigem escolher explicitamente um registro; `/inspect` lista os registros disponíveis. Nos outros layouts, a ausência de `record` inclui todos os registros.

### Janelas de tempo

Para examinar uma janela específica:

```text
/convert?format=svg&layout=continuous&record=1&offset_seconds=2&duration_seconds=3
```

Isso começa aproximadamente no segundo 2 e inclui até 3 segundos, respeitando o final do registro. Os limites são arredondados para a amostra mais próxima. `duration_seconds` deve ser maior que zero e no máximo 60; é rejeitado fora de `continuous`. O deslocamento deve estar dentro da duração do registro. Uma janela contínua pode ter até 1500 mm de largura: para exames longos, carregue janelas consecutivas.

`dpi` não afeta SVG ou PDF. `grid=gray` ou `grid=red` controla o fundo. O ganho e a velocidade vêm do XML; não são ajustados para ocupar a tela. `anonymize=true` oculta identificação, com os limites descritos no README.

## Componente reutilizável

O arquivo **`app/ecg-viewer.js`** contém um Web Component sem React/Vue ou dependências externas. Copie-o para os assets do frontend, por exemplo `/js/ecg-viewer.js`. O mesmo componente é servido pela API em `/assets/ecg-viewer.js` e usado na tela de demonstração.

Funcionalidades:

- Botões de zoom de 100% a 1600% e ajuste à largura.
- Zoom com Ctrl + roda do mouse, mantendo o ponto próximo ao cursor.
- Arraste com o mouse; rolagem e barras nativas; em telas de toque, navegação por rolagem e botões.
- Teclas `+`, `-` e `0` quando o painel está em foco; setas/rolagem do navegador.
- Proporção preservada entre os dois eixos, calculada pelo `viewBox` do SVG.
- Liberação de URLs temporárias ao substituir/desmontar o exame e proteção contra carregamentos antigos que terminem fora de ordem.
- Shadow DOM para isolar o componente dos estilos globais da aplicação.

**100% significa ajustar o desenho à largura do painel, não 1 mm real na tela.** O zoom amplia igualmente os dois eixos e os textos. A API não certifica calibração física do monitor. Não use `object-fit: fill` ou escalas diferentes em X e Y para encaixar um ECG, pois isso distorce proporções.

### Exemplo HTML/JavaScript completo

Neste exemplo, `/api/ecg` é o proxy do backend do sistema, que encaminha a requisição à API de conversão e mantém a chave no servidor.

```html
<form id="upload-ecg">
  <label>Exame WXML <input id="arquivo" type="file" accept=".wxml,.xml" required></label>
  <button id="abrir" type="submit">Visualizar ECG</button>
</form>
<p id="mensagem" role="status"></p>
<ecg-viewer id="ecg" style="--ecg-height: 75vh"></ecg-viewer>

<script type="module">
  import '/js/ecg-viewer.js';

  const form = document.querySelector('#upload-ecg');
  const viewer = document.querySelector('#ecg');
  const message = document.querySelector('#mensagem');
  const button = document.querySelector('#abrir');

  form.addEventListener('submit', async event => {
    event.preventDefault();
    button.disabled = true;
    message.textContent = 'Carregando traçado…';
    // Retira o exame anterior para não associar seu traçado ao novo paciente.
    viewer.clear();
    try {
      const body = new FormData();
      body.append('file', document.querySelector('#arquivo').files[0]);
      // O browser define Content-Type e boundary. Não os preencha manualmente.
      const response = await fetch('/api/ecg?format=svg&layout=continuous&record=1', {
        method: 'POST', body, credentials: 'same-origin'
      });
      if (!response.ok) {
        const text = await response.text();
        let detail;
        try { detail = JSON.parse(text).detail; } catch {}
        throw new Error(typeof detail === 'string' ? detail : `Falha HTTP ${response.status}`);
      }
      await viewer.load(await response.blob());
      message.textContent = 'Traçado pronto. Use +/−, arraste ou role para navegar.';
    } catch (error) {
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

  // viewer.setZoom(4) amplia a 400%; viewer.clear() descarrega o exame.
  viewer.addEventListener('ecg-zoom', event => {
    console.debug('Zoom:', event.detail.zoom); // Não registra dados do exame.
  });
</script>
```

O componente pode ser usado dentro de React/Vue/Angular como um elemento HTML; invoque `load(blob)` pela referência ao elemento após a montagem e `clear()` ao trocar de paciente. Ele renderiza o SVG como `<img>` e não injeta o XML recebido em `innerHTML`. O `innerHTML` interno é apenas o template fixo dos controles, não o conteúdo do exame.

## Proxy de backend recomendado

Fluxo: navegador do sistema → backend autenticado do sistema → API de conversão → resposta SVG → visualizador.

O backend deve encaminhar o arquivo multipart no campo `file`, os parâmetros permitidos e `X-API-Key` quando configurada. Retorne os bytes com `Content-Type: image/svg+xml` e `Cache-Control: no-store`. Preserve o tratamento de autenticação e autorização de exames que o sistema já utiliza. A requisição pode ser feita em Python, Java/Tomcat, Node ou outra linguagem; o contrato HTTP é o mesmo.

Exemplo de chamada do lado do servidor com `httpx`:

```python
import os
import httpx

async def converter_no_backend(wxml_bytes: bytes) -> bytes:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            os.environ['ECG_CONVERTER_URL'].rstrip('/') + '/convert',
            params={'format': 'svg', 'layout': 'continuous', 'record': 1},
            files={'file': ('exam.wxml', wxml_bytes, 'application/xml')},
            headers={'X-API-Key': os.environ['ECG_API_KEY']},
        )
        response.raise_for_status()
        return response.content

# Na rota já autenticada do sistema:
# return Response(svg_bytes, media_type='image/svg+xml',
#                 headers={'Cache-Control': 'no-store'})
```

`httpx` é necessário no backend que adotar este exemplo, não no frontend. A API conversora não armazena o exame; o sistema pode persistir os bytes SVG retornados conforme seu próprio fluxo, mantendo a relação com o WXML original. Um SVG salvo pode ser exibido novamente sem reconverter o WXML.

## Integração direta e CORS

Se o frontend acessar a API em outra origem, configure explicitamente, por exemplo:

```dotenv
ECG_CORS_ORIGINS=http://localhost:5173,https://sistema.exemplo.com.br
```

Recrie o container após alterar `.env`. Essa configuração permite POST, `Content-Type` e `X-API-Key` e expõe os cabeçalhos de layout/páginas. CORS não substitui autenticação. Uma chave compartilhada entregue ao JavaScript do navegador fica acessível a quem utiliza esse navegador; por isso, o proxy do backend é a opção recomendada.

Não há CORS liberado por padrão. O componente pode ser copiado para o frontend; o arquivo de módulo da API não é um CDN com acesso irrestrito a outras origens. A política de conteúdo do sistema, quando existir, deve permitir `blob:` em `img-src` para o componente e os seus próprios assets de JavaScript/CSS. O exemplo da API já funciona na mesma origem.

## Fidelidade e tamanho da resposta

- O SVG é criado com caminhos `<path>` nativos, um vértice por amostra da janela de cada canal. Não contém PNG/JPEG embutido, `<image>`, PDF ou scripts do exame.
- A geometria de referência é compartilhada com o PDF. O contínuo usa a mesma função de coordenadas e as mesmas escalas do XML.
- Textos do paciente são escapados como XML; não são executados como HTML. Os atributos de dados dos caminhos incluem derivação, início, quantidade de amostras, taxa, sensibilidade, velocidade e ganho, para auditoria técnica.
- Aumentar o zoom não reconverte o exame nem modifica os pontos. O navegador renderiza os vetores na nova dimensão; o componente não converte o SVG em canvas/bitmap antes de exibir.
- Muitos pontos resultam em SVG maior; cada exame deve ser avaliado também no dispositivo de destino. Os limites de upload/amostras continuam válidos. Para exames longos, use janelas. A versão atual não oferece streaming, medição por cursores nem downsampling.
- Se a amplitude ultrapassar o quadro de 40 mm, o sinal é recortado e o quadro indica o excesso; não há redução automática de ganho. Isso também vale no SVG e deve ser verificado na validação com o equipamento.

Especificação de coordenadas SVG: https://www.w3.org/TR/SVG2/coords.html

## Verificação da integração

Os testes Python são executados com `python -m pytest -q`. Para reproduzir o teste opcional de interface, com Node e as dependências Python já instalados, execute na pasta do projeto:

```bash
npm install --no-save playwright
npx playwright install chromium
node tests/browser-smoke.cjs
```

O script inicia um servidor de teste em `127.0.0.1:8767`, usa o WXML sintético, testa upload, zoom, proporção, arraste, teclado, viewport pequena, PDF e CORS, e encerra o servidor ao terminar. As dependências Node são apenas para testes; a API e o componente distribuído não dependem de Node em produção. Para usar um Chromium já instalado, configure `ECG_BROWSER_EXECUTABLE` com seu caminho absoluto.
