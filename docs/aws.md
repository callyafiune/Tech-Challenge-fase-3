# Fase 3 na EC2 existente

**Estado: configuração preparada; implantação remota ainda não confirmada.** A existência dos arquivos e a validação local do Compose não demonstram que a EC2 já serve a fase 3. A confirmação exige a execução remota e as respostas da API com a versão do modelo publicada.

## GitHub Actions e recursos de destino

O fluxo principal é [`.github/workflows/implantar-aws.yml`](../.github/workflows/implantar-aws.yml), iniciado automaticamente por cada push na `main`. Ele chama o CI reutilizável para a mesma revisão e só após aprovação assume o papel AWS por OIDC e publica no ECR as imagens de inferência e treinamento produzidas e verificadas pelo CI, sem reconstruí-las. Airflow também usa a imagem verificada pelo CI e é publicado quando solicitado. A implantação segue para a EC2 por SSM. O runner recebe credenciais temporárias; esse caminho não exige perfil AWS local nem chaves de acesso salvas nos secrets do GitHub.

| Recurso | Identificação |
|---|---|
| Conta AWS | `076516546831` |
| Região | `eu-west-1` |
| Instância existente | `i-024a7c79b3ec2bfa1` |
| Endereço informado | `54.246.245.167` |
| Repositório ECR da fase 3 | `tech-challenge-fase-3` |
| Registro ECR | `076516546831.dkr.ecr.eu-west-1.amazonaws.com` |
| Papel de implantação | `arn:aws:iam::076516546831:role/tech-challenge-deploy-role` |
| Environment do GitHub | `production` |

A instância da fase 2 é reutilizada; as imagens novas ficam no repositório ECR `tech-challenge-fase-3`, que precisa existir antes do workflow. O fluxo não cria esse repositório nem outros recursos de infraestrutura. A inspeção remota identifica os containers da fase 2 antes de qualquer parada. O IP deve ser reconfirmado na EC2, pois não há confirmação de que seja um Elastic IP.

Configure as cinco **Actions Variables** abaixo no repositório. Todas são usadas pelo workflow; seus valores não são credenciais:

| Variável | Valor | Uso |
|---|---|---|
| `AWS_REGION` | `eu-west-1` | Região de autenticação, ECR, EC2 e SSM |
| `AWS_ROLE_ARN` | `arn:aws:iam::076516546831:role/tech-challenge-deploy-role` | Papel assumido via OIDC |
| `EC2_INSTANCE_ID` | `i-024a7c79b3ec2bfa1` | Instância que receberá o comando SSM |
| `ECR_REPOSITORY` | `tech-challenge-fase-3` | Repositório das imagens de inferência, treino e Airflow |
| `PUBLIC_API_URL` | `http://54.246.245.167:8000` | Origem usada na validação pública da implantação |

Essas variáveis não criam permissões IAM, confiança OIDC, repositório ECR ou acesso ao SSM. **S3 e DVC não são dependências deste fluxo da fase 3.** Não é necessária uma variável de bucket. As permissões para o bucket `dvc-tech-challenge-fase-3` são dispensáveis. Preserve permissões de outros buckets enquanto forem necessárias a serviços legados ou ao retorno à fase 2.

## Preparar IAM uma vez, sem substituir acessos existentes

Os arquivos abaixo são referências para um administrador aplicar manualmente. Eles não foram aplicados à conta por esta preparação e não são políticas para criação de recursos pelo workflow.

| Arquivo | Aplicação |
|---|---|
| [github-oidc-trust-policy.json](aws/github-oidc-trust-policy.json) | Declaração de confiança a incorporar no papel `tech-challenge-deploy-role` |
| [deploy-role-policy.json](aws/deploy-role-policy.json) | Política adicional do papel de implantação: ECR da fase 3, leitura de estado e Run Command na instância informada |
| [ec2-ecr-policy.json](aws/ec2-ecr-policy.json) | Política adicional no papel IAM associado à EC2, somente para baixar as imagens do ECR da fase 3 |

No IAM, confirme o provedor OIDC `token.actions.githubusercontent.com` com audiência `sts.amazonaws.com`. Em [Roles → tech-challenge-deploy-role](https://console.aws.amazon.com/iam/home#/roles/details/tech-challenge-deploy-role), preserve a política de confiança atual e incorpore a declaração `ConfiarGitHubFase3Production`. **Não substitua toda a confiança da role compartilhada pelo arquivo de exemplo**, pois outras declarações podem ser necessárias à fase 2 ou a outros fluxos. A AWS distingue a confiança, que autoriza assumir o papel, das permissões que o papel concede. [Documentação IAM sobre OIDC](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html).

A política de exemplo usa o identificador padrão esperado para este repositório: `repo:callyafiune@16156667/Tech-Challenge-fase-3@1370511453:environment:production`. O GitHub inclui IDs imutáveis no `sub` de repositórios criados após 15/07/2026; este repositório foi criado em 14/09/2026. Os IDs conferidos na API do GitHub estão no [registro de autenticação inicial](../reports/aws/autenticacao_inicial.json). Compare o `sub` efetivamente emitido com o exemplo antes de aplicá-lo, respeitando maiúsculas e minúsculas e eventuais personalizações. [Referência oficial de identificadores OIDC](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims).

O job usa o environment `production`, que passa a compor o `sub` no lugar da branch. Configure esse environment no GitHub para aceitar implantação da branch `main`, preservando as regras de aprovação adotadas pelo projeto. Revisores obrigatórios, quando configurados, fazem o deploy aguardar aprovação mesmo com o gatilho automático. A etapa `Registrar os parâmetros públicos da identidade OIDC` mostra somente emissor, audiência, assunto, repositório, IDs, ambiente e referências da branch e do workflow. O token fica mascarado e não é gravado em arquivo nem exibido. Em caso de `Not authorized to perform sts:AssumeRoleWithWebIdentity`, compare esses campos com **Trust relationships / Relações de confiança** de `tech-challenge-deploy-role`; alterações na política de permissões da EC2 não corrigem essa autenticação. [Configuração OIDC oficial do GitHub para AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).

A edição pelo console ou por `update-assume-role-policy` substitui o documento de confiança completo. Antes de salvar, copie a política vigente e acrescente a declaração da fase 3 ao seu array `Statement`, mantendo as outras declarações. Use no `sub` o valor confirmado pelo workflow. O arquivo de exemplo isolado não deve substituir esse documento combinado.

Adicione a política de implantação sem remover políticas existentes. O exemplo usa um perfil administrativo local exclusivamente para essa configuração inicial; ele não é necessário no runner OIDC:

```powershell
$perfilAdminAws = 'perfil-administrador-autorizado'
aws iam put-role-policy --profile $perfilAdminAws --role-name tech-challenge-deploy-role --policy-name TechChallengeFase3Deploy --policy-document file://docs/aws/deploy-role-policy.json
```

Essa política permite upload/download e inspeção somente do ECR `tech-challenge-fase-3`, autenticação ECR e leitura de estado em `eu-west-1`. `ssm:SendCommand` fica restrito ao documento AWS `AWS-RunShellScript` e à instância `i-024a7c79b3ec2bfa1`. As consultas sem escopo por recurso usam `Resource: "*"` com restrição de região. Ela não concede criação de infraestrutura, alteração de IAM ou sessões interativas. O Run Command exige autorização tanto para o documento quanto para o destino. [Configuração oficial do Run Command](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command-setting-up.html).

O papel da EC2 é independente do papel OIDC. Uma política que só permita ler o ECR `tech-challenge-fase-2` não permite baixar as novas imagens. Identifique o papel efetivamente associado à instância e acrescente a política de leitura; mantenha suas permissões SSM e demais permissões ainda necessárias:

```powershell
$arnPerfilInstancia = (aws ec2 describe-instances --profile $perfilAdminAws --region eu-west-1 --instance-ids i-024a7c79b3ec2bfa1 --query 'Reservations[0].Instances[0].IamInstanceProfile.Arn' --output text).Trim()
if ($LASTEXITCODE -ne 0 -or $arnPerfilInstancia -eq 'None' -or -not $arnPerfilInstancia) { throw 'A instância não informou um perfil IAM válido.' }
$nomePerfilInstancia = ($arnPerfilInstancia -split '/')[-1]
$nomePapelInstancia = (aws iam get-instance-profile --profile $perfilAdminAws --instance-profile-name $nomePerfilInstancia --query 'InstanceProfile.Roles[0].RoleName' --output text).Trim()
if ($LASTEXITCODE -ne 0 -or $nomePapelInstancia -eq 'None' -or -not $nomePapelInstancia) { throw 'Não foi possível identificar o papel IAM da instância.' }
aws iam put-role-policy --profile $perfilAdminAws --role-name $nomePapelInstancia --policy-name TechChallengeFase3EcrLeitura --policy-document file://docs/aws/ec2-ecr-policy.json
```

A política adicional da EC2 contém somente autenticação ECR e leitura de camadas/imagens do repositório da fase 3. Ela não substitui a política que mantém o agente SSM operacional e não concede publicação de imagens. [Permissões e exemplos oficiais do ECR](https://docs.aws.amazon.com/AmazonECR/latest/userguide/repository-policy-examples.html).

Para o agente SSM, use a política gerenciada `arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore`. Após confirmar sua associação à role da EC2, os blocos equivalentes de uma política inline podem ser retirados para evitar duplicação. Os blocos `ListDvcPrefix` e `ReadWriteDvcObjects` para `dvc-tech-challenge-fase-3` são dispensáveis: o projeto não usa esse bucket. Permissões usadas por outros serviços ou pelo retorno à fase 2 devem ser avaliadas separadamente. [Política oficial AmazonSSMManagedInstanceCore](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AmazonSSMManagedInstanceCore.html).

Após configurar os pré-requisitos, um push na `main` inicia CI e implantação. Pushes em outras branches e pull requests executam somente o CI. O gatilho direto de `ci.yml` exclui `main` para evitar duas validações do mesmo push; nessa branch, a validação pertence ao workflow de implantação.

A opção **Actions → Implantar na AWS → Run workflow** permanece disponível para repetir uma implantação ou incluir Airflow. Selecione `main` e mantenha `airflow` desmarcado para a implantação padrão. Habilite essa opção somente quando a instância tiver capacidade para o serviço adicional.

Acompanhe o CI, a autenticação OIDC, a publicação ECR, o comando SSM e o resultado da validação pública. A tag `latest` da API só é atualizada depois dessa verificação. O artefato `implantacao-aws-<run_id>` preserva o relatório gerado em `reports/aws/implantacao.json`. Um workflow preparado ou um login OIDC bem-sucedido não equivale a implantação concluída; esta preparação ainda não registra uma execução remota aprovada.

## Acesso e pré-requisitos

Para a alternativa manual em uma máquina local, use AWS CLI v2, Docker e um perfil com as permissões EC2, ECR e SSM descritas acima. No GitHub Actions, o workflow usa a role OIDC e dispensa esse perfil local. Não copie chaves para os arquivos Compose, imagens, documentação ou repositório.

O operador precisa de leitura da instância, consulta ao estado do SSM, acesso às sessões/comandos usados na implantação e publicação no ECR existente. A EC2 precisa alcançar o ECR e baixar imagens com sua própria função IAM ou mecanismo de autenticação aprovado. A autenticação do Docker usa `get-login-password` e `--password-stdin`, conforme o [guia oficial do ECR](https://docs.aws.amazon.com/AmazonECR/latest/userguide/docker-push-ecr-image.html).

Na EC2, são necessários Docker, espaço para as imagens e artefatos, acesso inicial ao corpus e Docker Compose **2.24.4 ou superior**. Os arquivos AWS usam `!reset` para remover o build local e `!override` para substituir a publicação de portas, conforme as [regras de composição do Docker](https://docs.docker.com/reference/compose-file/merge/).

Para Run Command, a instância deve estar registrada como nó gerenciado e com agente operacional. O cliente de implantação usa somente a AWS CLI. Para os túneis interativos apresentados ao final, a máquina do operador também precisa do plugin Session Manager. Os pré-requisitos de encaminhamento estão na [documentação oficial de sessões do SSM](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-sessions-start.html).

No PowerShell, `seu-perfil` representa o nome do perfil autorizado da sua máquina; informe esse nome e confira a conta e a instância:

```powershell
$perfilAws = 'seu-perfil'
$regiaoAws = 'eu-west-1'
$instanciaAws = 'i-024a7c79b3ec2bfa1'
aws sts get-caller-identity --profile $perfilAws
aws ec2 describe-instances --profile $perfilAws --region $regiaoAws --instance-ids $instanciaAws --query 'Reservations[].Instances[].{Estado:State.Name,IP:PublicIpAddress,Tipo:InstanceType,Arquitetura:Architecture}'
aws ssm describe-instance-information --profile $perfilAws --region $regiaoAws --filters "Key=InstanceIds,Values=$instanciaAws" --query 'InstanceInformationList[].{Instancia:InstanceId,Estado:PingStatus,Agente:AgentVersion}'
```

## Alternativa manual: construir e publicar as três imagens

Execute na raiz desta revisão, após os testes do projeto. Os exemplos geram imagens `linux/amd64`; compare essa plataforma com a arquitetura real da instância antes de publicar. O SHA identifica o código usado, e os perfis têm tags distintas. O bloco inclui a imagem Airflow para instalações completas; esse serviço é opcional na EC2 e sua ativação depende da capacidade verificada na inspeção.

```powershell
$registroEcr = '076516546831.dkr.ecr.eu-west-1.amazonaws.com'
$repositorioEcr = "$registroEcr/tech-challenge-fase-3"
$revisao = (git rev-parse HEAD).Trim()
$env:ECR_RUNTIME_IMAGE = "${repositorioEcr}:fase3-runtime-$revisao"
$env:ECR_TRAINING_IMAGE = "${repositorioEcr}:fase3-treinamento-$revisao"
$env:ECR_AIRFLOW_IMAGE = "${repositorioEcr}:fase3-airflow-$revisao"

docker build --platform linux/amd64 --target runtime -t medical-classifier:local .
if ($LASTEXITCODE -ne 0) { throw 'Falha ao construir a API.' }
docker build --platform linux/amd64 --target treinamento -t medical-classifier-treino:local .
if ($LASTEXITCODE -ne 0) { throw 'Falha ao construir o treinamento.' }
docker build --platform linux/amd64 -f Dockerfile.airflow -t medical-classifier-airflow:local .
if ($LASTEXITCODE -ne 0) { throw 'Falha ao construir o Airflow.' }

docker tag medical-classifier:local $env:ECR_RUNTIME_IMAGE
docker tag medical-classifier-treino:local $env:ECR_TRAINING_IMAGE
docker tag medical-classifier-airflow:local $env:ECR_AIRFLOW_IMAGE
aws ecr get-login-password --profile $perfilAws --region $regiaoAws | docker login --username AWS --password-stdin $registroEcr
if ($LASTEXITCODE -ne 0) { throw 'Falha ao autenticar no ECR.' }
docker push $env:ECR_RUNTIME_IMAGE
if ($LASTEXITCODE -ne 0) { throw 'Falha ao publicar a API.' }
docker push $env:ECR_TRAINING_IMAGE
if ($LASTEXITCODE -ne 0) { throw 'Falha ao publicar o treinamento.' }
docker push $env:ECR_AIRFLOW_IMAGE
if ($LASTEXITCODE -ne 0) { throw 'Falha ao publicar o Airflow.' }
```

Confirme os digests no ECR antes da implantação. Nos arquivos de ambiente remotos, prefira referências imutáveis no formato `registro/repositorio@sha256:...`; os overlays aceitam tags ou digests. `ECR_RUNTIME_IMAGE` e `ECR_TRAINING_IMAGE` são obrigatórias na stack principal; `ECR_AIRFLOW_IMAGE` é obrigatória quando o overlay do Airflow é usado. O fluxo manual acima não altera o workflow de publicação no GHCR.

## Composição remota e persistência

A stack principal combina `docker-compose.yml` com `docker-compose.aws.yml`. O Airflow usa seu próprio projeto, combinando `docker-compose.airflow.yml` com `docker-compose.airflow.aws.yml`. Os arquivos AWS não substituem os arquivos base.

| Serviço | Imagem | Publicação de porta |
|---|---|---|
| `api` | `ECR_RUNTIME_IMAGE` | `0.0.0.0:${API_PORT:-8000}:8000` |
| `pipeline` | `ECR_TRAINING_IMAGE` | Nenhuma |
| `prometheus` | Versão fixada na stack base | `127.0.0.1:${PROMETHEUS_PORT:-9090}:9090` |
| `grafana` | Versão fixada na stack base | `127.0.0.1:${GRAFANA_PORT:-3000}:3000` |
| `airflow` | `ECR_AIRFLOW_IMAGE` | `127.0.0.1:${AIRFLOW_PORT:-8080}:8080` |

A API preserva usuário sem root, sistema de arquivos somente leitura e montagem de modelos somente leitura. O pipeline continua com `--reutilizar`: usa uma versão íntegra e aprovada quando disponível; o primeiro preparo precisa produzir e validar os artefatos. O Airflow compartilha os mesmos volumes de dados e modelos.

Os nomes da fase 3 continuam `medical-classifier_dados`, `medical-classifier_modelos`, `medical-classifier_prometheus-dados`, `medical-classifier_grafana-dados` e `medical-classifier-airflow_airflow-estado`. A publicação preserva esses volumes e os volumes existentes da fase 2. O recibo registra os digests das novas imagens, os IDs dos containers antigos e suas políticas de reinício, além da versão do modelo e do resultado da troca.

O arquivo de ambiente remoto contém as imagens ECR habilitadas e a credencial exclusiva do Grafana, com acesso restrito ao operador. Não reutilize a senha pública de demonstração de `.env.example`. O script cria `implantacao.env` na pasta da release. Para validar manualmente a partir dessa pasta, use `config --quiet`, que não imprime a senha resolvida; execute a segunda linha somente quando Airflow estiver habilitado:

```bash
docker compose --env-file implantacao.env -f docker-compose.yml -f docker-compose.aws.yml config --quiet
docker compose --env-file implantacao.env -f docker-compose.airflow.yml -f docker-compose.airflow.aws.yml config --quiet
```

## Implantação controlada por SSM

O cliente `scripts/enviar_implantacao_aws.py`, também usado pelo workflow, prepara o comando SSM, acompanha a execução remota e verifica a API pública. `--perfil` é opcional: localmente seleciona um perfil nomeado; quando omitido, usa a cadeia normal de credenciais da AWS CLI, incluindo as credenciais temporárias OIDC do runner. O script remoto `scripts/implantar_ec2.py` realiza a inspeção, o preparo e a troca na mesma instância, preservando os dados para rollback. Credenciais não são incluídas no payload enviado à EC2.

O padrão mantém API, Prometheus e Grafana como serviços persistentes; o pipeline prepara o modelo. Na primeira implantação, Airflow só entra quando `--imagem-airflow` é informado; nas atualizações, uma instalação anterior dele é preservada. Quando solicitado, a prontidão do Airflow faz parte do sucesso da implantação. Verifique memória, disco e carga antes de habilitar o serviço adicional. Esses comandos não solicitam criação de instância, repositório ECR, grupo de segurança ou política IAM.

O treinamento tem limite de 1 GiB de memória, sem swap adicional, e uma CPU. A inspeção de memória antecede o preparo do modelo: exige 1.536 MiB disponíveis para o primeiro treino ou 512 MiB para atualização com modelo publicado. O comando SSM permite até 2.400 segundos; o script reserva tempo para recuperação e trata interrupções antes de concluir a troca. Uma máquina sem capacidade disponível deve abortar a preparação, preservando a aplicação em execução.

Monte os argumentos no PowerShell. As variáveis de imagem podem ser substituídas pelos digests confirmados no ECR:

```powershell
$parametrosImplantacao = @(
    '--perfil', $perfilAws,
    '--instancia', $instanciaAws,
    '--regiao', $regiaoAws,
    '--revisao', $revisao,
    '--imagem-runtime', $env:ECR_RUNTIME_IMAGE,
    '--imagem-treinamento', $env:ECR_TRAINING_IMAGE,
    '--url-publica', 'http://54.246.245.167:8000'
)
# Acrescente somente quando a implantação também incluir o Airflow:
# $parametrosImplantacao += @('--imagem-airflow', $env:ECR_AIRFLOW_IMAGE)

.venv/Scripts/python.exe scripts/enviar_implantacao_aws.py @parametrosImplantacao --preparar
if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar o comando de implantação.' }
```

`--preparar` gera o JSON de SSM sem chamar a AWS nem alterar a EC2. Revise esse material antes da execução. O cliente executa a implantação quando a opção é omitida:

```powershell
.venv/Scripts/python.exe scripts/enviar_implantacao_aws.py @parametrosImplantacao
if ($LASTEXITCODE -ne 0) { throw 'A implantação ou sua validação pública falhou; consulte o relatório.' }
```

O resultado local fica em `.local/aws_fase3/ultima_implantacao.json`. Preserve o identificador do comando SSM, as imagens e a versão do modelo registradas nessa execução. Um perfil sem permissões suficientes não pode concluir a implantação; a preparação offline não substitui esse acesso.

O script remoto também oferece uma validação dos argumentos, sem mutações, que pode ser executada localmente:

```powershell
.venv/Scripts/python.exe scripts/implantar_ec2.py --revisao $revisao --imagem-runtime $env:ECR_RUNTIME_IMAGE --imagem-treinamento $env:ECR_TRAINING_IMAGE --regiao $regiaoAws --validar
```

## Rollback e dados preservados

O script mantém `/opt/tech-challenge-fase-3/current.json` com o estado ativo e `current-anterior.json` quando existe uma implantação anterior da fase 3. Cada execução usa `releases/<timestampUTC>-<sha12>/`, com as fontes, `implantacao.env` restrito ao operador e `receipt.json`. O recibo registra `legados_ativos`, uma lista dos IDs exatos dos containers da fase 2 que estavam ativos antes da troca, limitada ao projeto `tech-challenge-fase-2`.

O rollback automático de uma primeira implantação remove somente os containers e a rede da stack nova, sem `--volumes`, restaura as políticas de reinício anteriores e reinicia os IDs legados registrados. Após uma troca bem-sucedida, os containers antigos permanecem parados com reinício automático desativado. Em uma atualização da fase 3, o retorno recupera a configuração anterior. Não existe uma opção CLI `--rollback`: para uma intervenção manual posterior, entre por SSM e use os estados efetivamente gravados. Os exemplos seguintes são Bash na EC2; execute `sudo -i` antes deles, pois os arquivos de estado pertencem ao root e têm modo 0600.

Primeiro leia os caminhos do estado ativo e pare seus serviços. As variáveis exportadas de outro deploy são removidas para que não sobrescrevam o arquivo de ambiente recuperado:

```bash
set -euo pipefail
unset ECR_RUNTIME_IMAGE ECR_TRAINING_IMAGE ECR_AIRFLOW_IMAGE
unset API_PORT PROMETHEUS_PORT GRAFANA_PORT AIRFLOW_PORT
unset GRAFANA_ADMIN_USER GRAFANA_ADMIN_PASSWORD
mapfile -t atual < <(python3 - <<'PY'
import json
from pathlib import Path
estado = json.loads(Path('/opt/tech-challenge-fase-3/current.json').read_text())
print(estado['diretorio'])
print(estado['arquivo_env'])
print(estado['imagens'].get('airflow', ''))
PY
)
if [ -n "${atual[2]}" ]; then
  docker compose -p medical-classifier-airflow --env-file "${atual[1]}" -f "${atual[0]}/docker-compose.airflow.yml" -f "${atual[0]}/docker-compose.airflow.aws.yml" stop airflow
fi
docker compose -p medical-classifier --env-file "${atual[1]}" -f "${atual[0]}/docker-compose.yml" -f "${atual[0]}/docker-compose.aws.yml" stop api prometheus grafana
```

Se houver `current-anterior.json`, restaure os serviços da fase 3 com suas imagens anteriores, sem executar o pipeline:

```bash
mapfile -t anterior < <(python3 - <<'PY'
import json
from pathlib import Path
estado = json.loads(Path('/opt/tech-challenge-fase-3/current-anterior.json').read_text())
print(estado['diretorio'])
print(estado['arquivo_env'])
print(estado['imagens'].get('airflow', ''))
PY
)
docker compose -p medical-classifier --env-file "${anterior[1]}" -f "${anterior[0]}/docker-compose.yml" -f "${anterior[0]}/docker-compose.aws.yml" up -d --no-deps api prometheus grafana
if [ -n "${anterior[2]}" ]; then
  docker compose -p medical-classifier-airflow --env-file "${anterior[1]}" -f "${anterior[0]}/docker-compose.airflow.yml" -f "${anterior[0]}/docker-compose.airflow.aws.yml" up -d --no-deps airflow
fi
```

Para retornar à fase 2 após a primeira implantação, quando não houver estado anterior da fase 3, reinicie somente os IDs registrados no recibo da release ativa:

```bash
python3 - "${atual[0]}/receipt.json" <<'PY'
import json
import subprocess
import sys
from pathlib import Path
recibo = json.loads(Path(sys.argv[1]).read_text())
legados = recibo['legados_ativos']
if not legados:
    raise SystemExit('O recibo não contém containers legados ativos para restaurar.')
for identificador, politica in recibo.get('politicas_legadas', {}).items():
    nome = politica['Name']
    tentativas = politica.get('MaximumRetryCount', 0)
    if nome == 'on-failure' and tentativas:
        nome = f'{nome}:{tentativas}'
    subprocess.run(['docker', 'update', f'--restart={nome}', identificador], check=True)
subprocess.run(['docker', 'start', *legados], check=True)
PY
```

Esses comandos preservam volumes e modelos; a troca de imagem não reverte o ponteiro do modelo armazenado no volume. Confira a versão servida após restaurar a fase 3. A intervenção manual acima não reescreve os arquivos de estado: preserve o recibo, registre qual configuração foi restaurada e reconcilie o estado antes de uma nova implantação. Não use `down --volumes`, `docker volume rm` ou limpeza global como procedimento de rollback.

Se a fase 3 estiver ativa sem `current.json`, uma nova implantação será bloqueada. Identifique o recibo da release pelos caminhos do Compose e pelos digests dos containers; confira também a versão em `/ready`. Recupere `current.json` somente a partir de um recibo bem-sucedido que corresponda a esses serviços. Se não houver correspondência verificável, restaure a última configuração conhecida antes de repetir o deploy.

## Verificar a API após a troca

A fase 3 expõe classificação de condições médicas por `POST /predict`. O corpo contém `texto`, com um resumo em inglês, idioma do corpus. `GET /health` confirma o processo e `GET /ready` confirma o modelo carregado; somente o health da fase 2 não comprova a atualização.

```powershell
Invoke-RestMethod 'http://54.246.245.167:8000/health'
Invoke-RestMethod 'http://54.246.245.167:8000/ready'
$corpo = @{ texto = 'Patients with coronary artery disease underwent cardiac evaluation and cardiovascular treatment.' } | ConvertTo-Json
Invoke-RestMethod 'http://54.246.245.167:8000/predict' -Method Post -ContentType 'application/json' -Body $corpo
```

Confirme `backend: onnx`, `classe_id` entre 1 e 5, probabilidades e `versao_modelo`. A rota de recomendação usada na fase anterior não representa o contrato desta API. A entrada vazia deve retornar HTTP 422. Registre essas respostas junto aos digests implantados e ao resultado do smoke remoto antes de marcar a implantação como concluída.

## Painéis por túnel

Mantenha Grafana, Prometheus e Airflow vinculados ao loopback da EC2. Os túneis abaixo são operacionais e precisam de permissões próprias de Session Manager; a política mínima do workflow não concede `ssm:StartSession`. No PowerShell, use um perfil humano autorizado e abra um terminal por túnel SSM; os parâmetros usam a forma abreviada da AWS CLI:

```powershell
aws ssm start-session --profile $perfilAws --region $regiaoAws --target $instanciaAws --document-name AWS-StartPortForwardingSession --parameters 'portNumber=3000,localPortNumber=13000'
aws ssm start-session --profile $perfilAws --region $regiaoAws --target $instanciaAws --document-name AWS-StartPortForwardingSession --parameters 'portNumber=9090,localPortNumber=19090'
aws ssm start-session --profile $perfilAws --region $regiaoAws --target $instanciaAws --document-name AWS-StartPortForwardingSession --parameters 'portNumber=8080,localPortNumber=18080'
```

Acesse Grafana em `http://127.0.0.1:13000`, Prometheus em `http://127.0.0.1:19090` e Airflow em `http://127.0.0.1:18080`. Ajuste a porta remota caso as variáveis correspondentes tenham sido alteradas. A autenticação dos painéis continua obrigatória onde configurada.

Se o acesso SSH já estiver autorizado, o encaminhamento equivalente usa o usuário e a chave confirmados para essa instância:

```text
ssh -N -L 13000:127.0.0.1:3000 -L 19090:127.0.0.1:9090 -L 18080:127.0.0.1:8080 -i CAMINHO_DA_CHAVE USUARIO_CONFIRMADO@54.246.245.167
```

Não é necessário publicar as portas dos painéis em `0.0.0.0` para acessá-los por esses túneis.
