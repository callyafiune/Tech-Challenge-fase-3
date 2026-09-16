# Plano — implantação na EC2 existente

**Objetivo:** disponibilizar a API de classificação médica na instância e porta usadas pela aplicação anterior, preservando uma possibilidade de retorno durante a troca.

**Arquitetura:** EC2 existente em `eu-west-1`, imagens versionadas no ECR `tech-challenge-fase-3` e execução remota pelo Systems Manager. O GitHub Actions assume o papel de implantação via OIDC. O Compose publica somente a API na porta 8000; Prometheus, Grafana e Airflow permanecem acessíveis por túnel. API e treinamento usam imagens separadas. A instância, os volumes existentes e o endereço da aplicação são preservados.

## Preparação

- [x] Identificar endpoint, instância, região e ECR pela implantação anterior.
- [x] Conferir resposta pública da aplicação anterior.
- [ ] Obter uma sessão AWS com permissões de implantação e inspecionar a capacidade da instância.
- [x] Criar sobreposições Compose que consumam imagens ECR sem construir no servidor.
- [x] Preparar automação de instalação, verificação e retorno para a versão anterior.

## Verificação e implantação

- [x] Validar os manifests e os caminhos de falha da automação.
- [x] Submeter a implementação a três rodadas de revisão adversarial Claude Code `fable` e tratar os achados com verificações locais.
- [x] Executar o CI remoto e verificar o encadeamento automático até a tentativa de autenticação da implantação.
- [ ] Publicar as imagens com identificação da revisão e conferir seus digests.
- [ ] Preparar arquivos e modelos na instância, verificando o candidato antes da troca da porta pública.
- [ ] Substituir a aplicação anterior e verificar `/health`, `/ready` e `/predict` externamente.
- [ ] Registrar recursos, imagens, modelo e resultado da implantação, sem credenciais.

**Estado:** a [execução 35038813631](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/runs/35038813631) da revisão `eacd3b9` concluiu o CI com sucesso. O job de implantação falhou na autenticação OIDC (`sts:AssumeRoleWithWebIdentity`), antes de publicar imagens no ECR ou enviar comandos ao SSM. Nenhuma implantação da fase 3 ocorreu nessa tentativa.

Os ajustes posteriores à terceira revisão incluem o artefato Airflow produzido pelo CI, a identificação de imagem herdada, a recusa de estado anterior junto a legados ativos, a validação do destino antes da publicação e o suporte a sufixos de versão do Compose. O conjunto específico de implantação passou 44 testes, com um ignorado por exigir POSIX. Os [resultados e limites](verificacao_aws.md) distinguem a revisão validada remotamente das alterações verificadas localmente.

A autenticação OIDC precisa ser corrigida antes das etapas ainda pendentes. As cinco variáveis e as políticas necessárias estão descritas em [aws.md](aws.md); a confirmação de ECR, SSM, capacidade da instância e inferência pública permanece necessária.
