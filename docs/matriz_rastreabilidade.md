# Matriz de rastreabilidade — Tech Challenge Fase 3

O projeto classifica cinco condições médicas do Medical Abstracts TC Corpus. Esta matriz registra evidências de 14 e 15/09/2026. **Implementado** significa arquivo ou comportamento existente; **verificado** exige execução registrada; **em andamento** indica trabalho que continua até haver evidência. Configuração de serviço não equivale a serviço executado. A separação das imagens passou nas verificações locais e no CI completo `35033470421`, commit `34e4781`.

## Requisitos e estado

| ID | Requisito | Bloco | Evidência observada | Estado |
|---|---|---|---|---|
| R01 | Corpus real com pelo menos 2.000 exemplos | B1 | 5.285 de ajuste, 1.322 de validação e 2.888 de teste em [qualidade.json](../reports/qualidade.json) | Verificado |
| R02 | Classificador textual leve | B1 | TF-IDF + regressão logística, artefatos e versão identificados | Verificado |
| R03 | Técnica de otimização | B1 | ONNX com paridade na validação | Verificado |
| R04 | Ganho de latência | B1 | 3,52× no p50 histórico do host; 3,80× em processo na versão Docker `92cce529`; 1,35× no HTTP após separar as imagens | Verificado nos ensaios identificados |
| R05 | Qualidade e impacto da otimização | B1 | Teste: acurácia 0,639197, F1 macro 0,638544, iguais nos dois motores | Verificado |
| R06 | API FastAPI recebe texto e retorna classe | B2 | `/predict` 200 e versão no [smoke](../reports/smoke_stack.json) | Verificado |
| R07 | Validação e prontidão | B2 | Limites de entrada, testes API e prontidão 1 → 0 → 1 em parada/reinício | Verificado |
| R08 | Dockerfile funcional | B3 | [Builds locais](../reports/docker/imagem_enxuta/builds.json), [dependências](../reports/docker/imagem_enxuta/verificacoes.json) e [CI dos perfis e Airflow](../reports/ci/35033470421/execucao.json) | Verificado localmente e no CI |
| R09 | Baseline de latência HTTP | B3 | [Host histórico](../reports/latencia_http_local.json): 1,45×; [Docker com imagens separadas](../reports/docker/imagem_enxuta/latencia_http.json): 1,35× no p50 | Verificado nos dois ambientes |
| R10 | CI/CD por push | B4 | [CI 35033470421](../reports/ci/35033470421/execucao.json), commit `34e4781`, com imagens separadas | CI completo verificado; GHCR não executado |
| R11 | Pelo menos duas automações | B4 | Lint, 107 testes aprovados, builds, inventários, DAG e stack no CI 35033470421 | Verificado localmente e no GitHub Actions |
| R12 | DAG ingestão → treino → salvamento | B4 | [Quatro tarefas no CI atual](../reports/ci/35033470421/airflow-dag.log), publicação real e [execução local histórica](../reports/airflow_execucao.json) | Verificado |
| R13 | Instrumentação Prometheus | B2 | Contadores, histograma, prontidão e consultas reais | Verificado |
| R14 | API + Prometheus + Grafana via Compose | B3 | [Smoke com as imagens separadas](../reports/docker/imagem_enxuta/smoke_stack.json) com `sucesso=true` | Verificado localmente |
| R15 | Grafana com três ou mais painéis | B3 | Seis painéis e oito consultas reais | Verificado |
| R16 | Decisão de nuvem e batch/tempo real | B5 | [EC2 existente, ECR da fase 3 e SSM/OIDC](arquitetura.md) | Documentado; migração da aplicação ainda não verificada |
| R17 | Instruções de reprodução | B5 | [README](../README.md), dados, API, Compose e Airflow; execuções locais registradas | Documentado e verificado localmente |
| R18 | Histórico semântico de commits | B5 | [Histórico dos blocos e correções em main](https://github.com/callyafiune/Tech-Challenge-fase-3/commits/main) | Histórico semântico consolidado |
| R20 | Condições médicas, sem urgência | B1/B2/B5 | Classes, API e [documentação do modelo](model_card.md) | Implementado e documentado |
| R21 | Português Brasil | Todos | Documentação, comentários e relatórios explicativos | Verificado por inspeção |
| R22 | Orquestrador e revisão fable por bloco | Todos | Agente, comando e [pareceres por bloco](revisoes_adversariais.md), incluindo a [implantação AWS](verificacao_aws.md) | Verificado; correções e limites documentados |
| R24 | Imagem de inferência enxuta | B3 | API com 23 distribuições e redução local medida de 62,56%; [perfis e medidas](imagens_docker.md) | Verificado localmente e no CI |

## Dados e resultados

A revisão fixa do corpus é `70a2d9106c724729be8b3c4ddb00d1b14ec300c8`, com hashes no [manifesto](../src/medical_classifier/corpus_manifest.json). Das 11.550 linhas de treino, foram removidas 1.097 sobreposições com o teste e 3.846 linhas de textos conflitantes. As 6.607 restantes geraram ajuste/validação estratificados com semente 42. O teste oficial preservou suas 2.888 linhas.

O teste contém 2.770 textos únicos e 231 linhas ambíguas; o teto de acurácia determinística apenas pelo texto é 95,9141%. A validação foi extraída da população filtrada. A diferença entre F1 de validação 0,784904 e teste 0,638544 não é explicada integralmente pela ambiguidade.

| Ambiente e versão | Medição | Original p50 | ONNX p50 | Aceleração | Fonte |
|---|---|---:|---:|---:|---|
| Windows, `20260914T214327-e6c68fc4` | Modelo em processo, 400 amostras/motor | 1,2419 ms | 0,3532 ms | 3,52× | [Relatório](../reports/latencia_modelo.json) |
| Windows, mesma versão | HTTP local, 200 amostras/motor | 7,7405 ms | 5,3488 ms | 1,45× | [Relatório](../reports/latencia_http_local.json) |
| Docker Linux/WSL2, `20260914T214809-a767fe94` | Modelo em processo, sem HTTP, 400 amostras/motor | 1,226336 ms | 0,328270 ms | 3,74× | [Relatório](../reports/docker/latencia_modelo.json) |
| Servidores Docker, `20260914T221243-003d412d`; cliente Windows | HTTP, 200 amostras/motor | 5,41015 ms | 4,0585 ms | 1,33× | [Relatório](../reports/docker/latencia_http.json) |
| Docker local após correção, `20260914T232434-92cce529` | Modelo em processo, 400 amostras/motor | 1,317915 ms | 0,346612 ms | 3,80× | [Relatório](../reports/docker/pos_correcao/latencia_modelo.json) |
| Servidores Docker após correção, mesma versão; cliente Windows | HTTP, 200 amostras/motor | 5,68385 ms | 4,5707 ms | 1,24× | [Relatório](../reports/docker/pos_correcao/latencia_http.json) |
| Servidores Docker com imagens separadas, mesma versão; cliente Windows | HTTP, 200 amostras/motor | 6,8721 ms | 5,1066 ms | 1,35× | [Relatório](../reports/docker/imagem_enxuta/latencia_http.json) |
| GitHub Actions, `20260914T232314-d0a18808` | Modelo em processo, 400 amostras/motor | 0,744446 ms | 0,239354 ms | 3,11× | [Relatório](../reports/ci/34908437830/20260914T000000-latencia_modelo.json) |
| GitHub Actions após auditoria, `20260915T022734-e031e4fb` | Modelo em processo, 400 amostras/motor | 0,803890 ms | 0,227785 ms | 3,53× | [Relatório](../reports/ci/34921095963/20260914T000000-latencia_modelo.json) |
| GitHub Actions com imagens separadas, `20260915T230048-695b0121` | Modelo em processo, 400 amostras/motor | 0,751024 ms | 0,240916 ms | 3,12× | [Relatório](../reports/ci/35033470421/20260914T000000-latencia_modelo.json) |

Host e Docker têm versões e ambientes próprios. Os benchmarks usam lote um, os mesmos textos entre motores e ordem alternada. O piso de aceleração p50 é uma regra local sujeita a ruído; não há SLO nem medição de saturação.

## Infraestrutura observada

A [execução Docker](../reports/docker/execucao_stack.json) registra imagem `sha256:7d38ef63d2fef92e29b7f552013cea65f4dc8b6a18d11453d16e7e900fa746f8`, treino com rede `none`, UID/GID `10001:10001`, raiz somente para leitura e saída zero. O reaproveitamento retornou `reutilizado=true` mantendo a versão. A API monta os modelos sem permissão de escrita.

O [smoke](../reports/smoke_stack.json) da versão `20260914T221243-003d412d` confirmou 21 chamadas válidas e duas rejeições, coleta ativa, fonte Grafana `OK`, seis painéis e oito consultas. Registra a imagem `sha256:04875aff7dd271b654986a33392e577fe3a09d6c2769875b023ca560fc837377` e o estado `healthy`. O JSON do dashboard isoladamente não foi usado como prova de funcionamento.

O [teste de indisponibilidade](../reports/docker/readiness_indisponibilidade.json) registrou prontidão 1 antes da parada, 0 durante a parada e 1 após reinício. Seu horário é anterior ao smoke da versão mais recente; comprova o comportamento da consulta, sem ser apresentado como execução desse mesmo modelo.

Uma tentativa histórica de construção Airflow foi interrompida por espaço, conforme [registro](../reports/airflow_build_state.json). A [construção posterior](../reports/docker/build_airflow_state.json) foi concluída em 124,2 segundos, e a [execução real](../reports/airflow_execucao.json) registra quatro tarefas em `success`, na DAG `retreino_medico`, execução `manual__2026-09-14T00:00:00+00:00`. O modelo publicado foi `20260914T221243-003d412d`, com a versão anterior preservada no ponteiro. O [comando de teste](../reports/docker/airflow_execution_steps.json) levou 66,6 segundos; a data lógica da DAG não é usada para calcular duração. O standalone iniciou em 25,28 segundos, com metadatabase, scheduler e triggerer saudáveis na consulta registrada.

## Testes e revisões

O [CI atual 35033470421](../reports/ci/35033470421/execucao.json), job `104597112047`, concluiu com sucesso no commit remoto `34e478123d94854198cf4788580b40d539d8d86c`. Sua árvore `affdc3337b704c42efe73e4fb84527d7c951f8af` coincide com o commit local `13e89a0`. O [JUnit](../reports/ci/35033470421/testes.xml) registra 107 testes aprovados, um ignorado, zero erros e zero falhas. Builds dos perfis/Airflow, inventários, quatro tarefas reais e [smoke](../reports/ci/35033470421/smoke_stack.json) passaram. A versão publicada no runner foi `20260915T230048-695b0121`. Os [dois runners de diagnóstico](../reports/ci/35033470146/execucao.json) também concluíram com sucesso na mesma revisão.

O ciclo anterior da auditoria foi concluído no [CI 34921095963](../reports/ci/34921095963/execucao.json), commit `6426446`: 104 testes aprovados, imagens, quatro tarefas Airflow e stack verificados. A [atualização local daquele ciclo](../reports/auditoria_criterios/runtime_final.json) conferiu as fontes corrigidas dentro da API e do Airflow, preservou o modelo `92cce529` e manteve os quatro serviços saudáveis. Seu [smoke](../reports/auditoria_criterios/smoke_stack_final.json) tem arquivo próprio. Esse CI não verificou a separação posterior dos perfis Docker.

A [integração local após a correção](../reports/docker/pos_correcao/integracao_verificada.json) concluiu as quatro tarefas em 30,02 segundos e publicou `20260914T232434-92cce529`, mantendo a versão anterior. A API carregou a nova versão e os quatro serviços ficaram saudáveis; o novo smoke confirmou seis painéis e oito consultas. O commit local `fa821ef` e o remoto `3a7ad7f` possuem a mesma árvore Git, `1372ea830ae67647d3a6f50c9a5cee84d5dc0f75`; o SHA-256 do exportador também foi conferido dentro do Airflow.

A suíte consolidada em [testes.xml](../reports/testes.xml) registra **107 casos aprovados, um ignorado, zero falhas e zero erros**. Ruff passou na análise e formatação de 25 arquivos, conforme o [registro local](../reports/docker/imagem_enxuta/verificacao_codigo.json). O caso ignorado exige o ambiente Airflow real; execuções históricas da DAG e sua importação atual são registradas separadamente. Esse resultado local é independente da execução remota de CI. A [auditoria dos entregáveis disponíveis](auditoria_criterios.md) identifica as verificações e seus limites.

Os pareceres mais recentes estão em [reports/reviews](../reports/reviews/), com rodadas anteriores nos subdiretórios numerados. Os manifestos preservam a solicitação `fable`, o uso de `claude-fable-5-1` e o modelo auxiliar reportado pela CLI. Parecer concluído não equivale a aprovação. O [tratamento dos achados](revisoes_adversariais.md) registra a contagem de rodadas, correções e decisões justificadas.

## Critérios de avaliação

O recorte abaixo considera somente os entregáveis disponíveis e não afirma atendimento integral ao enunciado. Os pesos originais dos critérios incluídos foram preservados.

| Critério | Peso | Evidência disponível | Trabalho em acompanhamento |
|---|---:|---|---|
| Modelagem e otimização | 20% | Corpus real, qualidade, paridade e benchmarks | Vincular qualquer alteração posterior aos relatórios |
| CI/CD | 15% | Workflows e CI 35033470421 completo com imagens separadas | GHCR ainda não publicado |
| Orquestração | 15% | Quatro tarefas concluídas no Airflow real, publicação e standalone consultado | Execução local registrada; implantação na EC2 preparada |
| Monitoramento | 20% | Compose e smoke local/remoto com seis painéis/oito consultas | Repetir verificações se houver novas alterações de implementação |
| Documentação | 15% | README, arquitetura, modelo, plano, matriz, guia Linux/macOS e quatro revisões B5 | Histórico semântico consolidado |

## Etapa posterior — otimização das imagens Docker

Os [builds](../reports/docker/imagem_enxuta/builds.json) produziram runtime, treinamento e Airflow. A [comparação antes/depois](../reports/docker/imagem_enxuta/depois.json) registra API de **246.360.476 → 92.232.108 bytes (−62,56%)** e Airflow de **303.130.457 → 214.284.627 bytes (−29,31%)**. A imagem de treinamento mede 165.226.468 bytes. Esses valores são do campo Docker `Size`, não do consumo exclusivo de disco ou da transferência de rede.

Os perfis [runtime](../reports/docker/imagem_enxuta/runtime-dependencias.json) e [treinamento](../reports/docker/imagem_enxuta/treinamento-dependencias.json) passaram com 23 e 35 distribuições. Os [50 pins foram preservados](../reports/docker/imagem_enxuta/pins_preservados.json). Quatro `pip check` externos e imports reais passaram nas [verificações isoladas](../reports/docker/imagem_enxuta/verificacoes.json). A [DAG importada](../reports/docker/imagem_enxuta/dag-importacao.json) tem quatro tarefas, três dependências e nenhuma falha de importação; esse ensaio não executou retreino.

A [operação atual](../reports/docker/imagem_enxuta/runtime_verificado.json) reutilizou o modelo `20260914T232434-92cce529`, com `pipeline_reutilizado=true`. A captura identifica cinco serviços saudáveis durante o benchmark, incluindo a API scikit-learn temporária, encerrada depois da medição. API principal, Prometheus, Grafana e Airflow permanecem operacionais. O [smoke atual](../reports/docker/imagem_enxuta/smoke_stack.json) confirmou 101 chamadas válidas, duas rejeições, seis painéis e oito consultas. O [HTTP atual](../reports/docker/imagem_enxuta/latencia_http.json) usa 200 chamadas e 20 aquecimentos por motor, em outro ensaio da mesma versão preservada.

A quarta revisão B3 gerou correções posteriores ao snapshot: pré-requisito de build do Airflow documentado, Compose de benchmark incluído na validação CI e teste de imports ampliado. Actionlint 1.7.12 e o CI completo `35033470421` passaram no workflow atualizado. O [ensaio de partida](../reports/docker/imagem_enxuta/partida.json) mediu medianas de **3,6301 s antes e 3,3974 s depois** até `/ready`, com três observações por imagem e todas abaixo de 80 s. Caches e carga não isolados impedem atribuir significância estatística ou SLO.

A execução remota inicial [34904519738](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/runs/34904519738) falhou no gate de paridade ONNX durante o treino da DAG. O [CI posterior 34905435615](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/runs/34905435615) concluiu com sucesso, com instrumentação de erro e os mesmos critérios preservados. A falha voltou no [CI 34906533919](../reports/ci/34906533919/execucao.json). A [investigação por camada](diagnostico_paridade.md) identificou e corrigiu a representação de bigramas no conversor: erro de validação de 0,009424 para 1,93 × 10⁻⁷ no candidato remoto, sem novo ajuste. O [CI da correção do exportador 34908437830](../reports/ci/34908437830/execucao.json) confirmou o ciclo completo corrigido, e dois runners de diagnóstico confirmaram a paridade. Os registros identificam commits e artefatos. Não há push GHCR ou implantação AWS comprovados. As evidências locais permanecem válidas dentro dos ambientes identificados.
