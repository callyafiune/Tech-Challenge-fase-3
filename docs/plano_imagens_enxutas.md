# Plano — separar inferência, treinamento e desenvolvimento

**Objetivo:** reduzir a imagem Docker da API ao necessário para servir o modelo ONNX, preservando treinamento, benchmark, Airflow e monitoramento.

**Arquitetura:** a API usa uma imagem de inferência e o pipeline usa outra imagem com o extra `treinamento`. O Airflow incorpora o ambiente de treinamento, separado de suas dependências. O benchmark scikit-learn usa a imagem de treinamento. Ferramentas de teste, lint e construção do wheel ficam fora das imagens operacionais. O wheel é construído uma vez em estágio descartável; os ambientes finais recebem apenas as dependências fixadas do seu perfil.

**Restrições:** manter versões já fixadas, API e normalização existentes, artefatos/modelos históricos, usuário sem root, prontidão, volumes compartilhados e revisão Claude Code `fable`. Documentação e comentários em português Brasil. Não eliminar dependências transitivas exigidas pelos pacotes, nem migrar para uma base incompatível com as bibliotecas nativas do ONNX Runtime.

## Bloco 1 — desacoplamento e dependências

- [x] Reproduzir o carregamento indevido de pandas/scikit-learn ao importar a API.
- [x] Extrair classes, normalização e SHA-256 para `contracts.py`; manter os imports públicos existentes de `data.py` compatíveis.
- [x] Carregar joblib somente no backend scikit-learn e apresentar erro descritivo quando o extra estiver ausente.
- [x] Separar `pyproject.toml` em base de inferência, extra `treinamento` e extra `dev`.
- [x] Dividir os pins em locks de inferência, treinamento, construção e desenvolvimento, sem atualizar versões.
- [x] Validar importação fria e inferência real em ambiente sem pacotes de treinamento.

## Bloco 2 — imagens e integração

- [x] Medir tamanho e inventário da imagem anterior antes de substituir suas tags.
- [x] Criar targets `runtime` e `treinamento`; instalar sem bytecode/cache em ambientes próprios, com wheel produzido em estágio descartável.
- [x] Usar a imagem de treinamento no pipeline, benchmark scikit-learn e base do Airflow.
- [x] Atualizar CI para construir/testar os perfis, impedir dependências de treino/dev na API e manter a entrega da imagem validada.
- [x] Construir as imagens, comparar tamanhos e dependências, verificar reuso do pipeline, importação da DAG, API e consultas Grafana/Prometheus.
- [ ] Repetir o retreino completo no CI com a nova imagem.

## Bloco 3 — revisão e entrega

- [x] Registrar matriz de dependências, comandos e comparação medida em documentação própria.
- [x] Submeter o bloco de implementação a revisão adversarial Claude Code `fable`; corrigir achados confirmados e registrar decisões.
- [ ] Executar Ruff, suíte local, checks de dependências e CI completo.
- [ ] Publicar a implementação e os relatórios; preservar vídeo e evidências anteriores identificados como capturas históricas.

As imagens locais, a importação real da DAG, o reuso do pipeline, a API e o monitoramento foram verificados. A execução completa de retreino e o CI da revisão final serão registrados após a publicação do código.
