# Roteiro STAR — apresentação programática narrada

O gerador monta **oito cartões desenhados por código**, com texto, diagrama, gráficos e resultados reais de HTTP e PromQL. A narração é sintética, em português Brasil, pela Microsoft Maria Desktop. Os cartões identificam suas fontes; não imitam as interfaces Grafana, Airflow ou GitHub.

O [MP4](../reports/video/apresentacao_star.mp4) integra os arquivos deste repositório. Seu [manifesto](../reports/video/evidencias.json) registra a duração medida por `ffprobe`, resolução, codecs, hashes, versões, fontes e narração efetivamente renderizada. O limite é **300 segundos**; a duração não é inferida pela quantidade de palavras.

A renderização final de oito cenas foi verificada: **260,876417 segundos (4min21s)**, 1280×720, H.264/AAC e 2.849.611 bytes, com 525 palavras na narração. A [verificação completa](../reports/video/verificacao.json) aprovou **67 casos**. A [inspeção visual](../reports/video/inspecao_visual.json) registra os oito quadros extraídos do MP4, todos legíveis, e a verificação técnica do áudio. A amplitude média foi −23,9 dB e o pico −4,4 dB; não foi feita avaliação perceptiva da locução.

## Cenas e evidências

| Cena | STAR | Cartão programático | Fonte |
|---|---|---|---|
| 1 | Situação | Corpus em inglês e cinco categorias médicas | Escopo autorizado e classes do corpus |
| 2 | Tarefa | Corpus → treino → versão → API → resposta | Arquitetura implementada; AWS identificada como proposta |
| 3 | Ação | Contagens de ajuste/validação/teste e remoções | `reports/qualidade.json`, campo `auditoria_dados` |
| 4 | Ação | Exemplo público e campos das duas respostas reais | Chamadas `/ready` e `/predict` durante a captura |
| 5 | Ação | DAG real com quatro estados; CI real vinculado ao commit | `reports/docker/pos_correcao/integracao_verificada.json` e `reports/ci/34908437830/execucao.json` |
| 6 | Ação | Instrumentação → coleta → painéis, três resultados e consulta PromQL | `reports/docker/pos_correcao/smoke_stack.json` e configurações versionadas de monitoração |
| 7 | Resultado | Qualidade e gráficos p50 em processo/HTTP do host | `reports/qualidade.json`, `reports/latencia_modelo.json`, `reports/latencia_http_local.json` |
| 8 | Resultado | Aprendizados, proveniência, revisões e limites | Evidências e decisões do projeto |

## Pré-requisitos para gerar o vídeo

Use **Windows PowerShell 5.1**, iniciado por `powershell.exe`, com os assemblies **System.Drawing e System.Speech do .NET Framework**. O script rejeita PowerShell Core e plataformas diferentes do Windows. Habilite a voz **Microsoft Maria Desktop, cultura pt-BR**, e disponibilize **FFmpeg e ffprobe no PATH**. Ter somente outra voz em português não atende à seleção explícita usada pelo gerador.

Para preparar a voz, instale o recurso de fala de Português (Brasil) nas configurações de idioma do Windows e confirme que Microsoft Maria Desktop está disponível ao System.Speech. Instale uma distribuição Windows do FFmpeg que inclua os dois executáveis e adicione seu diretório `bin` ao PATH. Abra um novo Windows PowerShell após modificar o ambiente.

Este comando verifica versão do PowerShell, assemblies, voz habilitada e execução de FFmpeg/ffprobe, sem renderizar nem consultar a API:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/gerar_video.ps1 -VerificarAmbiente
```

Para pré-visualizar imagens, a voz e os executáveis de vídeo não são exigidos; Windows PowerShell e os assemblies continuam necessários.

## Preparação e verificação

1. Gere os relatórios reais de qualidade e latência. Os dois motores do benchmark HTTP precisam usar a mesma versão registrada no relatório do modelo.
2. Disponibilize essa versão no endereço passado por `-ApiUrl`. O gerador rejeita respostas de `/ready` ou `/predict` com outra versão ou motores divergentes. Uma indisponibilidade HTTP é declarada na cena; não produz resposta inventada.
3. Registre o smoke da stack em `reports/docker/pos_correcao/smoke_stack.json`. A cena de monitoração exige sucesso booleano, coleta ativa, histograma presente, fonte Grafana válida, instante e resultados numéricos finitos. Evidência ausente ou inválida interrompe a geração antes das imagens.
4. Preserve os registros reais de DAG e CI nos caminhos da tabela. A DAG só é narrada como concluída quando identifica execução, versão e quatro tarefas `success`. A versão publicada precisa coincidir com a do smoke. Sem comprovação da DAG, o cartão identifica o código estático. O CI exige execução concluída com sucesso e commit identificado, incluindo testes, build, quatro etapas e smoke.
5. Verifique os contratos, gere uma prévia e inspecione os oito PNGs. Após a revisão, renderize, confira o manifesto e escute a narração.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File reports/video/verificar_gerador.ps1 -SomenteContratos
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/gerar_video.ps1 -ApiUrl http://127.0.0.1:8004 -SomenteImagens
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/gerar_video.ps1 -ApiUrl http://127.0.0.1:8004
powershell.exe -NoProfile -ExecutionPolicy Bypass -File reports/video/verificar_gerador.ps1 -ApiUrl http://127.0.0.1:8004
```

`-SomenteContratos` não renderiza nem altera arquivos da entrega; seu resultado fica em `.local/video/verificacao-contratos.json`. `-SomenteImagens` grava imagens e manifesto próprios em `.local/video/imagens`, preservando MP4, manifesto final e intermediários de áudio/vídeo. O verificador completo confere essa preservação por hashes, obtém uma nova leitura `ffprobe`, verifica codecs, resolução, duração e correspondência com o manifesto. Também exige o hash do gerador atual, narração idêntica em cada cena, DAG real concluída e consultas/versões coincidentes com as fontes independentes. A quantidade de intermediários é calculada pelas cenas, sem depender de sete ou oito cartões. O resultado completo fica em `reports/video/verificacao.json`.

## Configuração de monitoração mostrada

O `Counter` conta requisições HTTP e o `Histogram` observa sua duração. `/metrics` expõe essas séries para o Prometheus. A [configuração de coleta](../monitoring/prometheus/prometheus.yml) usa `api:8000`, caminho `/metrics`, intervalo de **5 segundos** e job `medical-api` dentro da rede do Compose.

A [fonte Grafana](../monitoring/grafana/provisioning/datasources/prometheus.yml) tem UID `prometheus-medical` e URL `http://prometheus:9090`. O [provedor de painéis](../monitoring/grafana/provisioning/dashboards/dashboard.yml) carrega o [dashboard JSON](../monitoring/grafana/dashboards/medical-classifier.json). Esses arquivos são provisionados na inicialização dos contêineres. Os painéis apresentam volume, prontidão, coleta, taxa de chamadas, latência e erros.

A cena 6 mostra volume acumulado, p95 e proporção de erros HTTP 4xx, extraídos das consultas registradas pelo smoke. O volume acumulado pode incluir chamadas anteriores ao ensaio. Os erros 4xx incluem entradas inválidas intencionais do smoke; não medem erro de classificação médica. O p95 é uma **estimativa das faixas do histograma numa janela de 20 segundos**, expressa em segundos pela consulta e convertida para milissegundos no cartão. Não equivale ao percentil empírico do benchmark HTTP. A consulta PromQL de p95 aparece integralmente; as três expressões e seus valores integram o manifesto.

O [registro dos comandos](../reports/docker/pos_correcao/benchmark_http_execucao.json), etapa `smoke_stack_atual`, documenta o comando real, 20 requisições configuradas, caminho de saída, horários e código zero do smoke utilizado. Seu hash também integra o manifesto. A captura de 289 chamadas acumuladas corresponde à coleta de `2026-09-15T01:59:57.317Z`.

## Versões e proveniência

O exemplo HTTP e os gráficos históricos do host usam `20260914T214327-e6c68fc4`. A monitoração e a DAG Docker usam `20260914T232434-92cce529`. Tela, narração e manifesto distinguem esses experimentos. Os gráficos do host preservam seu contexto histórico; não representam o desempenho da versão Docker posterior.

O cartão de CI identifica a execução real **34908437830**, no commit **3a7ad7f052aa2ad246d399e4743f435bde8af221**. Esse resultado comprova aquele commit, sem atribuir sucesso às alterações posteriores do roteiro ou do gerador. O manifesto inclui os hashes dos relatórios e das configurações utilizados.

O comando `airflow dags test` executa a cadeia manualmente. No Airflow 2.11 também aplica `retries=1`, comportamento observado na execução remota inicial. A data lógica identifica a DAG; os horários reais dos comandos estão nas evidências de execução.

## Conteúdo STAR

**Situação:** organizar resumos públicos em inglês por condição médica com resposta rápida e operação observável. Explicar a adaptação autorizada para cinco categorias e o uso acadêmico.

**Tarefa:** entregar modelo leve, API, imagem, CI, retreino, métricas e otimização medida. O treinamento fica fora da API. A arquitetura AWS/ECS/ALB é uma proposta sem provisionamento.

**Ação:** explicar a auditoria dos dados, o TF-IDF ajustado apenas no treino, a conversão de TF-IDF e regressão logística para ONNX, o contrato da API e a identificação da versão. Demonstrar estados reais da DAG e do CI. Explicar Counter/Histogram, exposição `/metrics`, coleta a cada 5 segundos, provisionamento Grafana e resultados reais das consultas.

**Resultado:** apresentar a resposta capturada, qualidade no teste, paridade, aceleração p50 e número de medições. Separar inferência em processo, benchmark HTTP do host e estimativa do histograma Docker. Probabilidades não representam risco clínico calibrado.

**Aprendizados:** otimizar exige preservar comportamento, medir o caminho real e manter proveniência. Revisões adversariais precisam da análise dos achados. O serviço não foi validado para diagnóstico ou decisões clínicas.
