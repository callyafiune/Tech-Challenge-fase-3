# Plano de implementação — Tech Challenge Fase 3

> **Para os agentes executores:** implementar um bloco por vez e submeter cada bloco à revisão adversarial do Claude Code, modelo `fable`, conforme solicitado pelo usuário. O agente orquestrador acompanha dependências, critérios de aceitação e evidências. A execução ponta a ponta já foi autorizada; decisões rotineiras de implementação não exigem nova aprovação.

**Objetivo:** entregar um classificador de condições médicas a partir de resumos do Medical Abstracts TC Corpus, servido por FastAPI, com treinamento reproduzível, otimização mensurada, integração contínua e observabilidade local.

**Arquitetura:** inferência síncrona por API REST com um modelo leve de TF-IDF e classificador linear. O treino ocorre fora do processo da API, comandado por linha de comando ou Airflow, e gera artefatos identificáveis. Docker Compose reúne API, Prometheus e Grafana; a estratégia de nuvem fica documentada e o pipeline valida o código e a imagem.

**Tecnologias:** Python, scikit-learn, FastAPI, ONNX Runtime, prometheus-client, Airflow, Docker Compose, Prometheus, Grafana, GitHub Actions, pytest e Ruff. A otimização escolhida é ONNX; se a validação de compatibilidade ou medição exigir uma alternativa, a decisão e a comparação serão registradas.

**Especificação:** `C:/estudos/MLET-Tech-Challenge-Fase-3.md`. A alteração de objetivo para classificação de condições médicas e a escolha do Medical Abstracts TC Corpus foram autorizadas expressamente pelo usuário. Referência de organização e operação: `C:/estudos/Tech-Challenge-fase-2/README.md`.

**Fonte única do andamento:** a [matriz de rastreabilidade](matriz_rastreabilidade.md) registra o estado atual, as execuções e as pendências. Este arquivo descreve o plano técnico e seus critérios; as listas abaixo são ações previstas, sem marcações paralelas de conclusão. O [registro das revisões](revisoes_adversariais.md) acompanha o tratamento dos achados.

## Restrições globais

- Documentação, comentários, mensagens explicativas e relatórios em português Brasil. Identificadores de ferramentas e nomes originais do corpus preservam a interoperabilidade.
- Utilizar dados reais do Medical Abstracts TC Corpus, com pelo menos 2.000 amostras, proveniência documentada e separação de treino e teste preservada.
- O modelo classifica cinco categorias do corpus. A saída não representa urgência, diagnóstico clínico validado nem risco de um paciente.
- Resumos e vocabulário do corpus estão em inglês; exemplos funcionais usam inglês e a documentação explica a limitação linguística.
- Não ajustar hiperparâmetros, técnica de otimização ou limiares usando resultados do conjunto de teste. A escolha utiliza treino e validação; o teste mede o resultado final.
- A matriz de rastreabilidade distingue implementação, verificação local e demonstração em serviços externos. Arquivo YAML não comprova execução no GitHub; JSON de painel não comprova coleta de métricas.
- Cada bloco tem um parecer adversarial solicitado ao Claude Code com `--model fable`, correções registradas e uma nova verificação dos pontos alterados. Uma indisponibilidade desse modelo deve aparecer como impedimento concreto, sem substituição silenciosa de revisor.
- Publicações em nuvem e gravações ou links externos só contam como evidência quando existirem. Não inventar URLs, execuções remotas, commits ou métricas.

## Organização e responsabilidade dos arquivos

| Área | Arquivos/estrutura prevista | Responsabilidade |
|---|---|---|
| Dados e treino | `src/medical_classifier/data.py`, `src/medical_classifier/pipeline.py` | Validação do corpus, treino, otimização e publicação |
| Inferência e API | `src/medical_classifier/serving.py`, `src/medical_classifier/api.py` | Carregamento de artefatos, predição e exposição HTTP |
| Comandos operacionais | `scripts/` | Download verificável, treino, comparação de latência, carga HTTP e verificação dos serviços |
| Testes | `tests/` | Contratos públicos, isolamento de teste, artefatos inválidos, instrumentação e pipeline |
| Ambiente Python | `pyproject.toml` e arquivo de dependências reproduzível | Instalação local e em container com versões compatíveis |
| Serviço | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `.env.example` | Imagem de inferência e composição local |
| Observabilidade | `monitoring/` | Configuração Prometheus e provisionamento de fonte de dados/dashboard Grafana |
| Orquestração | `dags/` | DAG com ingestão, treino e salvamento/publicação de artefatos |
| Integração | `.github/workflows/` | Lint, testes, build e validações de configuração |
| Artefatos do modelo | `models/releases/<identificador>/baseline.joblib`, `model.onnx`, `metadata.json`; `models/current.json` | Bundle imutável por execução e ponteiro de publicação atômico |
| Evidências | `reports/` | Resultados gerados por comandos reais e identificação do ambiente |
| Documentação | `README.md`, `docs/` | Operação, modelo, decisões, roteiro STAR, rastreabilidade e revisões |

Os contratos abaixo foram alinhados entre os agentes responsáveis pelos blocos. Qualquer alteração precisa chegar simultaneamente a produtor, consumidor, testes e documentação.

## Contratos de integração

### Dados e modelo

1. A ingestão consome os arquivos oficiais de treino, teste e rótulos. Valida as colunas, a presença das cinco classes, textos não vazios e identificadores válidos; registra URL de origem, hash SHA-256 e contagens.
2. O vetor TF-IDF é ajustado exclusivamente com dados de treino. A separação de validação é estratificada e usa semente registrada. Deve existir uma auditoria de duplicatas entre partições; a política aplicada fica explícita no relatório.
3. O treino produz um modelo original, um modelo otimizado e metadados. Os metadados relacionam a versão dos artefatos às classes, semente, configuração, hashes de dados, versões das bibliotecas e métricas.
4. Os rótulos numéricos e nomes devem vir do arquivo oficial de classes. A tradução para português mantém a correspondência pelo identificador, sem depender da posição de um dicionário.
5. O serving carrega apenas artefatos locais confiáveis. Um artefato ausente, corrompido ou incompatível não pode ser anunciado como pronto. O treino grava em um diretório exclusivo da execução antes de publicar o conjunto completo; a API nunca deve misturar modelo de uma execução com metadados de outra.
6. A escolha do modelo otimizado exige comparar qualidade e latência com o original sob o mesmo conjunto de textos, aquecimento e número de repetições. Quantificar também tamanho do artefato e quantidade de atributos/parâmetros quando aplicável.

O pacote `medical_classifier.data` expõe `CLASSES` com identificadores de 1 a 5. O contrato de inferência é `Predictor(model_dir: Path, backend="onnx")`, no módulo `medical_classifier.serving`, com `predict(texts)` retornando a matriz de probabilidades de dimensões N × 5 e atributos `version` e `backend`. A ordem das colunas deve corresponder aos identificadores de 1 a 5 e ser verificada em teste.

O pipeline completo é executado pelo comando:

```powershell
python -m medical_classifier.pipeline executar --dados data/raw --modelos models
```

O CLI expõe `baixar` e `executar`; as funções `ingest`, `train` e `validate`, complementadas por `promote_release`, sustentam as quatro tarefas Airflow `ingestao`, `treinamento`, `validacao` e `publicacao`. A publicação gera `models/releases/<identificador>/` e troca atomicamente `models/current.json`. O Compose usa `--reutilizar` para verificar uma versão já publicada e seus relatórios, sem novo treino no reinício.

### API e instrumentação

Contrato acordado para a API:

```json
POST /predict
{"texto": "Cardiovascular risk factors were evaluated in the study population."}
```

```json
{
  "classe_id": 4,
  "classe": "Doenças cardiovasculares",
  "probabilidades": {
    "1": 0.1,
    "2": 0.1,
    "3": 0.1,
    "4": 0.6,
    "5": 0.1
  },
  "versao_modelo": "identificador-do-artefato",
  "backend": "onnx"
}
```

A resposta acima ilustra o esquema; não é uma predição executada. O tipo e as chaves de `probabilidades` devem acompanhar o esquema OpenAPI definitivo; as cinco probabilidades precisam respeitar a ordem oficial das classes e sua interpretação deve estar documentada.

- `GET /health`: verifica que o processo HTTP está vivo, independentemente da disponibilidade do modelo.
- `GET /ready`: verifica que há modelo válido carregado; responder 503 enquanto o serviço não puder prever.
- `POST /predict`: somente `texto`, com 20 a 20.000 caracteres após retirar espaços externos; o corpo JSON completo tem limite adicional de 128 KiB. Violações do contrato retornam 422; excesso de corpo retorna 413 antes da decodificação.
- `GET /metrics`: formato de exposição Prometheus, com contagem de requisições, duração e erros.
- Métricas usam rótulos de cardinalidade limitada: método, rota normalizada e código/status. Não incorporar texto recebido, identificador arbitrário de requisição ou caminho desconhecido como rótulo.
- Cada predição informa a classe e a versão do modelo. Logs e métricas não registram o texto clínico integral.

### Pipeline e infraestrutura

- CLI e Airflow chamam a mesma implementação de ingestão/treino/publicação. A DAG não deve conter uma segunda implementação do modelo.
- O caminho dos dados e dos artefatos é configurável e coincide entre CLI, volumes da DAG e volume carregado pela API.
- Airflow não transporta modelos ou corpus por XCom: transmite caminhos ou identificadores de execução. Evitar duas execuções publicando simultaneamente no mesmo destino.
- Prometheus consulta a API pelo nome do serviço na rede Compose; Grafana usa o nome do serviço Prometheus, não `localhost` dentro do container.
- O provisionamento do Grafana fixa o identificador da fonte de dados e o dashboard referencia esse mesmo identificador.
- CI executa verificações sem depender de credenciais privadas ou da disponibilidade contínua de serviços locais. A integração com dados reais e os testes rápidos devem estar claramente identificados.

## Bloco B1 — Dados, modelo e otimização

**Dependências:** nenhuma implementação anterior; requer acesso ao corpus e ambiente Python.

**Entrega verificável:** corpus validado, treino reprodutível, artefato original e otimizado, avaliação e comparação de latência geradas por execução real.

- Implementar a ingestão com origem explícita e validação de estrutura, conteúdo, rótulos e hashes.
- Cobrir comportamento de dados vazios, rótulos desconhecidos e texto de teste exclusivo. O teste de vazamento verifica que um termo presente apenas no teste não aparece no vocabulário ajustado.
- Ajustar TF-IDF e classificador linear no treino; separar validação com semente fixa e registrar parâmetros.
- Aplicar ONNX com paridade de pré-processamento ou poda real de atributos com novo vocabulário reduzido. Apenas zerar coeficientes de uma matriz densa não demonstra trabalho computacional eliminado.
- Comparar original e otimizado na validação, fixar a escolha e avaliar uma vez no teste. Gerar acurácia, F1 macro, métricas por classe e matriz de confusão.
- Medir latência completa de inferência textual, incluindo vetorização, com aquecimento e repetições suficientes. Registrar média, mediana, p95, ambiente, quantidade de textos e tamanho dos artefatos.
- Submeter B1 ao Claude Code `fable`; revisar especialmente vazamento de dados, rótulos, serialização, reprodutibilidade e honestidade da comparação.
- Corrigir achados confirmados e executar novamente as verificações afetadas.

**Aceitação:** pelo menos 2.000 amostras reais; cinco classes preservadas; separação documentada; modelos recarregáveis; relatório de qualidade e latência auditável. Se a técnica não melhorar latência, registrar o resultado e experimentar uma alternativa usando validação, sem afirmar melhoria inexistente.

## Bloco B2 — API de inferência e métricas

**Dependências:** contrato do artefato B1; pode ser implementado antes do treino completo usando um artefato pequeno exclusivo de testes.

**Entrega verificável:** API com carregamento no ciclo de vida, validação de entrada, resposta identificável e métricas.

- Escrever testes de integração da aplicação para predição válida, campo ausente, texto vazio, espaços, entrada excessiva e indisponibilidade do modelo.
- Implementar o carregamento único do artefato e a predição pelo modelo otimizado.
- Cobrir a correspondência entre identificador, nome da classe e versão retornada; impedir um resultado fora das cinco classes.
- Instrumentar contagem, duração e erros com registro isolável nos testes; verificar que requisições inválidas também são contabilizadas.
- Verificar rótulos normalizados: diferentes URLs desconhecidas não devem criar séries ilimitadas.
- Executar o teste da API com o artefato real de B1 e salvar uma requisição/resposta sem dados pessoais.
- Submeter B2 ao Claude Code `fable`; revisar especialmente falhas de inicialização, concorrência, exposição de texto e cardinalidade das métricas.
- Corrigir achados confirmados e executar novamente as verificações afetadas.

**Aceitação:** `/predict`, `/health`, `/ready` e `/metrics` funcionam conforme documentado; o serviço não retorna prontidão falsa; requisições inválidas não alcançam o modelo; a versão retornada identifica o artefato realmente carregado.

## Bloco B3 — Docker, Compose e observabilidade

**Dependências:** API B2 e artefato B1.

**Entrega verificável:** imagem funcional e stack API + Prometheus + Grafana com dashboard provisionado de pelo menos três painéis.

- Construir uma imagem que rode sem usuário root e com as dependências necessárias para inferência.
- Configurar volumes, variáveis, dependências entre serviços e verificação de saúde. Garantir que o primeiro uso obtenha ou gere o modelo de forma documentada.
- Provisionar Prometheus e Grafana com fonte de dados e dashboard: total/taxa de requisições, latência p95 e taxa de erros.
- Validar a expansão do Compose com `docker compose config --quiet` e construir a imagem.
- Subir os serviços, verificar saúde, enviar chamadas válidas e inválidas e consultar séries reais no Prometheus.
- Consultar o dashboard provisionado pela API Grafana ou pela interface; registrar identificador, painéis e evidência da fonte de dados funcionando.
- Medir baseline de latência HTTP local em container; separar essa medição do benchmark do modelo em processo.
- Submeter B3 ao Claude Code `fable`; revisar especialmente cold start, caminhos de volume, segredos, permissões, expressões PromQL e provisionamento.
- Corrigir achados confirmados e repetir a verificação da stack afetada.

**Aceitação:** Compose válido e serviços efetivamente saudáveis; coleta Prometheus ativa; dashboard com três ou mais painéis utilizando métricas observadas; JSON do dashboard versionado; latência HTTP registrada com metodologia.

## Bloco B4 — Airflow e integração contínua

**Dependências:** funções e comandos estáveis de B1, imagem e configuração de B3 para validação integrada.

**Entrega verificável:** DAG funcional e workflow acionado por push/PR com lint, testes e build.

- Criar DAG com tarefas explícitas de ingestão, treino/otimização e salvamento/publicação. Usar diretórios por execução, configuração dos caminhos e limite de concorrência compatível com a publicação.
- Validar importação da DAG dentro da mesma imagem/versão de Airflow usada na operação; ausência de erro de importação não substitui uma execução completa.
- Executar a DAG com dados reais, registrar identificador da execução e confirmar os arquivos produzidos e os estados das tarefas.
- Criar workflow que execute Ruff, pytest e build da imagem; incluir validação de Compose e da DAG conforme o ambiente CI disponível.
- Garantir permissões mínimas do token do workflow, versões coerentes e nenhuma credencial embutida.
- Executar localmente os mesmos comandos de qualidade do workflow. Se houver execução remota disponível e autorizada, registrar URL e conclusão; se não houver, registrar somente a verificação local.
- Submeter B4 ao Claude Code `fable`; revisar dependências da DAG, publicação concorrente, caminho de importação, permissões e fidelidade do CI à instalação real.
- Corrigir achados confirmados e executar novamente as verificações afetadas.

**Aceitação:** DAG executa a cadeia e produz um artefato carregável; workflow tem ao menos duas automações e build; comandos locais passam; execução remota é registrada separadamente da configuração.

## Bloco B5 — Integração final, documentação e entrega

**Dependências:** B1 a B4 concluídos ou limitações externas documentadas com evidência.

**Entrega verificável:** README operacional, decisão de nuvem, documentação do modelo, relatório de resultados, roteiro STAR e matriz de rastreabilidade atualizada.

- Documentar API síncrona para classificação individual e treino assíncrono. Comparar batch e tempo real e justificar uma arquitetura de nuvem adequada ao modelo leve e à necessidade de baixa latência.
- Adaptar os padrões úteis da fase 2: comandos reproduzíveis, configuração explícita, prontidão, execução sem root, identidade do modelo, evidências e decisões arquiteturais.
- Explicar por que bibliotecas da fase 2 voltadas a recomendação neural, registry ou versionamento remoto só serão incluídas se houver necessidade concreta nesta fase.
- Escrever o dicionário de classes, origem/licença verificadas, separações dos dados, escopo em inglês e limitações da classificação.
- Publicar números exclusivamente dos relatórios produzidos; identificar sistema operacional, CPU/ambiente, número de repetições e diferença entre latência do modelo e HTTP.
- Preparar roteiro STAR com até cinco minutos, comandos de demonstração e tempos por seção. Uma gravação ou link ausente permanece pendente de entrega audiovisual.
- Consolidar evidências de cada gate e resultados das revisões `fable`; executar a verificação final de instalação, lint, testes e stack conforme os recursos disponíveis.
- Organizar commits semânticos apenas com alterações revisadas e sem arquivos de credencial, ambientes virtuais ou corpus bruto acidentalmente incluídos.
- Submeter B5 ao Claude Code `fable`; revisar cobertura do enunciado, instruções copiáveis, links reais e incompatibilidades entre alegações e resultados.
- Corrigir achados confirmados e atualizar a matriz de rastreabilidade.

**Aceitação:** um avaliador consegue instalar, treinar, servir, consultar métricas e executar a DAG seguindo a documentação; as evidências sustentam as alegações. Pendências de publicação remota, vídeo ou ferramenta indisponível são explicitadas.

## Protocolo da revisão adversarial

Para cada bloco, o orquestrador fornece ao Claude Code um pedido de leitura sem alterações, com arquivos e critérios de aceitação. O parecer deve classificar problemas por severidade, apontar o arquivo e explicar um cenário reproduzível; o objetivo é encontrar falhas funcionais, de integração e de evidência.

```text
Revise adversarialmente o bloco indicado, em português Brasil, sem editar arquivos.
Modelo solicitado: fable.
Verifique o enunciado, os contratos do bloco e as alterações efetivas.
Priorize falhas reproduzíveis, vazamento de dados, prontidão falsa,
incompatibilidade entre serviços e alegações sem execução comprovada.
Informe severidade, arquivo, cenário de falha e correção mínima sugerida.
Se não encontrar problemas, registre os limites da revisão realizada.
```

O registro precisa identificar: bloco, data/hora, comando/modelo solicitado, resposta ou erro recebido, achados confirmados, correções e verificações posteriores. Solicitação enviada sem parecer retornado não é revisão concluída. O revisor não deve receber credenciais nem o conteúdo de arquivos pessoais alheios ao projeto.

## Riscos concretos e encaminhamento

| Risco | Consequência | Verificação ou mitigação |
|---|---|---|
| Modelo `fable` não disponível na sessão Claude Code | Gate adversarial solicitado fica sem parecer | Verificar executável e chamada real cedo; guardar erro e não alegar revisão substituta |
| Tradução ou ordem incorreta das classes | API retorna condição médica errada mesmo com índice correto | Carregar rótulos oficiais e testar a correspondência completa |
| TF-IDF ajustado antes de separar os dados | Métricas de qualidade infladas | Testar termo exclusivo de teste e inspecionar vocabulário treinado |
| Textos duplicados entre treino e teste | Avaliação otimista | Gerar auditoria e documentar a política de remoção/relato |
| ONNX altera tokenização ou não suporta operadores | Falha de inferência ou divergência das classes | Testar paridade textual; usar poda real como alternativa verificável |
| Otimização reduz qualidade ou não acelera | Requisito de ganho não demonstrado | Medir com protocolo comum e escolher na validação, registrando limitações |
| Artefatos publicados parcialmente | API lê modelo e metadados incompatíveis | Diretório por execução e publicação atômica do conjunto |
| Grafana aponta para `localhost` | Painéis não recebem métricas | Usar DNS dos serviços Compose e verificar consultas reais |
| Teste HTTP mistura rede e tempo de modelo | Comparação de latência enganosa | Relatórios separados com metodologia explícita |
| DAG só foi importada | Retreino pode falhar na operação real | Executar tarefas e confirmar artefato recarregável |
| Dependência Python incompatível com Airflow | DAG quebra mesmo com testes locais passando | Instalar e verificar no ambiente Airflow efetivamente utilizado |
| Corpus inglês apresentado como triagem clínica em português | Demonstração comunica capacidade não avaliada | Explicar escopo, idioma e ausência de classificação de urgência |

## Registro inicial

Este plano foi elaborado pela leitura do enunciado, do README e da configuração Python da fase 2. Na elaboração inicial, nenhuma execução de treino, benchmark, container, DAG, workflow remoto ou revisão Claude foi presumida. O progresso verificável é registrado em [matriz_rastreabilidade.md](matriz_rastreabilidade.md).
