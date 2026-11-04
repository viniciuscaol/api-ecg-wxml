# Validação da entrega

## Versão 1.1.0 - visualização web vetorial

- **41 testes Python aprovados**, incluindo os 28 anteriores e casos de SVG nativo, todos os vértices e escalas, janela de tempo, múltiplas folhas, escape XML, anonimização e formatos inválidos. Permanece um aviso de depreciação do transporte HTTP de testes do Starlette, sem falha.
- O caminho SVG foi testado com as funções de PDF/rasterização substituídas por funções que falhariam se fossem chamadas: o SVG foi gerado com sucesso sem essas etapas.
- SVG contínuo do exame real: **52.800 vértices**, correspondentes às 4.400 amostras de cada uma das 12 derivações, sem decimação.
- SVGs de referência e contínuo rasterizados com CairoSVG para inspeção do cabeçalho, grade, caminhos e recortes.
- Teste de interface no **Chromium 153**, com upload do exame real: visualização SVG via Blob, zoom de 400% e 1600%, preservação da proporção, arraste, ajuste de largura, teclado, viewport de 390 px, exportação PDF e preflight CORS. Nenhum erro de JavaScript observado.
- `tests/browser-smoke.cjs` reproduz as verificações principais da interface com o exame sintético. Requer Node, Playwright e Chromium; não faz parte da execução padrão do pytest.
- A execução Docker continua não testada neste ambiente. A validação clínica e ensaios de carga continuam fora do escopo desta entrega.

## Verificações da versão inicial (mantidas como histórico)

- `python -m pytest -q`: **28 testes aprovados**, em aproximadamente 5 segundos. Um aviso de depreciação de transporte HTTP no TestClient/Starlette; não afetou a execução.
- Arquivo real fornecido: perfil WinCardio, 12 derivações, 4.400 amostras por canal, 600 Hz, 200 unidades/mV, 25 mm/s e 10 mm/mV.
- Todas as **52.800 amostras** lidas pelo parser foram comparadas com os inteiros extraídos separadamente do XML de origem: valores e ordem idênticos.
- Conversão do arquivo real via `POST /convert` em PDF, PNG, JPEG e ZIP: HTTP 200 nos quatro formatos.
- PDF de referência: uma página A4, com identificação, derivações, escalas e faixa DII. PNG: gerado a partir do mesmo PDF, com DPI registrado.
- PDF completo do arquivo real: quatro páginas; os intervalos dos quadros menores cobrem as 4.400 amostras por canal sem lacunas nem duplicações. A faixa longa de ritmo pode se sobrepor entre páginas, e seus intervalos são informados.
- Quatro uploads/conversões PNG concorrentes pelo TestClient: todos HTTP 200. O PDFium usa um lock por processo.
- Processo Uvicorn iniciado e cliente `examples/client.py` executado contra HTTP local real: PDF sintético gerado com sucesso.
- YAML do Compose lido e estrutura validada. **Build e execução Docker não testados**, pois o executável Docker não estava disponível.
- PDF renderizado com Poppler para inspeção visual, além da rasterização com PDFium usada na API. Cabeçalho, alinhamento, canais e rodapé verificados.

## Limites desta validação

O exemplo representa apenas **um perfil/um exame real**. Os testes sintéticos não comprovam compatibilidade com todos os aparelhos/versões nem equivalência clínica com o WinCardio. Não houve homologação clínica, ensaio de carga de longa duração, verificação da assinatura proprietária ou reconstrução de filtros do fabricante.

As imagens da referência e da API podem apresentar diferenças de posicionamento, traçado processado, fontes e grade. O renderizador usa diretamente os dados e escalas do XML, sem ajustar o sinal para imitar a imagem.

Os arquivos pessoais de origem e os resultados com identificação foram entregues separadamente do pacote de código. `examples/synthetic.wxml` não contém dados de um paciente real.
