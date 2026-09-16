# Verificação da automação AWS

**Estado:** a revisão `901c8f8` passou no CI, autenticou por OIDC e publicou as imagens no ECR. A execução remota falhou no preparo do Compose, antes da troca da API. A causa foi reproduzida e corrigida; a implantação dessa correção ainda exige validação remota.

## Revisão adversarial

A revisão usa Claude Code com o modelo solicitado `fable`, sem ferramentas habilitadas. Os manifestos em `reports/reviews/` registram o modelo reportado, os arquivos e seus hashes. O parecer é confrontado com o código e com verificações executadas separadamente.

| Achado | Tratamento |
|---|---|
| Arquivos extraídos sob `umask 077` ilegíveis pelos painéis | A extração define diretórios 0755 e arquivos 0644; ambiente e senha continuam com acesso 0600 |
| Encerramento por timeout sem recuperação | Prazo interno de 1.800 s, externo de 2.400 s, tratamento de sinais e limpeza dos containers temporários; a recuperação cancela o alarme interno |
| Reinício automático dos containers antigos após reboot | As políticas são registradas e desativadas durante a troca, com restauração no retorno |
| Identificação fixa do projeto antigo | Restrição mantida: o workflow anterior usa `/opt/tech-challenge-fase-2` como diretório Compose. Outro rótulo na porta 8000 causa falha antes da parada; não autoriza encerrar serviços desconhecidos |
| Treinamento sem limite de recursos | Limites de 1 GiB e uma CPU, sem swap adicional; inspeção de memória antes do preparo |
| Volume criado fora do Compose | O serviço pipeline é criado pelo Compose antes da leitura do ponteiro de modelo |
| Falha do Airflow opcional desfaz a troca | Comportamento mantido: se solicitado ou já instalado, ele pertence à implantação e precisa estar pronto. O padrão da primeira implantação não inclui Airflow |
| Python do runner implícito | O workflow prepara Python 3.11 explicitamente |

A segunda rodada identificou casos adicionais: política de reinício vazia agora equivale a `no`; temporários remanescentes são reconhecidos por rótulo exclusivo e removidos sob a trava de implantação; o Airflow tem até 300 segundos para iniciar. A recuperação tem orçamento único de 540 segundos, consumido pelos subprocessos e chamadas HTTP, com recibo gravado antes das tentativas. O job dispõe de 75 minutos para publicação, execução remota e validação pública. As instruções de retorno exigem acesso como root e recuperam as políticas antigas.

A terceira rodada está registrada no [parecer B4 preservado](../reports/reviews/aws-3/B4.md). Seus achados receberam os seguintes tratamentos, verificados após a revisão:

| Achado | Tratamento final |
|---|---|
| Airflow reconstruído fora do CI | Quando solicitado, o CI inclui sua imagem no artefato; a implantação confere o SHA-256 do arquivo e o ID da imagem antes de publicá-la |
| Airflow herdado sem indicação no recibo | `airflow_herdado` distingue o digest preservado da imagem solicitada explicitamente; a DAG embutida acompanha a revisão dessa imagem herdada |
| Estado anterior da fase 3 junto a legados ativos | A atualização é recusada antes de alterar políticas de reinício ou parar containers; a primeira implantação mantém seu fluxo de substituição |
| Destino validado após a publicação | Conta, região e repositório são validados por `--validar` antes dos comandos de publicação no ECR |
| Versão Compose com sufixo de distribuição | A leitura aceita, por exemplo, `v2.24.4+ds1`, mantém o mínimo 2.24.4 e informa versões inválidas ou antigas |

O desarme dos sinais permanece como primeira instrução do tratamento de exceções. Encerramento por SIGKILL e perda do host continuam entre os limites operacionais; nenhum teste local elimina esses limites.

O gatilho automático de `main` chama o CI reutilizável antes do deploy. O CI direto exclui essa branch para evitar duplicação, mantendo validação de outras branches e pull requests. A execução manual continua disponível.

O contrato do pipeline foi conferido em `medical_classifier.pipeline`: a saída final é JSON e inclui `qualidade` e `latencia` vinculadas à versão. A imagem define `MODEL_DIR=/app/models`, também usado pelo candidato. O tarball exige acesso público ao repositório e saída de rede da EC2.

## Execução remota registrada

Na [execução 35038813631](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/runs/35038813631), referente à revisão `eacd3b9` de `main`, o [job de CI 104613859320](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/runs/35038813631/job/104613859320) terminou com sucesso. O [job de implantação 104614737817](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/runs/35038813631/job/104614737817) falhou ao executar `sts:AssumeRoleWithWebIdentity`, na autenticação OIDC, antes das etapas de ECR e SSM.

Esse resultado é histórico. Na [execução 35040175430](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/runs/35040175430), revisão `901c8f8`, OIDC, ECR e envio SSM funcionaram. O comando `f1fcd3d7-78bc-408d-bf52-642b67395a69` aguardou 1.717,547 segundos até o início registrado e executou por 33,872 segundos. O recibo registra `corte_iniciado: false`: essa tentativa não substituiu a API anterior.

O [diagnóstico remoto](../reports/aws/falha_preparo_pipeline.json) confirmou configuração válida, 22,5 GiB livres e download das imagens concluído. A reprodução isolada retornou `unknown flag: --no-deps` em `docker compose create --no-deps pipeline`. O comando passou a ser `docker compose create pipeline`; esse serviço não possui dependências. O teste de regressão captura o comando completo gerado pela implantação e usa a CLI real com `--help`, sem depender de daemon: falhou antes da correção e passou depois. As opções válidas de `run` e `up` foram preservadas.

O diagnóstico usou SSM, sem abrir SSH ou alterar grupos de segurança. Os pareceres do [diagnóstico](../reports/reviews/diagnostico-ssm/B4.md), da [reprodução controlada](../reports/reviews/diagnostico-preparo/B4.md) e da [correção](../reports/reviews/B4.md) preservam os respectivos escopos.

### Tratamento da revisão da correção

O [diff enviado ao revisor](../reports/reviews/correcao_preparo.diff) preserva o snapshot do comando e de sua regressão. As correções posteriores do cliente SSM são verificadas pelos testes, sem atribuir aprovação automática ao parecer.

| Achado | Decisão e evidência |
|---|---|
| Observação menor que a soma dos limites SSM | O prazo é de 3.300 s (600 + 2.400 + 300 s de margem); uma expiração informa resultado indeterminado e exige consulta antes de repetir |
| Falha transitória de consulta interrompe imediatamente o acompanhamento | Códigos transitórios conhecidos recebem novas consultas com espera limitada; o comando remoto não é reenviado |
| Código seguro da falha de consulta perdido no artefato | O artefato preserva `ErroConsulta`, além da última resposta disponível |
| Consulta expirada não aparece após o primeiro estado | O progresso inclui o contador de consultas sem resposta |
| Regressão cobre somente `create` | Escopo mantido no defeito reproduzido. `run` e `up` não foram alterados; sua execução integra os ensaios da stack |
| Possível download antes da guarda de memória | Não confirmado: a primeira guarda ocorre antes da autenticação e de qualquer download; a imagem de treinamento já é obtida antes de `create`. Outra guarda confere a memória imediatamente antes do pipeline |
| Espera de 1.717 s parecer incompatível com envio de 600 s | A AWS define o prazo total de entrega como a soma do parâmetro de envio e do prazo do documento: 600 + 2.400 = 3.000 s. O registro não identifica a causa do atraso do agente |
| Evidências externas ausentes do snapshot | Os links das execuções reais estão no relatório de diagnóstico; a CLI e os testes foram executados separadamente. O parecer continua sendo análise estática |

O contrato de timeout está na [documentação do Systems Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/monitor-commands.html). Os artefatos de falha preservam a resposta SSM para diagnóstico; o console imprime apenas campos permitidos e o caminho de recibo validado.

## Treinamento com recursos limitados

O [ensaio local](../reports/aws/treino_limitado.json) executou o pipeline completo em um container sem volumes da stack, com 1 GiB e uma CPU. Terminou em 31,19 segundos, com código zero, avaliação aprovada e sem encerramento por falta de memória. O resultado pertence ao Docker Desktop/WSL2 local; não estabelece o tempo ou a capacidade da EC2.

## Testes e permissões

A [suíte local completa](../reports/aws/testes_locais.xml) terminou com 181 testes aprovados e dois ignorados no Windows: integração Airflow em container e sinais POSIX. Ruff verificou 29 arquivos no escopo do CI e o actionlint passou. Os casos de implantação exercitam memória insuficiente, ordem entre preparo e corte, recuperação de políticas de reinício e limpeza após timeout, SIGALRM e SIGTERM. A verificação Compose usa o parser real. Os 29 testes do cliente SSM cobrem progresso, consultas expiradas, erros transitórios, preservação de evidências e resultado indeterminado quando o acompanhamento termina sem resposta final.

O conjunto de [testes de implantação](../tests/test_aws_deployment.py) terminou com 45 aprovados e um ignorado por exigir POSIX. Inclui a regressão da CLI `create`, a marcação de Airflow herdado ou explícito, a recusa de estado incoerente e versões Compose com sufixo, antigas ou inválidas. Também verifica a limpeza por rótulo, o orçamento decrescente de recuperação e a gravação do recibo antes das operações de retorno.

O [ensaio Linux de permissões](../reports/aws/permissoes_linux.json) confirmou que os usuários 472 e 65534 conseguem ler configurações extraídas sob `umask 077`. A cópia sintética sem os ajustes de permissões reproduziu a falha. Containers temporários foram removidos, sem montagem dos volumes da stack.

## Limites operacionais

A revisão adicional de OIDC/IAM está no [parecer preservado](../reports/reviews/aws-oidc/B4.md). O workflow registra uma lista explícita de campos públicos e mascara o token. A autenticação da revisão `901c8f8` confirmou o `sub` com IDs imutáveis descrito em [aws.md](aws.md). O script remoto autentica no ECR e obtém digests por `docker image inspect`, sem exigir `ecr:DescribeImages` na EC2. Regras de aprovação do environment podem suspender o deploy automático até aprovação.

O retorno automático depende de o host, o Docker e os volumes continuarem disponíveis. Encerramento forçado, falta de disco ou falha do host podem impedir a recuperação. O procedimento manual e os arquivos de estado estão descritos em [aws.md](aws.md).

A conclusão remota exige autenticação OIDC válida, ECR existente, EC2 Online no SSM e validação pública de `/ready` e `/predict` com a mesma versão registrada na implantação.
