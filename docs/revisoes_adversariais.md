# Revisões adversariais e tratamento dos achados

As revisões por bloco usam Claude Code, modelo `fable`. O [comando de revisão](../scripts/review_block.py) envia um snapshot literal numerado pela entrada padrão, sem ferramentas de leitura ou escrita habilitadas. Preserva JSON completo, parecer e manifesto com hashes, horários, modelo solicitado e código de saída.

As revisões são estáticas: o revisor não executou testes nem serviços. **Código zero da CLI não significa aprovação.** Os achados foram confrontados com o código, corrigidos quando confirmados ou documentados como decisões e limitações.

## Rodadas realizadas

| Bloco | Primeira rodada | Parecer mais recente | Tratamento |
|---|---|---|---|
| B1 — Dados e otimização | [Parecer](../reports/reviews/rodada-1/B1.md) | [Quarto parecer válido](../reports/reviews/B1.md) | Auditoria, exportação, aprovação completa na promoção/reuso e revalidação |
| B2 — API e métricas | [Parecer](../reports/reviews/rodada-1/B2.md) | [Parecer](../reports/reviews/B2.md) | Aquecimento, corpo limitado e métricas de desconexão/rejeição corrigidos |
| B3 — Containers e monitoramento | [Parecer](../reports/reviews/rodada-1/B3.md) | [Quarto parecer](../reports/reviews/B3.md) | Perfis runtime/treinamento, fechamento das dependências, builds, benchmark e integração |
| B4 — Airflow, CI/CD e AWS | [Parecer](../reports/reviews/rodada-1/B4.md) | [Parecer](../reports/reviews/B4.md) | Mesma imagem validada, implantação na EC2, limites e recuperação; [verificação AWS](verificacao_aws.md) |
| B5 — Documentação | [Parecer histórico](../reports/reviews/rodada-1/B5.md) | [Quarto parecer histórico](../reports/reviews/B5.md) | Consistência dos relatórios, versões e ambientes; situação atual na auditoria dos entregáveis |

Os manifestos acompanham os pareceres com sufixo `-manifest.json`. Até a separação das imagens foram concluídos **18 pareceres**: quatro de B1, dois de B2, quatro de B3, quatro de B4 e quatro de B5. Os diretórios `rodada-1` a `rodada-5` e `pre-aws` preservam esses snapshots, incluindo tentativas que falharam. As revisões adicionais de implantação ficam em `aws-1`, `aws-2` e no parecer B4 atual, com tratamento em [verificacao_aws.md](verificacao_aws.md). Nas chamadas concluídas, a solicitação foi `fable` e a CLI reportou `claude-fable-5-1`. Também listou `claude-haiku-4-5-20251001` entre os modelos utilizados internamente; o registro original foi preservado. O script não substituiu o modelo solicitado nem atribui artificialmente cada trecho do parecer a um modelo.

As duas tentativas suplementares B1 que receberam HTTP 429 estão preservadas em `rodada-3/B1.*` e `rodada-4/B1.*`; elas não contam como parecer. Após a renovação do limite, duas novas revisões B1 foram concluídas, em `rodada-5/B1.*` e `reports/reviews/B1.*`. As correções posteriores aos snapshots são verificadas pelo orquestrador e identificadas abaixo, sem convertê-las em aprovação automática do Claude.

## B1 — Dados e modelos

| Achado | Tratamento e evidência |
|---|---|
| Validação filtrada e teste de população diferente | Auditoria agora registra 2.770 textos únicos, 231 linhas ambíguas e teto determinístico de acurácia de 95,9141% no teste. A documentação não atribui toda a queda à ambiguidade |
| Publicação com F1 inferior | Quando o hash de validação coincide, bloqueia queda de F1 macro além de `1e-6`; o ponteiro preserva a versão anterior |
| ONNX sem ganho | `validate` bloqueia fator p50 abaixo de 1; teste cobre reprovação de um motor mais lento |
| Configuração incompleta nos metadados | Parâmetros derivados dos estimadores; versões do conversor/runtime e iterações do solver registradas |
| Partições alteradas entre tarefas | Hashes dos CSVs preparados conferidos no treino e validação, inclusive contra a auditoria da versão |
| Relatórios de outra versão no reuso | `--reutilizar` exige aprovação, identificação da versão e hashes correspondentes; confere também a versão do relatório de latência |
| Relatórios ausentes na promoção ou no reuso | Ambos exigem avaliação aprovada, versão, hashes e latência finita. O helper de publicação confere os relatórios antes inclusive do retorno idempotente |
| Artefatos parciais após reprovação | Treino/exportação em diretório temporário antes de disponibilizar a versão |
| Lacunas de cobertura | Casos para conflitos, corrupção, publicação reprovada, partição alterada, regressão de F1 e reprovação de latência |

Três decisões foram mantidas. Corrupção local causa erro e preserva o arquivo; não há remoção e novo download automáticos. A paridade de `argmax` é exata, embora empates numéricos possam reprovar conversões próximas. O piso de latência é conservador e sujeito a ruído de CPU: aquecimento, 400 amostras pareadas e ordem alternada não constituem SLO nem intervalo de confiança. A tentativa adicional do Airflow não elimina essa limitação.

O diretório de modelos é confiável. Hashes detectam corrupção ou troca acidental; não impedem quem possa editar simultaneamente modelo, metadados e ponteiro. As classes são o contrato fixo dos identificadores 1 a 5 dessa revisão, sem descoberta dinâmica de novas categorias. A documentação distingue modelo candidato avaliado e versão efetivamente apontada por `current.json`.

A integração remota encontrou depois uma falha concreta não detectada pelos pareceres estáticos: um bigrama podia ser convertido como token único quando faltava um componente no vocabulário individual. A [reprodução por camada](diagnostico_paridade.md) localizou a causa, e a exportação passou a fornecer tuplas explícitas em cópia do pipeline. O teste de regressão falhou antes e passou depois; outro teste preserva integralmente o baseline. O candidato remoto reconvertido passou em validação e teste completos, sem novo ajuste nem relaxamento dos limites. A primeira solicitação suplementar falhou com 429; as revisões posteriores concluídas examinaram a correção e seus testes.

## B2 — API e métricas

Os achados resultaram em checagens de forma, finitude, intervalo e soma das probabilidades, aquecimento antes da prontidão, identificação do modelo nas métricas, probes assíncronas e limite de corpo de 128 KiB antes da decodificação JSON, inclusive em transferência fragmentada.

Desconexões durante a leitura são observadas como **499**, sem inflar 5xx. Caminhos conhecidos são preservados antes do roteamento para que respostas 413 de `/predict` apareçam no painel correspondente; caminhos arbitrários continuam agrupados. A documentação distingue o limite de caracteres do texto do limite de bytes do corpo.

A política de inicialização foi mantida: falha de carregamento preserva `/health`, deixa `/ready` em 503 e impede predição. A alternativa de encerrar imediatamente o processo não foi adotada. Logs registram somente o tipo da exceção, sem texto médico. Dependências são fixadas no lock; atualizar Starlette exige repetir testes de normalização das rotas.

## B3 — Docker e Grafana

O parecer identificou que o smoke daquele snapshot era de uma versão anterior. A [nova execução](../reports/smoke_stack.json) usa `20260914T221243-003d412d`, publicada pelo Airflow, e registra o digest da imagem e `healthy`. Confirmou 23 chamadas: 21 válidas e duas rejeições. Os seis painéis totalizam oito consultas reais. A [evidência anterior de treino offline e permissões](../reports/docker/execucao_stack.json) preserva sua própria versão e imagem, sem ser apresentada como execução da versão mais recente.

O painel de prontidão combina `model_ready` com `up`. O [ensaio de parada e reinício](../reports/docker/readiness_indisponibilidade.json) registrou 1 → 0 → 1. Fonte Grafana e provisionamento foram consultados diretamente.

Observações operacionais seguem acompanhadas: uma janela curta de taxa pode ficar sem amostras se o Grafana demorar; a verificação precisa sustentar tráfego durante suas consultas. Alterar `.env` não modifica a senha já persistida no Grafana, e falhas 401/403 devem ser distinguidas de falha da fonte. Nas imagens anteriores, o lock completo levava ferramentas de desenvolvimento para a API. A quarta rodada acompanha a separação dos perfis: o lock completo permanece no host/CI, e a imagem de inferência usa apenas o lock de runtime.

O Compose de benchmark é complementar, com uso dos dois `-f` documentado. O [benchmark HTTP do host](../reports/latencia_http_local.json) e o [HTTP de servidores Docker](../reports/docker/latencia_http.json) têm metadados, endpoints e versões próprios. O benchmark do modelo em Docker continua identificado como inferência sem HTTP.

Na terceira rodada B3, a espera por painel em um instante já fixado foi removida: uma consulta sem valor finito agora falha imediatamente. A consistência de dependências é conferida por `pip check`. A construção posterior usa um estágio exclusivo para o wheel e ambientes distintos por perfil; o README deixou de participar do contexto usado na construção do pacote. A base usa tag versionada e os locks fixam versões sem hashes de wheels: os digests registrados identificam cada execução, mas não garantem reprodução binária de builds futuros.

### Quarta rodada B3 — separação das imagens

O [parecer](../reports/reviews/B3.md) não encontrou defeito crítico reproduzível por leitura. Os itens confirmados foram tratados depois do snapshot:

| Achado | Tratamento e limite |
|---|---|
| Build Airflow depende da imagem local de treinamento | O Compose informa o pré-requisito `docker compose build pipeline`; os guias mostram `docker compose build api pipeline` antes do Airflow. A dependência permanece explícita, sem tentativa de buscar uma imagem privada |
| Compose de benchmark não validado no CI | O workflow passou a executar `docker compose -f docker-compose.yml -f docker-compose.benchmark.yml config --quiet` |
| Imports de treinamento não bloqueados pelo teste isolado | A lista foi ampliada com `ml_dtypes`, `dateutil`, `pytz`, `six` e `tzdata`, além dos módulos de treinamento já bloqueados |
| Imports de Pydantic/Starlette e Packaging como transitivas | Pydantic e Starlette foram mantidos como dependências obrigatórias de FastAPI dentro das faixas fixadas. Os locks e o fechamento real conferem sua presença; nenhuma versão foi atualizada. O verificador documenta seu uso de Packaging, exigido por ONNX Runtime |
| Inclusão relativa do lock de runtime | O Dockerfile documenta que o estágio de treinamento herda `/tmp/requirements-runtime.lock`, permitindo a inclusão relativa |
| Custo de partida sem bytecode | [Ensaio até `/ready`](../reports/docker/imagem_enxuta/partida.json): três observações por imagem, medianas de 3,6301 s antes e 3,3974 s depois, todas abaixo de 80 s. Caches e carga não isolados; não estabelece ganho estatístico ou SLO |
| Arquivos de integração ausentes do snapshot | Imports reais nos dois perfis, quatro `pip check` externos e importação da DAG complementam o parecer; o [CI 35033470421](../reports/ci/35033470421/execucao.json) também concluiu builds, quatro tarefas e stack |

A [comparação de tamanho](../reports/docker/imagem_enxuta/depois.json) registra redução de **62,56% na API** e **29,31% no Airflow**, no mesmo campo `Size` usado na [captura anterior](../reports/docker/imagem_enxuta/antes.json). Os perfis [runtime](../reports/docker/imagem_enxuta/runtime-dependencias.json) e [treinamento](../reports/docker/imagem_enxuta/treinamento-dependencias.json) têm 23 e 35 distribuições, sem pacotes fora do fechamento ou proibidos. As [verificações dos ambientes](../reports/docker/imagem_enxuta/verificacoes.json) passaram sem rede e sem volumes de modelo montados. A [DAG importada](../reports/docker/imagem_enxuta/dag-importacao.json) tem quatro tarefas e três dependências; essa inspeção não executou retreino.

As verificações locais posteriores ao snapshot registram **107 testes aprovados e um ignorado**, com Ruff em 25 arquivos. O [CI 35033470421](../reports/ci/35033470421/execucao.json) repetiu **107 testes aprovados e um ignorado**, construiu os perfis e o Airflow, validou dependências, executou as quatro tarefas da DAG e verificou a stack. O commit remoto `34e4781` e o local `13e89a0` têm a mesma árvore `affdc3337b704c42efe73e4fb84527d7c951f8af`. O CI `34921095963` permanece como evidência do empacotamento anterior. Os modelos locais e relatórios históricos foram preservados.

A [comparação dos pins](../reports/docker/imagem_enxuta/pins_preservados.json) confirmou 50 versões idênticas. A [operação atual](../reports/docker/imagem_enxuta/runtime_verificado.json) reutilizou o modelo `92cce529`; o [HTTP](../reports/docker/imagem_enxuta/latencia_http.json) mediu p50 de 6,8721 → 5,1066 ms, em 200 chamadas por motor, e o [smoke](../reports/docker/imagem_enxuta/smoke_stack.json) confirmou 101 chamadas válidas, duas rejeições, seis painéis e oito consultas. No runner, o retreino publicou `20260915T230048-695b0121`, com [p50 em processo de 0,751024 → 0,240916 ms](../reports/ci/35033470421/20260914T000000-latencia_modelo.json), ou 3,12×. Os [dois runners de diagnóstico](../reports/ci/35033470146/execucao.json) também concluíram com sucesso. Cada resultado permanece vinculado ao seu ambiente e versão.

## B4 — Airflow e entrega

O gate da tarefa exige aprovação explicitamente igual a `True`, vinculada à versão da execução. Etapas anteriores invalidam a aprovação, e estado ausente gera erros descritivos. Testes exercitam a publicação real e falhas isoladas.

A entrega carrega **a mesma imagem validada pelo CI**, conferindo SHA-256 e ID, em vez de reconstruí-la. Os volumes compartilhados são externos ao Compose Airflow. A retenção manual preserva versão atual, anterior e relatórios; não se apagam esses volumes para limpar o orquestrador.

Na quarta rodada B4, a saída vazia do identificador do artefato passou a ser rejeitada antes do download. O caminho `imagem/` continua fazendo parte do contrato entre quem grava e quem verifica o checksum. O artefato de imagem expira em sete dias; depois disso é necessário executar o CI completo para produzir outra imagem validada. Publicações manuais não são serializadas: `latest` pode representar o envio que terminou por último, portanto a tag do commit identifica a imagem a utilizar. São limites operacionais registrados, sem alegação de publicação GHCR já verificada.

A imagem Airflow passou a reutilizar a imagem de treinamento, com ambientes Python separados e constraints fixadas por revisão/SHA-256. A DAG usa o interpretador via `python -m`; o link de `/opt/model-venv` para `/opt/venv` preserva os shebangs. A API carrega a versão publicada somente após reinício, documentado como passo operacional. As rodadas adicionais de B3/B4 revisaram as alterações de infraestrutura.

O [estado histórico da construção](../reports/airflow_build_state.json) registra uma tentativa interrompida por falta de espaço. A [construção posterior](../reports/docker/build_airflow_state.json) terminou com código zero em 124,2 segundos. A [execução real](../reports/airflow_execucao.json) concluiu as quatro tarefas, publicou uma nova versão e confirmou a saúde de metadatabase, scheduler e triggerer do standalone. O comando `dags test` levou 66,6 segundos, conforme o registro de comandos; a data lógica da DAG não mede esse intervalo. A instrumentação da falha remota de paridade permitiu reproduzir e corrigir a representação dos bigramas, mantendo os critérios originais. O Airflow 2.11 aplicou `retries=1` também no comando `dags test`; a documentação anterior que restringia esse comportamento ao agendador foi corrigida.

## Situação consolidada

A revisão B5 confirmou a consistência aritmética dos relatórios e orientou a identificação dos ambientes e das versões examinadas. O estado da DAG vem de `reports/airflow_execucao.json`, com quatro tarefas concluídas e uma execução identificada. O plano remete à matriz como fonte de andamento, e o README inclui autoria/licença do corpus. O guia de execução documenta os benchmarks do host em portas independentes.

A suíte histórica anterior registrava 78 casos aprovados e um ignorado. A contagem atual está em [testes.xml](../reports/testes.xml) e na [auditoria dos critérios](auditoria_criterios.md). O teste ignorado depende do Airflow real; o sucesso da DAG é verificado separadamente no container. A suíte local não comprova execução remota do GitHub.

Os relatórios em `reports/airflow/` são da DAG local `20260914T221243-003d412d`; os relatórios remotos ficam em `reports/ci/<execucao>/`. As contagens da matriz e do histórico identificam cada execução separadamente.

A correção posterior do exportador também passou no [CI 34908437830](../reports/ci/34908437830/execucao.json), com 78 testes aprovados e execução completa da DAG/stack. Dois runners confirmaram a paridade e a [integração local atualizada](../reports/docker/pos_correcao/integracao_verificada.json) publicou uma nova versão, mantendo os quatro serviços saudáveis. As revisões Claude adicionais foram concluídas na rodada de auditoria descrita a seguir.

## Correções da auditoria dos critérios

O terceiro parecer válido B1 identificou que a promoção direta aceitava um candidato antes da validação completa. O [ensaio de regressão](../reports/auditoria_criterios/correcao_b1.json) reproduziu a falha e verificou a correção: promoção e reuso exigem aprovação explícita, versão, hashes dos modelos e latência finita. O exportador ganhou guardas de tokenização e cobertura de bigramas sem o primeiro, segundo ou ambos os unigramas. A validação oficial também exige concordância de classes. A [reconversão reproduzível](diagnostico_paridade.md) preservou os artefatos e corrigiu as diferenças do candidato remoto sem novo treinamento.

O quarto parecer B1 não encontrou defeito crítico ou alto. A remoção manual da versão atual continua bloqueando a publicação, pois pular a comparação perderia o gate de regressão; a mensagem foi tornada descritiva. O contrato da versão retornada pelo benchmark é conferido antes de aprovar relatórios. Uma verificação adicional do orquestrador reproduziu a revalidação reprovada que deixava a aprovação anterior disponível para promoção direta; essa aprovação é invalidada antes da nova tentativa. Os testes e o novo CI verificam as correções posteriores ao snapshot.

Algumas sugestões B1 foram mantidas como limites explícitos. Os diretórios de versões são armazenamento local confiável, não uma fronteira contra edição manual de relatórios: SHA e versão detectam trocas acidentais, mas não autenticam evidências reescritas deliberadamente. A latência mantém vínculo pelo nome da versão, enquanto a avaliação carrega os hashes dos modelos. Adicionar hashes aos JSONs não impediria falsificação por quem pode editar todo o diretório. O gate conserva fator p50 mínimo de 1 e registra p95; os ganhos reais excedem esse piso. Parâmetros futuros do vetorizador passam pelo gate de paridade completo. O teste de bigramas isola a representação problemática; o treino real do CI exercita `max_features`. O vínculo histórico baseline/ONNX está no [manifesto original](../reports/diagnostico_paridade/34907294809-runner-1.json). As evidências HTTP e Grafana pertencem aos blocos de integração, não estavam todas no snapshot B1 e permanecem disponíveis na matriz.

Este documento não declara aprovação automática dos blocos. A [matriz](matriz_rastreabilidade.md) separa implementação, execução e trabalho restante. Cada parecer permanece vinculado ao seu snapshot; as correções e verificações posteriores são explicitamente identificadas.

As correções anteriores da auditoria passaram no [CI 34921095963](../reports/ci/34921095963/execucao.json), commit `6426446`, com **104 testes aprovados**, builds, quatro tarefas Airflow e stack. O [runtime local daquele ciclo](../reports/auditoria_criterios/runtime_final.json) teve as fontes de treinamento/pipeline conferidas por SHA-256 e reutilizou o modelo preservado. A separação posterior das imagens possui registros próprios em `reports/docker/imagem_enxuta/`; o resultado remoto anterior não valida suas alterações de código, Dockerfile ou workflow.
