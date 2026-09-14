# Documentação do modelo

## Identificação e finalidade

O modelo usa TF-IDF e regressão logística para classificar resumos médicos em inglês nas cinco categorias do Medical Abstracts TC Corpus. A versão é o identificador do diretório `models/releases/` e aparece em `metadata.json`, nos relatórios e na resposta da API. O motor padrão de inferência é ONNX Runtime; scikit-learn representa o modelo original para comparação.

O uso previsto é educacional: demonstrar treinamento, exportação, API, integração contínua, retreino e observabilidade. O modelo não estima urgência, não realiza diagnóstico e não foi validado para orientar decisões clínicas. Resumos de artigos não equivalem a laudos de pacientes. Entradas em português, outras especialidades ou outros tipos de documento não tiveram desempenho avaliado neste projeto.

## Origem, licença e integridade dos dados

O [Medical Abstracts TC Corpus](https://github.com/sebischair/Medical-Abstracts-TC-Corpus) foi disponibilizado por Tim Schopf, Daniel Braun e Florian Matthes e acompanha o trabalho *Evaluating Unsupervised Text Classification: Zero-Shot and Similarity-Based Approaches*. O corpus possui 11.550 linhas de treino e 2.888 de teste, distribuídas em cinco categorias. O manifesto local identifica a licença como CC BY-SA 3.0 e o downloader preserva o arquivo `LICENSE` original. Consulte a [fonte do corpus](https://github.com/sebischair/Medical-Abstracts-TC-Corpus) e a [licença na revisão utilizada](https://github.com/sebischair/Medical-Abstracts-TC-Corpus/blob/70a2d9106c724729be8b3c4ddb00d1b14ec300c8/LICENSE).

A revisão fixada é `70a2d9106c724729be8b3c4ddb00d1b14ec300c8`. O [manifesto](../src/medical_classifier/corpus_manifest.json) contém SHA-256 dos quatro arquivos baixados. Os hashes dos CSVs brutos também são carregados na auditoria e nos metadados de cada versão:

| Arquivo bruto | SHA-256 esperado |
|---|---|
| `medical_tc_train.csv` | `ad53aebc682d6b87a5647f619a079bb446d286fdc93bf0159b812418f5758609` |
| `medical_tc_test.csv` | `1eecea73c9ecad292c55e10403bd139fab9580545d6878482997c5564d51ac05` |

Um arquivo existente com hash divergente é rejeitado. A proveniência não depende de uma versão mutável da branch principal do repositório do corpus.

## Classes e partições

| ID | Nome original | Nome na API | Ajuste | Validação | Teste oficial |
|---|---|---|---:|---:|---:|
| 1 | Neoplasms | Neoplasias | 1.402 | 350 | 633 |
| 2 | Digestive system diseases | Doenças do sistema digestivo | 446 | 112 | 299 |
| 3 | Nervous system diseases | Doenças do sistema nervoso | 659 | 165 | 385 |
| 4 | Cardiovascular diseases | Doenças cardiovasculares | 1.242 | 311 | 610 |
| 5 | General pathological conditions | Condições patológicas gerais | 1.536 | 384 | 961 |
| **Total** | | | **5.285** | **1.322** | **2.888** |

As contagens acima foram observadas em `data/prepared/auditoria.json`. O tratamento aplica minúsculas e unifica espaços antes de comparar textos. A política é:

1. Remover do treino as 1.097 linhas cujo texto normalizado aparece no teste oficial.
2. No treino remanescente, remover todas as 3.846 linhas associadas a textos que possuem mais de um rótulo. Não escolher arbitrariamente um rótulo desses textos.
3. Eliminar repetições restantes por texto; nesta auditoria, essa etapa não removeu linhas adicionais.
4. Dividir as 6.607 linhas restantes em ajuste e validação estratificados, com 20% para validação e semente 42.
5. Preservar todas as 2.888 linhas e rótulos do teste oficial. A normalização usada no processamento não altera os arquivos brutos.

Essas remoções reduzem vazamento e ambiguidade do treino, mas mudam sua distribuição e descartam parte do corpus original. A validação é extraída dessa população filtrada, enquanto o teste conserva sua composição original. Portanto, as métricas não devem ser comparadas diretamente com trabalhos que treinem nas 11.550 linhas sem a mesma política.

A auditoria atual identifica **2.770 textos únicos e 231 linhas associadas a textos com rótulos conflitantes no teste**. Um classificador determinístico que só recebe o texto tem teto de acurácia de **95,9141%** nesse teste: para cada texto, soma-se a frequência do rótulo mais comum e divide-se por 2.888. A ambiguidade impõe perda mínima de aproximadamente 4,09 pontos percentuais, mas **não explica toda a diferença entre validação e teste**; o relatório não estabelece uma decomposição causal desse intervalo.

## Pré-processamento e treinamento

| Componente | Configuração |
|---|---|
| Normalização compartilhada | Minúsculas e espaços consecutivos convertidos em um espaço |
| Tokenização | Sequências de pelo menos duas letras de `a` a `z`, sem distinguir caixa após normalização |
| Vocabulário | Até 20.000 atributos, unigramas e bigramas |
| TF-IDF | Frequência linear, `sublinear_tf=False`, valores `float32` |
| Classificador | Regressão logística, `C=4.0`, `max_iter=500`, `class_weight="balanced"` |
| Critério mínimo de qualidade | F1 macro de validação ≥ 0,55 |
| Exportação | ONNX com entrada textual N × 1, opset 17 e `zipmap=False` |
| Execução padrão | ONNX Runtime em CPU, uma thread para operações intra/interoperador |

A escolha de uma representação lexical e de um classificador linear reduz dependências e permite manter o pipeline completo de inferência no grafo exportado. O vetor TF-IDF é ajustado exclusivamente nos dados de ajuste. A ponderação por classe considera o desbalanceamento do treino; a F1 macro dá o mesmo peso às cinco classes na métrica de aceitação.

Os hiperparâmetros foram predeterminados antes da primeira avaliação do teste, sem busca em grade. A configuração efetiva do TF-IDF e da regressão logística e as versões de scikit-learn, ONNX, ONNX Runtime e `skl2onnx` ficam nos metadados. Os hashes dos CSVs preparados são conferidos entre tarefas, além dos hashes do corpus bruto.

## Conversão ONNX e regressão de compatibilidade

Na implementação com `skl2onnx` 1.19, o caminho de frequência sublinear observado aplica `log(1 + tf)`, que difere de `1 + log(tf)` usado pelo scikit-learn para frequências positivas. A diferença afeta textos com repetições de palavras e pode alterar as probabilidades. O modelo foi definido com frequência linear, `sublinear_tf=False`, para preservar a transformação entre os dois motores.

O teste `test_paridade_com_frequencias_de_palavras_distintas`, em [tests/test_model.py](../tests/test_model.py), cobre textos com frequências distintas. A publicação exige, na validação real, erro máximo absoluto de probabilidade de até `1e-4` e concordância de classe de 100%. O pipeline também registra a comparação dos motores no teste oficial. Essa verificação detecta divergência da conversão; não representa uma nova escolha de hiperparâmetros a partir do teste.

A exigência de `argmax` idêntico é uma decisão conservadora: probabilidades quase empatadas podem inverter a classe com pequenas diferenças numéricas e reprovar a versão. Esse risco é aceito para não alterar silenciosamente a categoria da API. Quando o hash da validação coincide com o da versão ativa, a publicação também impede queda de F1 macro acima da tolerância `1e-6`.

## Avaliação e resultados reproduzíveis

As métricas são produzidas pelo pipeline e vinculadas à versão do modelo. Esta documentação usa os arquivos de resultado como fonte, evitando números estimados ou resultados de testes sintéticos apresentados como avaliação do corpus real.

A versão local **`20260914T214327-e6c68fc4`** produziu **acurácia de 0,639197 e F1 macro de 0,638544 no teste oficial**, com as mesmas métricas para scikit-learn e ONNX. Na validação, a acurácia foi 0,798033 e a F1 macro 0,784904. A concordância entre os motores na validação foi 100%, com diferença máxima de probabilidade de `1,92 × 10⁻⁷`; no teste, a diferença máxima foi `2,98 × 10⁻⁷`. Fonte: [relatório de qualidade](../reports/qualidade.json).

| Classe | Precisão no teste | Revocação no teste | F1 no teste | Suporte |
|---|---:|---:|---:|---:|
| Neoplasias | 0,7022 | 0,7899 | 0,7435 | 633 |
| Doenças do sistema digestivo | 0,5667 | 0,6254 | 0,5946 | 299 |
| Doenças do sistema nervoso | 0,5964 | 0,6104 | 0,6033 | 385 |
| Doenças cardiovasculares | 0,6859 | 0,7803 | 0,7301 | 610 |
| Condições patológicas gerais | 0,5910 | 0,4662 | 0,5212 | 961 |

A classe de condições patológicas gerais teve a menor F1 e revocação desta execução. Também existe uma diferença relevante entre a F1 de validação e de teste. A política de limpeza foi aplicada somente ao treino, enquanto o teste oficial foi preservado; a diferença observada exige cautela sobre generalização e não deve ser ocultada por apresentar apenas a validação.

| Latência em processo | scikit-learn | ONNX | Aceleração |
|---|---:|---:|---:|
| p50 | 1,2419 ms | 0,3532 ms | 3,52× |
| p95 | 1,905995 ms | 0,5867 ms | 3,25× |
| p99 | 2,210677 ms | 0,661357 ms | 3,34× |

As 400 medições por motor, com 30 chamadas de aquecimento e uma thread nativa, foram executadas em Windows `10.0.26200`, processador `Intel64 Family 6 Model 140 Stepping 1`, Python 3.11.9, scikit-learn 1.7.2 e ONNX Runtime 1.23.2. O artefato original tem 1.531.732 bytes e o ONNX tem 1.007.018 bytes. Fonte: [relatório de latência em processo](../reports/latencia_modelo.json). Essa medição não comprova latência HTTP ou funcionamento em Docker.

O [benchmark HTTP local](../reports/latencia_http_local.json) da mesma versão mediu p50 de 7,7405 ms no original e 5,3488 ms no ONNX, com aceleração de 1,45×; o p95 foi 17,088365 e 10,58619 ms, ou 1,61×. Foram 200 chamadas por motor e 20 de aquecimento, com concorrência um, fora de Docker.

Separadamente, a versão Docker `20260914T214809-a767fe94` foi medida em Linux/WSL2: p50 de 1,226336 ms e 0,328270 ms, ou 3,74×, em [inferência em processo dentro do container](../reports/docker/latencia_modelo.json). Essa comparação não inclui HTTP e não deve ser combinada com a medição do host como se fosse a mesma execução.

Após publicação pelo Airflow, a versão `20260914T221243-003d412d` foi medida em [HTTP com servidores Docker](../reports/docker/latencia_http.json): p50 de 5,41015 e 4,0585 ms, ou 1,33×, e p95 de 8,251045 e 6,137035 ms, ou 1,34×. O cliente rodou no Windows; ambos os servidores usaram a mesma versão, com 200 chamadas por motor e 20 de aquecimento. Os endpoints e a identificação do ambiente estão no relatório.

| Evidência | Localização e campos |
|---|---|
| Qualidade de validação | `reports/qualidade.json`: `validacao`, `paridade_validacao` |
| Qualidade do teste oficial | `reports/qualidade.json`: `teste.sklearn` e `teste.onnx` |
| Métricas por classe | `por_classe`: precisão, revocação, F1 e suporte |
| Matriz de confusão | `matriz_confusao`, na ordem dos identificadores 1 a 5 |
| Paridade numérica no teste | `erro_maximo_probabilidade_teste` |
| Tamanho dos artefatos | `tamanho_bytes` para original e ONNX |
| Latência em processo | `reports/latencia_modelo.json`: p50/p95/p99, média, ambiente e fatores de aceleração |
| Latência HTTP local | `reports/latencia_http_local.json`: versões, motores, aquecimento e percentis, fora de Docker |
| Latência em processo no Docker | `reports/docker/latencia_modelo.json`, com versão e ambiente próprios |

A [matriz de rastreabilidade](matriz_rastreabilidade.md) indica quais execuções foram efetivamente concluídas. A análise de qualidade deve considerar F1 macro e desempenho por classe, pois acurácia isolada pode esconder dificuldades nas classes menores.

O benchmark em processo mede normalização, vetorização e classificação com lote um. Os mesmos textos são sorteados da validação com semente 42, a ordem dos motores é alternada e há aquecimento anterior às medições. A comparação HTTP inclui transporte, validação da API e serialização. Ela utiliza conexões persistentes e concorrência um; não mede saturação, picos de tráfego ou capacidade máxima.

O pipeline bloqueia fator de aceleração p50 abaixo de 1. Esse piso pode reprovar uma execução sob ruído de CPU e não constitui SLO, intervalo de confiança ou comparação histórica de versões. A tentativa adicional do Airflow é um recurso operacional; não substitui a análise da medição reprovada.

## Contrato e interpretação da resposta

A API recebe um único campo `texto`, estritamente textual, com 20 a 20.000 caracteres depois da retirada de espaços externos. O corpo JSON completo tem limite adicional de 128 KiB, incluindo escapes Unicode; excedê-lo produz HTTP 413. Ela retorna o identificador e o nome da maior classe, as cinco probabilidades, a versão e o motor.

As probabilidades são saídas normalizadas do classificador entre as cinco categorias conhecidas. Elas não foram calibradas como risco clínico e não indicam a probabilidade de um paciente ter uma doença. O sistema não possui uma classe de rejeição para documento fora do domínio; mesmo um texto inadequado que passe a validação de formato pode receber uma das cinco categorias.

Somente artefatos locais confiáveis devem ser carregados. Os hashes são comparados com o manifesto da versão antes do carregamento; isso detecta corrupção, mas não constitui assinatura de um produtor confiável. A versão precisa acompanhar o pacote de arquivos e a configuração de código usados na execução.

## Limitações

- O domínio é o de resumos médicos em inglês, sem avaliação em laudos reais, português ou idiomas adicionais.
- A classificação é de uma categoria por texto. Textos que abordam múltiplas condições podem não se ajustar bem a essa representação.
- A remoção de conflitos e sobreposição altera o conjunto de treinamento e limita comparações externas.
- Não houve calibração clínica, validação prospectiva, avaliação demográfica nem estudo de impacto em pacientes.
- O dashboard monitora operação HTTP e prontidão; não acompanha qualidade clínica ou deriva automaticamente.
- Resultados de latência dependem do processador, sistema operacional, carga concorrente, distribuição dos textos e modo de execução registrados no relatório.
