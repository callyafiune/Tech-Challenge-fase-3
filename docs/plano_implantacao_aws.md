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
- [ ] Submeter a implementação a revisão adversarial Claude Code `fable` e tratar os achados.
- [ ] Publicar as imagens com identificação da revisão e conferir seus digests.
- [ ] Preparar arquivos e modelos na instância, verificando o candidato antes da troca da porta pública.
- [ ] Substituir a aplicação anterior e verificar `/health`, `/ready` e `/predict` externamente.
- [ ] Registrar recursos, imagens, modelo e resultado da implantação, sem credenciais.

**Estado:** automação preparada e verificada localmente; implantação remota pendente. As cinco variáveis e as políticas necessárias estão descritas em [aws.md](aws.md). O IP público responde ao health da aplicação anterior. A execução do workflow precisa confirmar autenticação OIDC, permissões no ECR e acesso ao SSM antes da troca.
