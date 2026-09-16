# Verificação da automação AWS

**Estado:** CI remoto concluído com sucesso na revisão `eacd3b9`; implantação bloqueada pela autenticação OIDC. A tentativa não publicou imagens no ECR nem enviou comandos ao SSM, e não implantou a fase 3 na EC2.

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

Esse resultado comprova o CI daquela revisão e o bloqueio de autenticação; não comprova implantação ou inferência da fase 3 no endereço público. Os ajustes posteriores à terceira revisão têm as verificações locais descritas abaixo e precisam de uma nova execução remota para evidenciar sua publicação.

## Treinamento com recursos limitados

O [ensaio local](../reports/aws/treino_limitado.json) executou o pipeline completo em um container sem volumes da stack, com 1 GiB e uma CPU. Terminou em 31,19 segundos, com código zero, avaliação aprovada e sem encerramento por falta de memória. O resultado pertence ao Docker Desktop/WSL2 local; não estabelece o tempo ou a capacidade da EC2.

## Testes e permissões

A [suíte local completa](../reports/aws/testes_locais.xml) terminou com 159 testes aprovados e dois ignorados no Windows. Ruff verificou 29 arquivos e o actionlint passou. Os casos de implantação exercitam memória insuficiente, ordem entre preparo e corte, recuperação de políticas de reinício e limpeza após timeout, SIGALRM e SIGTERM. A verificação Compose usa o parser real.

O conjunto de [testes de implantação](../tests/test_aws_deployment.py) terminou com 44 aprovados e um ignorado por exigir POSIX. Inclui a marcação de Airflow herdado ou explícito, a recusa de estado incoerente e versões Compose com sufixo, antigas ou inválidas. Também verifica a limpeza por rótulo, o orçamento decrescente de recuperação e a gravação do recibo antes das operações de retorno.

O [ensaio Linux de permissões](../reports/aws/permissoes_linux.json) confirmou que os usuários 472 e 65534 conseguem ler configurações extraídas sob `umask 077`. A cópia sintética sem os ajustes de permissões reproduziu a falha. Containers temporários foram removidos, sem montagem dos volumes da stack.

## Limites operacionais

A revisão adicional de OIDC/IAM está no [parecer B4](../reports/reviews/B4.md). A documentação esclarece que a edição de confiança substitui o documento inteiro, distingue o bucket dispensável da fase 3 de recursos legados e vincula os metadados públicos do repositório ao [registro da primeira tentativa](../reports/aws/autenticacao_inicial.json). O workflow registra uma lista explícita de campos públicos, incluindo referências de branch e workflow, e mascara o token. A comparação do `sub` real com a confiança AWS continua pendente; o exemplo usa o formato padrão documentado para a data de criação do repositório. O script remoto autentica no ECR e obtém digests por `docker image inspect`, sem exigir `ecr:DescribeImages` na EC2. Regras de aprovação do environment podem suspender o deploy automático até aprovação.

O retorno automático depende de o host, o Docker e os volumes continuarem disponíveis. Encerramento forçado, falta de disco ou falha do host podem impedir a recuperação. O procedimento manual e os arquivos de estado estão descritos em [aws.md](aws.md).

A conclusão remota exige autenticação OIDC válida, ECR existente, EC2 Online no SSM e validação pública de `/ready` e `/predict` com a mesma versão registrada na implantação.
