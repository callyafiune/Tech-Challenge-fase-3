# Matriz de rastreabilidade — Tech Challenge Fase 3

O objetivo autorizado é classificar cinco condições médicas do Medical Abstracts TC Corpus, em vez de urgência. Esta matriz registra evidências de 14/09/2026. **Implementado** significa arquivo ou comportamento existente; **verificado** exige execução registrada; **em andamento** indica trabalho que continua até haver evidência. Configuração de serviço não equivale a serviço executado.

## Requisitos e estado

| ID | Requisito | Bloco | Evidência observada | Estado |
|---|---|---|---|---|
| R01 | Corpus real com pelo menos 2.000 exemplos | B1 | 5.285 de ajuste, 1.322 de validação e 2.888 de teste em [qualidade.json](../reports/qualidade.json) | Verificado |
| R02 | Classificador textual leve | B1 | TF-IDF + regressão logística, artefatos e versão identificados | Verificado |
| R03 | Técnica de otimização | B1 | ONNX com paridade na validação | Verificado |
| R04 | Ganho de latência | B1 | 3,52× no p50 histórico do host; 3,80× em processo e 1,24× via HTTP na versão Docker `92cce529` | Verificado |
| R05 | Qualidade e impacto da otimização | B1 | Teste: acurácia 0,639197, F1 macro 0,638544, iguais nos dois motores | Verificado |
| R06 | API FastAPI recebe texto e retorna classe | B2 | `/predict` 200 e versão no [smoke](../reports/smoke_stack.json) | Verificado |
| R07 | Validação e prontidão | B2 | Limites de entrada, testes API e prontidão 1 → 0 → 1 em parada/reinício | Verificado |
| R08 | Dockerfile funcional | B3 | [Imagem, treino sem rede, usuário e permissões](../reports/docker/execucao_stack.json) | Verificado |
| R09 | Baseline de latência HTTP | B3 | [Host histórico](../reports/latencia_http_local.json): 1,45×; [Docker atual](../reports/docker/pos_correcao/latencia_http.json): 1,24× no p50 | Verificado nos dois ambientes |
| R10 | CI/CD por push | B4 | [CI completo com a correção ONNX](../reports/ci/34908437830/execucao.json), commit `3a7ad7f` | CI verificado; publicação GHCR não executada |
| R11 | Pelo menos duas automações | B4 | Lint, 78 testes aprovados, builds, DAG e stack concluídos no CI 34908437830 | Verificado no ambiente local e no GitHub Actions |
| R12 | DAG ingestão → treino → salvamento | B4 | [Quatro tarefas concluídas](../reports/airflow_execucao.json), publicação real e standalone consultado | Verificado |
| R13 | Instrumentação Prometheus | B2 | Contadores, histograma, prontidão e consultas reais | Verificado |
| R14 | API + Prometheus + Grafana via Compose | B3 | [Smoke da stack](../reports/smoke_stack.json) com `sucesso=true` | Verificado |
| R15 | Grafana com três ou mais painéis | B3 | Seis painéis e oito consultas reais | Verificado |
| R16 | Decisão de nuvem e batch/tempo real | B5 | [Arquitetura AWS proposta](arquitetura.md) | Documentado; AWS não provisionada |
| R17 | Instruções de reprodução | B5 | [README](../README.md), dados, API, Compose e Airflow; execuções locais registradas | Documentado e verificado localmente |
| R18 | Histórico semântico de commits | B5 | [Histórico dos blocos e correções em main](https://github.com/callyafiune/Tech-Challenge-fase-3/commits/main) | Histórico semântico consolidado |
| R19 | Vídeo STAR até cinco minutos | B5 | [MP4](../reports/video/apresentacao_star.mp4) com 260,876417 segundos, oito cenas e monitoração explicada; [manifesto](../reports/video/evidencias.json) | Vídeo verificado e publicado no próprio repositório |
| R20 | Condições médicas, sem urgência | B1/B2/B5 | Classes, API e [documentação do modelo](model_card.md) | Implementado e documentado |
| R21 | Português Brasil | Todos | Documentação, comentários e relatórios explicativos | Verificado por inspeção |
| R22 | Orquestrador e revisão fable por bloco | Todos | Agente, comando e 17 pareceres concluídos; B1 e B5 com quatro pareceres válidos cada | Verificado; correções e limites documentados |
| R23 | Referência à fase 2 | B5 | Padrões e diferenças no README/arquitetura | Documentado |

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
| GitHub Actions, `20260914T232314-d0a18808` | Modelo em processo, 400 amostras/motor | 0,744446 ms | 0,239354 ms | 3,11× | [Relatório](../reports/ci/34908437830/20260914T000000-latencia_modelo.json) |

Host e Docker têm versões e ambientes próprios. Os benchmarks usam lote um, os mesmos textos entre motores e ordem alternada. O piso de aceleração p50 é uma regra local sujeita a ruído; não há SLO nem medição de saturação.

## Infraestrutura observada

A [execução Docker](../reports/docker/execucao_stack.json) registra imagem `sha256:7d38ef63d2fef92e29b7f552013cea65f4dc8b6a18d11453d16e7e900fa746f8`, treino com rede `none`, UID/GID `10001:10001`, raiz somente para leitura e saída zero. O reaproveitamento retornou `reutilizado=true` mantendo a versão. A API monta os modelos sem permissão de escrita.

O [smoke](../reports/smoke_stack.json) da versão `20260914T221243-003d412d` confirmou 21 chamadas válidas e duas rejeições, coleta ativa, fonte Grafana `OK`, seis painéis e oito consultas. Registra a imagem `sha256:04875aff7dd271b654986a33392e577fe3a09d6c2769875b023ca560fc837377` e o estado `healthy`. O JSON do dashboard isoladamente não foi usado como prova de funcionamento.

O [teste de indisponibilidade](../reports/docker/readiness_indisponibilidade.json) registrou prontidão 1 antes da parada, 0 durante a parada e 1 após reinício. Seu horário é anterior ao smoke da versão mais recente; comprova o comportamento da consulta, sem ser apresentado como execução desse mesmo modelo.

Uma tentativa histórica de construção Airflow foi interrompida por espaço, conforme [registro](../reports/airflow_build_state.json). A [construção posterior](../reports/docker/build_airflow_state.json) foi concluída em 124,2 segundos, e a [execução real](../reports/airflow_execucao.json) registra quatro tarefas em `success`, na DAG `retreino_medico`, execução `manual__2026-09-14T00:00:00+00:00`. O modelo publicado foi `20260914T221243-003d412d`, com a versão anterior preservada no ponteiro. O [comando de teste](../reports/docker/airflow_execution_steps.json) levou 66,6 segundos; a data lógica da DAG não é usada para calcular duração. O standalone iniciou em 25,28 segundos, com metadatabase, scheduler e triggerer saudáveis na consulta registrada.

## Testes e revisões

A [integração local após a correção](../reports/docker/pos_correcao/integracao_verificada.json) concluiu as quatro tarefas em 30,02 segundos e publicou `20260914T232434-92cce529`, mantendo a versão anterior. A API carregou a nova versão e os quatro serviços ficaram saudáveis; o novo smoke confirmou seis painéis e oito consultas. O commit local `fa821ef` e o remoto `3a7ad7f` possuem a mesma árvore Git, `1372ea830ae67647d3a6f50c9a5cee84d5dc0f75`; o SHA-256 do exportador também foi conferido dentro do Airflow.

A suíte consolidada em [testes.xml](../reports/testes.xml) registra **104 casos aprovados, um ignorado, zero falhas e zero erros**. O caso ignorado exige o ambiente Airflow real; a DAG foi executada separadamente no container. Esse resultado local é independente da execução remota de CI. A [auditoria dos seis critérios](auditoria_criterios.md) identifica as verificações finais e as correções decorrentes da conferência.

Os pareceres mais recentes estão em [reports/reviews](../reports/reviews/), com rodadas anteriores nos subdiretórios numerados. Os manifestos preservam a solicitação `fable`, o uso de `claude-fable-5-1` e o modelo auxiliar reportado pela CLI. Parecer concluído não equivale a aprovação. O [tratamento dos achados](revisoes_adversariais.md) registra a contagem de rodadas, correções e decisões justificadas.

## Critérios de avaliação

| Critério | Peso | Evidência disponível | Trabalho em acompanhamento |
|---|---:|---|---|
| Modelagem e otimização | 20% | Corpus real, qualidade, paridade e benchmarks | Vincular qualquer alteração posterior aos relatórios |
| CI/CD | 15% | Workflows e CI remoto 34908437830 concluído com imagem validada | Publicação manual GHCR disponível, além do lint/test/build exigido |
| Orquestração | 15% | Quatro tarefas concluídas no Airflow real, publicação e standalone consultado | Execução local registrada; produção permanece fora do escopo provisionado |
| Monitoramento | 20% | Compose e smoke com seis painéis/oito consultas | Repetir verificações afetadas por correções posteriores |
| Documentação | 15% | README, arquitetura, modelo, plano, matriz, guia Linux/macOS e quatro revisões B5 | Histórico semântico consolidado |
| Vídeo STAR | 15% | Roteiro e MP4 final de 4min21s, oito cartões inspecionados e narração sintética | Configuração da monitoração e resultados reais demonstrados |

A execução remota inicial [34904519738](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/runs/34904519738) falhou no gate de paridade ONNX durante o treino da DAG. O [CI posterior 34905435615](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/runs/34905435615) concluiu com sucesso, com instrumentação de erro e os mesmos critérios preservados. A falha voltou no [CI 34906533919](../reports/ci/34906533919/execucao.json). A [investigação por camada](diagnostico_paridade.md) identificou e corrigiu a representação de bigramas no conversor: erro de validação de 0,009424 para 1,93 × 10⁻⁷ no candidato remoto, sem novo ajuste. O [CI final 34908437830](../reports/ci/34908437830/execucao.json) confirmou o ciclo completo corrigido, e dois runners de diagnóstico confirmaram a paridade. Os registros identificam commits e artefatos. Não há push GHCR ou infraestrutura AWS comprovados. O MP4 integra os arquivos do repositório. As evidências locais permanecem válidas dentro dos ambientes identificados.
