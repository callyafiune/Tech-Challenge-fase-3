# Verificação da automação AWS

**Estado:** preparação local verificada; execução na EC2 pendente. As verificações descritas aqui não comprovam que o endereço público serve a fase 3.

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

O gatilho automático de `main` chama o CI reutilizável antes do deploy. O CI direto exclui essa branch para evitar duplicação, mantendo validação de outras branches e pull requests. A execução manual continua disponível.

O contrato do pipeline foi conferido em `medical_classifier.pipeline`: a saída final é JSON e inclui `qualidade` e `latencia` vinculadas à versão. A imagem define `MODEL_DIR=/app/models`, também usado pelo candidato. O tarball exige acesso público ao repositório e saída de rede da EC2.

## Treinamento com recursos limitados

O [ensaio local](../reports/aws/treino_limitado.json) executou o pipeline completo em um container sem volumes da stack, com 1 GiB e uma CPU. Terminou em 31,19 segundos, com código zero, avaliação aprovada e sem encerramento por falta de memória. O resultado pertence ao Docker Desktop/WSL2 local; não estabelece o tempo ou a capacidade da EC2.

## Testes e permissões

A [suíte local completa](../reports/aws/testes_locais.xml) terminou com 153 testes aprovados e dois ignorados no Windows. Os casos de implantação exercitam memória insuficiente, ordem entre preparo e corte, recuperação de políticas de reinício e limpeza após timeout, SIGALRM e SIGTERM. A verificação Compose usa o parser real.

O [ensaio Linux de permissões](../reports/aws/permissoes_linux.json) confirmou que os usuários 472 e 65534 conseguem ler configurações extraídas sob `umask 077`. A cópia sintética sem os ajustes de permissões reproduziu a falha. Containers temporários foram removidos, sem montagem dos volumes da stack.

## Limites operacionais

O retorno automático depende de o host, o Docker e os volumes continuarem disponíveis. Encerramento forçado, falta de disco ou falha do host podem impedir a recuperação. O procedimento manual e os arquivos de estado estão descritos em [aws.md](aws.md).

A conclusão remota exige autenticação OIDC válida, ECR existente, EC2 Online no SSM e validação pública de `/ready` e `/predict` com a mesma versão registrada na implantação.
