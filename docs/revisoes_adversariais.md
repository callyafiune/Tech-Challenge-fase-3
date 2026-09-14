# Revisões adversariais e tratamento dos achados

O usuário solicitou Claude Code, modelo `fable`, para cada bloco. O [comando de revisão](../scripts/review_block.py) envia um snapshot literal numerado pela entrada padrão, sem ferramentas de leitura ou escrita habilitadas. Preserva JSON completo, parecer e manifesto com hashes, horários, modelo solicitado e código de saída.

As revisões são estáticas: o revisor não executou testes nem serviços. **Código zero da CLI não significa aprovação.** Os achados foram confrontados com o código, corrigidos quando confirmados ou documentados como decisões e limitações.

## Rodadas realizadas

| Bloco | Primeira rodada | Parecer mais recente | Tratamento |
|---|---|---|---|
| B1 — Dados e otimização | [Parecer](../reports/reviews/rodada-1/B1.md) | [Último parecer válido](../reports/reviews/rodada-2/B1.md) | Auditoria, gates, configuração e vínculo de artefatos corrigidos |
| B2 — API e métricas | [Parecer](../reports/reviews/rodada-1/B2.md) | [Parecer](../reports/reviews/B2.md) | Aquecimento, corpo limitado e métricas de desconexão/rejeição corrigidos |
| B3 — Containers e monitoramento | [Parecer](../reports/reviews/rodada-1/B3.md) | [Parecer](../reports/reviews/B3.md) | Stack e prontidão verificadas; evidência atualizada para a versão observada |
| B4 — Airflow e CI/CD | [Parecer](../reports/reviews/rodada-1/B4.md) | [Parecer](../reports/reviews/B4.md) | Aprovação explícita, mesma imagem validada e volumes externos corrigidos |
| B5 — Documentação e vídeo | [Parecer](../reports/reviews/rodada-1/B5.md) | [Terceiro parecer](../reports/reviews/B5.md) | Correções de vínculo de versões, ambientes, intermediários, roteiro e rastreabilidade |

Os manifestos acompanham os pareceres com sufixo `-manifest.json`. Há **14 pareceres concluídos**: dois de B1, dois de B2, três de B3, quatro de B4 e três de B5. As rodadas anteriores ficam nos diretórios `rodada-1`, `rodada-2` e `rodada-3`. Nessas chamadas, a solicitação foi `fable` e a CLI reportou `claude-fable-5-1`. Também listou `claude-haiku-4-5-20251001` entre os modelos utilizados internamente; o registro original foi preservado. O script não substituiu o modelo solicitado nem atribui artificialmente cada trecho do parecer a um modelo.

As tentativas suplementares B1 de diagnóstico e de revisão da correção de bigramas receberam limite de sessão HTTP 429; elas não contam como parecer. A primeira está preservada em `rodada-3/B1.*`, e a tentativa com o código corrigido está em `reports/reviews/B1.*`. O último parecer válido B1 está em `rodada-2`. A terceira B5 terminou antes desse limite. As correções posteriores aos snapshots foram verificadas localmente e são descritas abaixo, sem alegar nova aprovação pelo Claude.

## B1 — Dados e modelos

| Achado | Tratamento e evidência |
|---|---|
| Validação filtrada e teste de população diferente | Auditoria agora registra 2.770 textos únicos, 231 linhas ambíguas e teto determinístico de acurácia de 95,9141% no teste. A documentação não atribui toda a queda à ambiguidade |
| Publicação com F1 inferior | Quando o hash de validação coincide, bloqueia queda de F1 macro além de `1e-6`; o ponteiro preserva a versão anterior |
| ONNX sem ganho | `validate` bloqueia fator p50 abaixo de 1; teste cobre reprovação de um motor mais lento |
| Configuração incompleta nos metadados | Parâmetros derivados dos estimadores; versões do conversor/runtime e iterações do solver registradas |
| Partições alteradas entre tarefas | Hashes dos CSVs preparados conferidos no treino e validação, inclusive contra a auditoria da versão |
| Relatórios de outra versão no reuso | `--reutilizar` exige aprovação, identificação da versão e hashes correspondentes; confere também a versão do relatório de latência |
| Relatórios ausentes no reuso | Retorno com erro explícito para avaliação incompleta. O helper interno de publicação não substitui a execução suportada do pipeline completo |
| Artefatos parciais após reprovação | Treino/exportação em diretório temporário antes de disponibilizar a versão |
| Lacunas de cobertura | Casos para conflitos, corrupção, publicação reprovada, partição alterada, regressão de F1 e reprovação de latência |

Três decisões foram mantidas. Corrupção local causa erro e preserva o arquivo; não há remoção e novo download automáticos. A paridade de `argmax` é exata, embora empates numéricos possam reprovar conversões próximas. O piso de latência é conservador e sujeito a ruído de CPU: aquecimento, 400 amostras pareadas e ordem alternada não constituem SLO nem intervalo de confiança. A tentativa adicional do Airflow não elimina essa limitação.

O diretório de modelos é confiável. Hashes detectam corrupção ou troca acidental; não impedem quem possa editar simultaneamente modelo, metadados e ponteiro. As classes são o contrato fixo dos identificadores 1 a 5 dessa revisão, sem descoberta dinâmica de novas categorias. A documentação distingue modelo candidato avaliado e versão efetivamente apontada por `current.json`.

A integração remota encontrou depois uma falha concreta não detectada pelos pareceres estáticos: um bigrama podia ser convertido como token único quando faltava um componente no vocabulário individual. A [reprodução por camada](diagnostico_paridade.md) localizou a causa, e a exportação passou a fornecer tuplas explícitas em cópia do pipeline. O teste de regressão falhou antes e passou depois; outro teste preserva integralmente o baseline. O candidato remoto reconvertido passou em validação e teste completos, sem novo ajuste nem relaxamento dos limites. A solicitação suplementar ao `fable` incluiu essa correção, testes, diagnóstico e workflow, mas retornou 429 conforme o manifesto atual.

## B2 — API e métricas

Os achados resultaram em checagens de forma, finitude, intervalo e soma das probabilidades, aquecimento antes da prontidão, identificação do modelo nas métricas, probes assíncronas e limite de corpo de 128 KiB antes da decodificação JSON, inclusive em transferência fragmentada.

Desconexões durante a leitura são observadas como **499**, sem inflar 5xx. Caminhos conhecidos são preservados antes do roteamento para que respostas 413 de `/predict` apareçam no painel correspondente; caminhos arbitrários continuam agrupados. A documentação distingue o limite de caracteres do texto do limite de bytes do corpo.

A política de inicialização foi mantida: falha de carregamento preserva `/health`, deixa `/ready` em 503 e impede predição. A alternativa de encerrar imediatamente o processo não foi adotada. Logs registram somente o tipo da exceção, sem texto médico. Dependências são fixadas no lock; atualizar Starlette exige repetir testes de normalização das rotas.

## B3 — Docker e Grafana

O parecer identificou que o smoke daquele snapshot era de uma versão anterior. A [nova execução](../reports/smoke_stack.json) usa `20260914T221243-003d412d`, publicada pelo Airflow, e registra o digest da imagem e `healthy`. Confirmou 23 chamadas: 21 válidas e duas rejeições. Os seis painéis totalizam oito consultas reais. A [evidência anterior de treino offline e permissões](../reports/docker/execucao_stack.json) preserva sua própria versão e imagem, sem ser apresentada como execução da versão mais recente.

O painel de prontidão combina `model_ready` com `up`. O [ensaio de parada e reinício](../reports/docker/readiness_indisponibilidade.json) registrou 1 → 0 → 1. Fonte Grafana e provisionamento foram consultados diretamente.

Observações operacionais seguem acompanhadas: uma janela curta de taxa pode ficar sem amostras se o Grafana demorar; a verificação precisa sustentar tráfego durante suas consultas. Alterar `.env` não modifica a senha já persistida no Grafana, e falhas 401/403 devem ser distinguidas de falha da fonte. O lock único inclui ferramentas de desenvolvimento na imagem, uma troca por reprodução simples nesta demonstração, sem alegação de imagem mínima.

O Compose de benchmark é complementar, com uso dos dois `-f` documentado. O [benchmark HTTP do host](../reports/latencia_http_local.json) e o [HTTP de servidores Docker](../reports/docker/latencia_http.json) têm metadados, endpoints e versões próprios. O benchmark do modelo em Docker continua identificado como inferência sem HTTP.

Na terceira rodada B3, a espera por painel em um instante já fixado foi removida: uma consulta sem valor finito agora falha imediatamente. A consistência de dependências é conferida por `pip check` no CI. O venv fica em uma camada estável e o pacote ganha uma camada pequena; o README ainda participa da construção do wheel. A base usa tag versionada e o lock fixa versões sem hashes de wheels: os digests registrados identificam cada execução, mas não garantem reprodução binária de builds futuros.

## B4 — Airflow e entrega

O gate da tarefa exige aprovação explicitamente igual a `True`, vinculada à versão da execução. Etapas anteriores invalidam a aprovação, e estado ausente gera erros descritivos. Testes exercitam a publicação real e falhas isoladas.

A entrega carrega **a mesma imagem validada pelo CI**, conferindo SHA-256 e ID, em vez de reconstruí-la. Os volumes compartilhados são externos ao Compose Airflow. A retenção manual preserva versão atual, anterior e relatórios; não se apagam esses volumes para limpar o orquestrador.

Na quarta rodada B4, a saída vazia do identificador do artefato passou a ser rejeitada antes do download. O caminho `imagem/` continua fazendo parte do contrato entre quem grava e quem verifica o checksum. O artefato de imagem expira em sete dias; depois disso é necessário executar o CI completo para produzir outra imagem validada. Publicações manuais não são serializadas: `latest` pode representar o envio que terminou por último, portanto a tag do commit identifica a imagem a utilizar. São limites operacionais registrados, sem alegação de publicação GHCR já verificada.

A imagem Airflow passou a reutilizar a base da aplicação, com ambientes Python separados e constraints fixadas por revisão/SHA-256. A DAG usa o interpretador via `python -m`; o link de `/opt/model-venv` para `/opt/venv` preserva os shebangs. A API carrega a versão publicada somente após reinício, documentado como passo operacional. As rodadas adicionais de B3/B4 revisaram as alterações de infraestrutura.

O [estado histórico da construção](../reports/airflow_build_state.json) registra uma tentativa interrompida por falta de espaço. A [construção posterior](../reports/docker/build_airflow_state.json) terminou com código zero em 124,2 segundos. A [execução real](../reports/airflow_execucao.json) concluiu as quatro tarefas, publicou uma nova versão e confirmou a saúde de metadatabase, scheduler e triggerer do standalone. O comando `dags test` levou 66,6 segundos, conforme o registro de comandos; a data lógica da DAG não mede esse intervalo. A instrumentação da falha remota de paridade permitiu reproduzir e corrigir a representação dos bigramas, mantendo os critérios originais. O Airflow 2.11 aplicou `retries=1` também no comando `dags test`; a documentação anterior que restringia esse comportamento ao agendador foi corrigida.

## Situação consolidada

A revisão B5 confirmou a consistência aritmética dos relatórios e apontou lacunas no vídeo/documentação. O gerador passou a rejeitar `/ready` ou `/predict` de versão diferente dos relatórios, sem ocultar o erro. A contingência da stack é neutra; o estado da DAG vem de `reports/airflow_execucao.json` e exige sucesso booleano, quatro tarefas concluídas e uma execução identificada. O roteiro descreve os cartões programáticos, com HTTP do host separado de Docker. O plano remete à matriz como fonte de andamento, e o README inclui autoria/licença do corpus.

A segunda rodada B5 identificou sobrescrita do manifesto pelo modo de imagens, mistura de versões na apresentação e coerção de sucesso textual. O modo `-SomenteImagens` agora grava somente em `.local/video`; stack e DAG usam booleanos estritos; tela, narração e manifesto distinguem a versão Docker operacional da versão do host nos gráficos. O gerador prefere o registro posterior de build concluído e rejeita um cartão CI vazio. A coleta Airflow passou a registrar o instante final da saúde, e o README traz os comandos do benchmark do host em portas independentes.

O vídeo final tem 219,626395 segundos, H.264/AAC, 1280×720 e 451 palavras, com API real do host em 8004. Os sete quadros foram extraídos do MP4 e inspecionados. A [verificação reproduzível](../reports/video/verificar_gerador.ps1) passou em 26 casos, incluindo evidências inválidas, leitura independente ffprobe e preservação dos hashes do MP4/manifesto após `-SomenteImagens`. Os JSONs de verificação e inspeção estão em `reports/video/`. O CI aparece no vídeo como configuração estática; seu estado remoto atual está no README.

A última suíte em [testes.xml](../reports/testes.xml) registra 78 casos aprovados e um ignorado, sem falhas ou erros. O teste ignorado depende do Airflow real; o sucesso da DAG foi verificado separadamente no container. A suíte local não comprova execução remota do GitHub.

A terceira B5 identificou dois defeitos médios, ambos corrigidos: o gerador agora exige `ambiente_servidores=host` no relatório HTTP e método sem HTTP no relatório em processo; `-SomenteImagens` usa um subdiretório isolado, preservando também os 23 intermediários da renderização. Os achados baixos foram tratados exigindo versão publicada na DAG, avisando divergência de versão mesmo quando só a DAG tiver evidência, cobrindo `/predict` e motor divergentes, registrando uma nova rejeição HTTP real e anotando os textos conferidos por quadro. Contagens da matriz e histórico foram alinhados. Os relatórios em `reports/airflow/` são da DAG local `20260914T221243-003d412d`; os relatórios remotos ficam em `reports/ci/<execucao>/`.

O verificador ampliado passou em **26 casos**, incluindo preservação de intermediários, e o MP4 foi renderizado novamente. A [rejeição de versão](../reports/video/rejeicao_versao.json) e a [inspeção dos quadros](../reports/video/inspecao_visual.json) registram as verificações posteriores ao terceiro parecer. O CI remoto 34905435615 concluiu com sucesso; esse resultado foi incorporado depois do snapshot da revisão.

A correção posterior do exportador também passou no [CI 34908437830](../reports/ci/34908437830/execucao.json), com 78 testes aprovados e execução completa da DAG/stack. Dois runners confirmaram a paridade e a [integração local atualizada](../reports/docker/pos_correcao/integracao_verificada.json) publicou uma nova versão, mantendo os quatro serviços saudáveis. Esses resultados complementam a verificação técnica; a tentativa suplementar Claude para essa correção continuou limitada por HTTP 429, conforme registrado acima.

Este documento não declara aprovação automática dos blocos. A [matriz](matriz_rastreabilidade.md) separa implementação, execução e trabalho restante. Cada parecer permanece vinculado ao seu snapshot; as correções e verificações posteriores são explicitamente identificadas.
