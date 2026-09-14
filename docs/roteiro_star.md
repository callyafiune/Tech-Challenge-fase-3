# Roteiro STAR — apresentação programática narrada

O vídeo usa **sete cartões desenhados por código**, com texto, diagrama, gráficos e recortes de JSON reais. A narração é sintética, em português Brasil, pela Microsoft Maria Desktop. Não há captura da área de trabalho nem simulação visual das interfaces Grafana, Airflow ou GitHub.

O [MP4 local](../reports/video/apresentacao_star.mp4) e o [manifesto de evidências](../reports/video/evidencias.json) são produzidos por [scripts/gerar_video.ps1](../scripts/gerar_video.ps1). A duração vem do arquivo renderizado e é validada por `ffprobe`, com limite de **300 segundos**. Os tempos de cada cena são registrados no manifesto; não se presume uma duração a partir do texto. O MP4 integra os arquivos deste repositório.

A renderização final foi verificada: **219,626395 segundos (3min40s)**, resolução 1280×720, vídeo H.264 e áudio AAC, com 2.409.644 bytes. Os sete cartões foram inspecionados visualmente. A narração contém 451 palavras. O manifesto confirma API/relatórios da versão `20260914T214327-e6c68fc4`, stack verificada e as quatro tarefas reais do Airflow concluídas.

## Cenas e evidências

| Cena | STAR | Cartão programático | Fonte |
|---|---|---|---|
| 1 | Situação | Título, corpus em inglês e cinco categorias | Escopo autorizado e classes do corpus |
| 2 | Tarefa | Diagrama corpus → treino → versão → API → resposta | Arquitetura implementada; AWS identificada como proposta |
| 3 | Ação | Contagens de ajuste/validação/teste e remoções | `reports/qualidade.json`, campo `auditoria_dados` |
| 4 | Ação | Exemplo público e campos selecionados das duas respostas reais | Chamadas `/ready` e `/predict` na captura |
| 5 | Ação | Estado real da DAG quando comprovado; workflow como código estático; resultado da stack | `reports/airflow_execucao.json`, `reports/smoke_stack.json` e `ci.yml` |
| 6 | Resultado | Gráficos p50 do modelo em processo e HTTP do host, fora de Docker | `reports/latencia_modelo.json`, `reports/latencia_http_local.json` |
| 7 | Resultado | Aprendizados, versões, revisões e limites | Evidências e decisões do projeto |

## Preparação

1. Gere os relatórios reais de qualidade e latência. Os dois motores do benchmark HTTP precisam usar a mesma versão registrada no relatório do modelo.
2. Disponibilize a API dessa versão no endereço passado ao gerador. O script **rejeita** respostas de `/ready` ou `/predict` que usem outra versão ou motores divergentes.
3. Execute a verificação da stack. Sem relatório com sucesso, a cena declara apenas ausência de comprovação; não inventa a causa de uma falha.
4. Registre a execução Airflow no JSON descrito abaixo. Sem as quatro tarefas concluídas e um identificador de execução, o vídeo mostra código estático e declara que a execução completa não foi comprovada.
5. Execute o gerador, confira os sete PNGs em `.local/video`, escute a narração e verifique `reports/video/evidencias.json`.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/gerar_video.ps1 -ApiUrl http://127.0.0.1:8004
```

Para repetir a verificação dos contratos e da preservação do vídeo:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File reports/video/verificar_gerador.ps1 -ApiUrl http://127.0.0.1:8004
```

O modo `-SomenteImagens` permite conferir o layout sem renderizar áudio/vídeo e grava seu manifesto apenas em `.local/video/imagens/evidencias-imagens.json`, preservando o manifesto do MP4 final. O gerador registra a frase “evidências capturadas nesta execução”, os hashes das fontes e as respostas reais. Dados exibidos são públicos; não há telas pessoais, tokens ou credenciais de serviços.

Na [verificação negativa final](../reports/video/rejeicao_versao.json), a API Docker da porta 8000, com a versão `20260914T221243-003d412d`, foi rejeitada pelo gerador antes das imagens, pois os relatórios do vídeo usam a versão do host. Na renderização final, a API do host na porta 8004 forneceu a versão correta. A [verificação reproduzível](../reports/video/verificar_gerador.ps1) passou em 26 casos: rejeição de evidências inválidas, leitura independente com ffprobe e preservação dos hashes do MP4, do manifesto e dos 23 intermediários após `-SomenteImagens`. O [resultado](../reports/video/verificacao.json) registra o comando e cada caso; a [inspeção visual](../reports/video/inspecao_visual.json) identifica os sete quadros extraídos do MP4 final.

## Evidência Airflow

O coletor deve produzir `reports/airflow_execucao.json` com `sucesso` booleano, `dag_id`, `run_id` e `tarefas`. O campo `dag_id` precisa ser `retreino_medico`; os estados de `ingestao`, `treinamento`, `validacao` e `publicacao` precisam ser `success`. Um JSON ausente, incompleto ou com tarefa reprovada não autoriza narrar sucesso.

Quando essa evidência existe, a cena mostra o identificador e os quatro estados reais. O cartão do workflow GitHub é sempre identificado como código estático; não representa o estado de uma execução remota. A situação atual do CI deve ser consultada no README e na matriz. O comando `airflow dags test` executa a cadeia manualmente e, no Airflow 2.11, também aplica a tentativa adicional configurada por `retries=1`, observada na execução remota inicial.

Na apresentação final, stack e DAG usam a versão Docker `20260914T221243-003d412d`, distinta da versão `20260914T214327-e6c68fc4` da API do host e dos gráficos. A tela, a narração e os campos `versao_modelo_stack`/`versao_modelo_dag` do manifesto identificam essa separação.

## Conteúdo da narração

**Situação:** organizar resumos médicos em inglês por condição, com resposta rápida e operação verificável. Explicar que a classificação de urgência foi substituída por cinco categorias com autorização e que o uso é acadêmico.

**Tarefa:** entregar modelo leve, API, imagem, CI, retreino, métricas e otimização medida. O treinamento fica fora da API. A arquitetura AWS/ECS/ALB é uma proposta sem provisionamento.

**Ação:** mostrar as contagens reais e a política de remoção de sobreposição/conflitos. Explicar que TF-IDF aprende apenas no ajuste. A resposta da API identifica modelo e motor; probabilidades não são risco clínico calibrado. A cena operacional distingue os estados reais da DAG e da stack de trechos estáticos do workflow.

**Resultado:** apresentar acurácia e F1 do teste oficial, paridade, p50 original/ONNX e número de medições. A primeira comparação inclui normalização, vetorização e classificação. A segunda inclui o percurso HTTP **no host, fora de Docker**. Os dados Docker têm relatórios e versões separados; não são usados nesses gráficos como se fossem o mesmo ambiente.

**Aprendizados:** otimização exige preservar comportamento, medir o caminho real e manter proveniência. A validação vem de uma população filtrada e o teste preserva ambiguidades; isso não explica sozinho toda a diferença de qualidade. O serviço não foi validado para diagnóstico ou decisões clínicas.

## Entrega

O manifesto do vídeo é a fonte da duração, resolução, codecs, versão, capturas e arquivos efetivamente utilizados. O MP4 integra os arquivos deste repositório e pode ser acessado pelo link da apresentação no README.
