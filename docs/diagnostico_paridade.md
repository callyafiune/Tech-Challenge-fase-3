# Diagnóstico da divergência ONNX

O CI `34906533919` reprovou duas tentativas de treinamento: diferença máxima de probabilidade de **0,00942405621**, com classes iguais nas 1.322 amostras. O limite de 0,0001 impediu a publicação. O [registro da falha](../reports/ci/34906533919/execucao.json) preserva esses valores.

## Reprodução e localização

O [diagnóstico 34907294809](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/runs/34907294809) executou a mesma imagem em dois runners AMD EPYC 7763. Ambos reproduziram o mesmo erro. Os relatórios completos estão em [runner 1](../reports/diagnostico_paridade/34907294809-runner-1.json) e [runner 2](../reports/diagnostico_paridade/34907294809-runner-2.json).

Na linha 812 da validação, o atributo `gadopentetate dimeglumine` valeu 0,142863 no scikit-learn e zero no ONNX. A diferença persistiu com otimizações do grafo desabilitadas, com a amostra isolada e com a substituição do classificador por operações MatMul e Softmax. Alimentado com o TF-IDF correto, o classificador ONNX apresentou erro de aproximadamente 1,92 × 10⁻⁷. Alimentado com o vetor divergente, o classificador scikit-learn reproduziu a diferença de 0,009424. A falha está na representação dos n-gramas pelo conversor.

O corte de 20.000 atributos pode manter um bigrama e retirar um de seus componentes como atributo individual. No [conversor `skl2onnx` 1.19.1](https://github.com/onnx/sklearn-onnx/blob/v1.19.1/skl2onnx/operator_converters/text_vectoriser.py), `_intelligent_split` trata esse bigrama como um token único contendo espaço. O tokenizador de letras usado neste projeto produz palavras separadas, então esse token não é contado. Empates de frequência na seleção do vocabulário explicam por que o caso aparece em alguns ambientes.

## Correção verificada

A exportação fornece n-gramas como tuplas explícitas de palavras, usando uma cópia do pipeline ajustado. Essa representação é aceita pelo conversor fixado e evita sua inferência ambígua. Os índices, o IDF e os coeficientes do modelo original permanecem intactos. A tokenização fixa `[a-zA-Z]{2,}` permite separar os componentes pelo espaço usado nos nomes dos n-gramas.

A [regressão automatizada](../tests/test_model.py) contém um bigrama cujo componente não existe como unigram no vocabulário: falhou antes da correção e passou depois. Outro teste confere que a exportação preserva o estado completo e as predições do baseline. Os limites de qualidade, paridade e aceleração permanecem os mesmos.

O [candidato remoto foi reconvertido](../reports/diagnostico_paridade/correcao_paridade_verificada.json) sem novo ajuste. Na validação inteira, o erro caiu de 0,009424 para 1,93 × 10⁻⁷; no teste oficial, de 0,033730 para 3,13 × 10⁻⁷. As classes coincidiram em 100% das amostras. A avaliação do teste conferiu a equivalência da conversão e não selecionou hiperparâmetros. As duas expressões afetadas eram `gadopentetate dimeglumine` e `ehlers danlos`; seus componentes `dimeglumine` e `danlos` ficaram fora do vocabulário individual.

## Confirmação remota da correção

O [CI 34908437830](../reports/ci/34908437830/execucao.json) terminou com sucesso no commit `3a7ad7f`: 78 testes aprovados, DAG completa, publicação do modelo, stack verificada e imagem preservada. A versão `20260914T232314-d0a18808` obteve aceleração p50 de 3,11× no runner; os critérios originais foram mantidos.

O [diagnóstico 34908437779](../reports/diagnostico_paridade/34908437779/execucao.json) também terminou em dois runners independentes. No [runner 1](../reports/diagnostico_paridade/34908437779-runner-1.json), o controle com a biblioteca voltou a apresentar erro de 0,009424, enquanto a exportação corrigida apresentou 1,93 × 10⁻⁷. No [runner 2](../reports/diagnostico_paridade/34908437779-runner-2.json), ambos apresentaram 1,92 × 10⁻⁷. Os dois candidatos corrigidos tiveram concordância de classes de 100% e nenhuma amostra acima do limite de `1e-4`. O controle do segundo runner confirma que a falha depende do vocabulário selecionado no ambiente; não é necessário que todo treino a reproduza.

## Reproduzir o diagnóstico

```powershell
.\.venv\Scripts\python.exe scripts/diagnosticar_paridade.py --dados data/raw --saida reports/diagnostico_paridade
```

Use um diretório de saída novo a cada execução. O script preserva o candidato e seus grafos intermediários, produz `diagnostico.json` e não publica `current.json`. Uma execução bem-sucedida do diagnóstico significa que a investigação terminou; o campo `erro_gate_treinamento` informa se o candidato passou pelo critério. `pipeline_do_projeto` usa a exportação corrigida; `pipeline_conversor_padrao`, TF-IDF isolado e alternativas MatMul conservam a heurística da biblioteca como controle. No GitHub, os candidatos são artefatos temporários retidos por sete dias; os relatórios desta investigação foram preservados no repositório.
