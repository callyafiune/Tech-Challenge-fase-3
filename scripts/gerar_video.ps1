<#
.SYNOPSIS
Gera uma apresentação STAR narrada a partir das evidências reais do projeto.
.DESCRIPTION
Usa System.Drawing, Microsoft Maria Desktop e FFmpeg, sem capturar a área de trabalho.
Os arquivos de trabalho ficam em .local/video e o MP4 final fica em reports/video.
#>
[CmdletBinding()]
param(
    [string]$ApiUrl = 'http://127.0.0.1:8000',
    [switch]$SomenteImagens
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Speech

$Raiz = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Temporarios = Join-Path $Raiz '.local/video'
if ($SomenteImagens) { $Temporarios = Join-Path $Temporarios 'imagens' }
$Entrega = Join-Path $Raiz 'reports/video'
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$Cultura = [System.Globalization.CultureInfo]::GetCultureInfo('pt-BR')
$Invariante = [System.Globalization.CultureInfo]::InvariantCulture
$Instante = [DateTime]::UtcNow.ToString('o')
$Marinho = [System.Drawing.ColorTranslator]::FromHtml('#142E41')
$Verde = [System.Drawing.ColorTranslator]::FromHtml('#087F80')
$Papel = [System.Drawing.ColorTranslator]::FromHtml('#F5F3EC')
$Cinza = [System.Drawing.ColorTranslator]::FromHtml('#526674')
$Branco = [System.Drawing.Color]::White
$Amarelo = [System.Drawing.ColorTranslator]::FromHtml('#E4B957')
$Largura = 1280
$Altura = 720

foreach ($Diretorio in @($Temporarios, $Entrega)) {
    $Resolvido = [System.IO.Path]::GetFullPath($Diretorio)
    if (-not $Resolvido.StartsWith($Raiz + [System.IO.Path]::DirectorySeparatorChar)) {
        throw 'Diretório de saída fora do repositório.'
    }
    [System.IO.Directory]::CreateDirectory($Resolvido) | Out-Null
}

function Ler-Json([string]$Relativo) {
    $Caminho = Join-Path $Raiz $Relativo
    if (-not (Test-Path -LiteralPath $Caminho -PathType Leaf)) {
        throw "A evidência necessária ainda não existe: $Relativo"
    }
    return Get-Content -LiteralPath $Caminho -Encoding UTF8 -Raw | ConvertFrom-Json
}

function Numero([double]$Valor, [int]$Casas = 2) {
    return $Valor.ToString("N$Casas", $Cultura)
}

function Campo($Objeto, [string]$Nome) {
    if ($null -eq $Objeto) { return $null }
    $Propriedade = $Objeto.PSObject.Properties[$Nome]
    if ($null -eq $Propriedade) { return $null }
    return $Propriedade.Value
}

function Testar-SucessoBooleano($Objeto) {
    $Sucesso = Campo $Objeto 'sucesso'
    return ($Sucesso -is [bool]) -and $Sucesso
}

function Verificar-VersaoApi($Pronta, $Resposta, [string]$VersaoEsperada) {
    if ($Pronta.versao_modelo -ne $VersaoEsperada -or
        $Resposta.versao_modelo -ne $VersaoEsperada -or
        $Pronta.backend -ne $Resposta.backend) {
        throw 'As respostas /ready e /predict precisam usar a mesma versão dos relatórios e o mesmo motor.'
    }
}

function Verificar-AmbienteRelatorios($Http, $Latencia) {
    if ((Campo $Http 'ambiente_servidores') -ne 'host' -or
        (Campo $Latencia 'metodo') -notmatch 'sem HTTP') {
        throw 'Os gráficos exigem HTTP do host e inferência em processo sem HTTP.'
    }
}

function Testar-ExecucaoDag($Execucao) {
    $Valida = (Testar-SucessoBooleano $Execucao) -and
        ((Campo $Execucao 'dag_id') -eq 'retreino_medico') -and
        (-not [string]::IsNullOrWhiteSpace((Campo $Execucao 'run_id'))) -and
        ((Campo (Campo $Execucao 'modelo') 'release') -match '^releases/[A-Za-z0-9_-]+$')
    $Etapas = Campo $Execucao 'tarefas'
    foreach ($Etapa in @('ingestao', 'treinamento', 'validacao', 'publicacao')) {
        $Valida = $Valida -and ((Campo $Etapas $Etapa) -eq 'success')
    }
    return $Valida
}

function Retangulo($Grafico, [float]$X, [float]$Y, [float]$W, [float]$H, $Cor) {
    $Pincel = New-Object System.Drawing.SolidBrush($Cor)
    try { $Grafico.FillRectangle($Pincel, $X, $Y, $W, $H) }
    finally { $Pincel.Dispose() }
}

function Texto {
    param($Grafico, [string]$Conteudo, [float]$X, [float]$Y, [float]$W,
        [float]$H, [float]$Tamanho = 28, $Cor = $Marinho, [switch]$Negrito)
    $Estilo = [System.Drawing.FontStyle]::Regular
    if ($Negrito) { $Estilo = [System.Drawing.FontStyle]::Bold }
    $Formato = New-Object System.Drawing.StringFormat
    $Formato.Trimming = [System.Drawing.StringTrimming]::None
    $Pincel = New-Object System.Drawing.SolidBrush($Cor)
    $Fonte = $null
    try {
        do {
            if ($null -ne $Fonte) { $Fonte.Dispose() }
            $Fonte = New-Object System.Drawing.Font('Segoe UI', $Tamanho, $Estilo,
                [System.Drawing.GraphicsUnit]::Pixel)
            $Medida = $Grafico.MeasureString($Conteudo, $Fonte,
                [System.Drawing.SizeF]::new($W, 10000), $Formato)
            if ($Medida.Height -le $H) { break }
            $Tamanho -= 1
        } while ($Tamanho -ge 14)
        if ($Medida.Height -gt $H) { throw "Texto excede a área disponível: $Conteudo" }
        $Grafico.DrawString($Conteudo, $Fonte, $Pincel,
            [System.Drawing.RectangleF]::new($X, $Y, $W, $H), $Formato)
    }
    finally {
        if ($null -ne $Fonte) { $Fonte.Dispose() }
        $Pincel.Dispose()
        $Formato.Dispose()
    }
}

function Estatistica($Grafico, [string]$Valor, [string]$Rotulo, [float]$X, [float]$Y,
    [float]$W = 365) {
    Retangulo $Grafico $X $Y $W 145 $Branco
    Texto $Grafico $Valor ($X + 24) ($Y + 18) ($W - 48) 67 51 $Verde -Negrito
    Texto $Grafico $Rotulo ($X + 24) ($Y + 90) ($W - 48) 45 24 $Cinza
}

function Barras($Grafico, [string]$Titulo, [double]$Original, [double]$Otimizado,
    [double]$Fator, [float]$X) {
    Retangulo $Grafico $X 295 548 287 $Branco
    Texto $Grafico $Titulo ($X + 24) 312 490 42 28 $Marinho -Negrito
    Texto $Grafico ((Numero $Fator) + '× mais rápido no p50') ($X + 24) 355 490 42 27 $Verde -Negrito
    Texto $Grafico ('scikit-learn   ' + (Numero $Original 3) + ' ms') ($X + 24) 414 490 30 23 $Cinza
    Retangulo $Grafico ($X + 24) 451 480 22 $Marinho
    Texto $Grafico ('ONNX   ' + (Numero $Otimizado 3) + ' ms') ($X + 24) 492 490 30 23 $Cinza
    Retangulo $Grafico ($X + 24) 529 ([float](480 * $Otimizado / $Original)) 22 $Verde
}

$Qualidade = Ler-Json 'reports/qualidade.json'
$Latencia = Ler-Json 'reports/latencia_modelo.json'
$Http = Ler-Json 'reports/latencia_http_local.json'
Verificar-AmbienteRelatorios $Http $Latencia
if ($Qualidade.versao_modelo -ne $Latencia.versao_modelo) {
    throw 'Qualidade e latência em processo pertencem a versões diferentes.'
}
$Modelo = $Qualidade.versao_modelo
if ($Http.prontidao.sklearn.versao_modelo -ne $Modelo -or
    $Http.prontidao.onnx.versao_modelo -ne $Modelo) {
    throw 'O benchmark HTTP local deve ser refeito para a mesma versão dos relatórios do modelo.'
}
$Auditoria = $Qualidade.auditoria_dados
$StackConcluida = $false
$Stack = $null
$VersaoStack = $null
if (Test-Path -LiteralPath (Join-Path $Raiz 'reports/smoke_stack.json')) {
    $Stack = Ler-Json 'reports/smoke_stack.json'
    $StackConcluida = Testar-SucessoBooleano $Stack
    $VersaoStack = Campo (Campo $Stack 'modelo') 'versao'
}

$Prontidao = $null
$Predicao = $null
$FalhaApi = $null
$Exemplo = 'The study evaluated cardiovascular risk factors and the association between hypertension and coronary artery disease.'
try {
    $Prontidao = Invoke-RestMethod -Uri ($ApiUrl.TrimEnd('/') + '/ready') -TimeoutSec 8
    $Corpo = @{ texto = $Exemplo } | ConvertTo-Json -Compress
    # No Windows PowerShell, a leitura explícita evita interpretar JSON UTF-8 como Latin-1.
    $RespostaApi = Join-Path $Temporarios 'api-predicao.json'
    Invoke-RestMethod -Method Post -Uri ($ApiUrl.TrimEnd('/') + '/predict') `
        -ContentType 'application/json' -Body $Corpo -TimeoutSec 8 -OutFile $RespostaApi
    $Predicao = [System.IO.File]::ReadAllText($RespostaApi, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
}
catch { $FalhaApi = 'A API não respondeu às duas chamadas no instante da captura.' }
if ($null -ne $Predicao) {
    Verificar-VersaoApi $Prontidao $Predicao $Modelo
}

$FonteDag = Get-Content -LiteralPath (Join-Path $Raiz 'dags/retreino_medico.py') -Encoding UTF8
$TrechoDag = ($FonteDag | Where-Object {
    $_ -match 'dag_id=|schedule=|max_active_runs=|for etapa in'
}) -join "`n"
$FonteCi = Get-Content -LiteralPath (Join-Path $Raiz '.github/workflows/ci.yml') -Encoding UTF8
$TrechoCi = ($FonteCi | Where-Object {
    $_ -match 'name: Executar análise|name: Construir|name: Importar|name: Executar as quatro|name: Verificar a stack'
}) -join "`n"
if ([string]::IsNullOrWhiteSpace($TrechoCi)) {
    throw 'O workflow não contém os passos esperados para o cartão de configuração.'
}

$Airflow = $null
$AirflowBuild = $null
$FonteBuildAirflow = $null
$VersaoDag = $null
$DagConcluida = $false
$RotuloDag = 'AIRFLOW / TRECHO ESTÁTICO'
$FonteAutomacao = 'Trechos estáticos: dags/retreino_medico.py e .github/workflows/ci.yml.'
if (Test-Path -LiteralPath (Join-Path $Raiz 'reports/airflow_execucao.json')) {
    $Airflow = Ler-Json 'reports/airflow_execucao.json'
    $DagConcluida = Testar-ExecucaoDag $Airflow
}
if (Test-Path -LiteralPath (Join-Path $Raiz 'reports/docker/build_airflow_state.json')) {
    $FonteBuildAirflow = 'reports/docker/build_airflow_state.json'
}
elseif (Test-Path -LiteralPath (Join-Path $Raiz 'reports/airflow_build_state.json')) {
    $FonteBuildAirflow = 'reports/airflow_build_state.json'
}
if ($null -ne $FonteBuildAirflow) {
    $AirflowBuild = Ler-Json $FonteBuildAirflow
}

if ($DagConcluida) {
    $VersaoDag = (Campo (Campo $Airflow 'modelo') 'release') -replace '^releases/', ''
    $EstadoDag = 'Airflow: quatro tarefas concluídas em uma execução real identificada.'
    $RotuloDag = 'AIRFLOW / EXECUÇÃO REAL REGISTRADA'
    $FonteAutomacao = 'Fonte Airflow: reports/airflow_execucao.json. GitHub Actions: trecho estático de ci.yml.'
    $TrechoDag = "DAG: $($Airflow.dag_id)`nExecução: $($Airflow.run_id)`n`ningestao: success`ntreinamento: success`nvalidacao: success`npublicacao: success`nVersão: $VersaoDag"
    $NarracaoAirflow = 'O relatório do Airflow confirma as quatro tarefas concluídas: ingestão, treinamento, validação e publicação, em uma execução identificada. O cartão mostra esses estados reais. O workflow do GitHub aparece como código estático; sua execução remota não é presumida.'
}
else {
    $EstadoDag = 'Airflow: sem evidência de execução completa das quatro tarefas nesta captura.'
    $NarracaoAirflow = 'A execução completa das quatro tarefas do Airflow ainda não tem evidência de sucesso nesta captura. Os cartões da DAG e do workflow são trechos estáticos, identificados como configuração. Também não presumimos execução remota no GitHub.'
    if ($null -ne $AirflowBuild -and (Campo $AirflowBuild 'interrompido_por_espaco') -eq $true) {
        $NarracaoAirflow += ' O último registro de construção informa interrupção por espaço em disco.'
    }
}

if ($StackConcluida) {
    $EstadoStack = "Stack API, Prometheus e Grafana: verificada; versão $VersaoStack."
    $NarracaoStack = 'A verificação real da stack retornou sucesso. Ela enviou chamadas, consultou métricas e confirmou a fonte de dados e os painéis do Grafana. ' + $NarracaoAirflow
}
else {
    $EstadoStack = 'Stack: sem relatório de verificação completa com sucesso nesta captura.'
    $NarracaoStack = 'Não há relatório de verificação completa da stack com sucesso nesta captura. Essa ausência não permite atribuir uma causa nem afirmar o funcionamento dos containers. ' + $NarracaoAirflow
}
if (($StackConcluida -and $VersaoStack -ne $Modelo) -or
    ($DagConcluida -and $VersaoDag -ne $Modelo)) {
    $NarracaoStack += ' Essas evidências operacionais incluem outra versão publicada no Docker, distinta da versão do host mostrada nos gráficos.'
    $FonteAutomacao = 'Evidência operacional: versão Docker distinta do host nos gráficos. GitHub: configuração estática.'
}

if ($null -ne $Predicao) {
    $TrechoApi = [ordered]@{
        status = $Prontidao.status
        classe_id = $Predicao.classe_id
        classe = $Predicao.classe
        backend = $Predicao.backend
        versao_modelo = $Predicao.versao_modelo
    } | ConvertTo-Json
    $NarracaoApi = 'Nesta cena, os dados exibidos foram obtidos por chamadas reais aos endpoints de prontidão e classificação no endereço local. O exemplo público está em inglês. A resposta informa a classe, o motor e a versão efetivamente carregada. A entrada aceita de vinte a vinte mil caracteres. As cinco probabilidades são saídas do classificador; não são uma medida calibrada de risco clínico.'
}
else {
    $TrechoApi = $FalhaApi
    $NarracaoApi = 'O exemplo desta cena mostra o contrato de entrada, mas a API não respondeu às chamadas no instante da captura. Essa indisponibilidade fica registrada nas evidências do vídeo. Não apresentamos uma resposta inventada. A implementação aceita um resumo em inglês de vinte a vinte mil caracteres e identifica a versão do modelo em cada predição. As probabilidades não representam uma medida calibrada de risco clínico.'
}

$Cenas = @(
    @{
        etapa = 'SITUAÇÃO'; titulo = 'Classificação médica, com evidências'; fonte = 'Fonte: corpus público e escopo autorizado da atividade.'
        narracao = 'Esta apresentação reúne evidências capturadas nesta execução do Tech Challenge, fase três. O cenário exige um serviço capaz de organizar textos médicos com resposta rápida e operação observável. Usamos resumos públicos em inglês e classificamos cinco condições médicas. A adaptação foi autorizada para o projeto. Trata-se de uma demonstração acadêmica: as saídas não representam urgência, diagnóstico ou orientação clínica.'
    },
    @{
        etapa = 'TAREFA'; titulo = 'Do corpus à operação da API'; fonte = 'Diagrama da implementação; AWS ECS Fargate e ALB são uma proposta, sem provisionamento.'
        narracao = 'A tarefa foi implementar o ciclo completo: adquirir dados verificáveis, treinar um modelo leve, converter a inferência para ONNX e servir respostas por FastAPI. Também precisamos de testes e construção automatizada, retreino no Airflow e métricas no Prometheus e Grafana. O treinamento fica fora da API. Na proposta de nuvem, ECS Fargate e um balanceador atenderiam às requisições; essa infraestrutura AWS não foi provisionada.'
    },
    @{
        etapa = 'AÇÃO / DADOS'; titulo = 'A auditoria muda o experimento'; fonte = 'Fonte: reports/qualidade.json → auditoria_dados; semente 42; teste oficial preservado.'
        narracao = "O corpus original tem $(Numero $Auditoria.treino_original 0) linhas de treino e $(Numero $Auditoria.teste_oficial 0) de teste. A auditoria removeu do treino $(Numero $Auditoria.sobreposicoes_removidas_treino 0) sobreposições com o teste e $(Numero $Auditoria.rotulos_conflitantes_removidos 0) linhas com rótulos conflitantes. O ajuste usa $(Numero $Auditoria.treino 0) exemplos e a validação usa $(Numero $Auditoria.validacao 0). O teste oficial foi preservado. O TF-IDF aprende somente no ajuste, e as escolhas técnicas não usam o teste final."
    },
    @{
        etapa = 'AÇÃO / API'; titulo = 'Uma resposta que identifica o modelo'; fonte = "Captura HTTP: $Instante • exemplo público; resposta reduzida aos campos exibidos."
        narracao = $NarracaoApi
    },
    @{
        etapa = 'AÇÃO / AUTOMAÇÃO'; titulo = 'Configuração e execução são evidências diferentes'; fonte = $FonteAutomacao
        narracao = $NarracaoStack
    },
    @{
        etapa = 'RESULTADO'; titulo = 'Otimização medida no mesmo modelo'; fonte = 'Fontes: qualidade.json, latencia_modelo.json e latencia_http_local.json. HTTP fora de Docker.'
        narracao = "No teste oficial, a acurácia foi $(Numero ($Qualidade.teste.onnx.acuracia * 100)) por cento e a F1 macro foi $(Numero $Qualidade.teste.onnx.f1_macro 4). A conversão preservou as classes na validação. Em $(Numero $Latencia.onnx.amostras 0) medições por motor, ONNX foi $(Numero $Latencia.fator_aceleracao_p50) vezes mais rápido na mediana da inferência completa. No HTTP local, fora de Docker, a aceleração foi $(Numero $Http.fator_aceleracao_p50) vezes em $(Numero $Http.onnx.amostras 0) chamadas por motor. Rede, validação e serialização reduzem o ganho observado na API."
    },
    @{
        etapa = 'RESULTADO / APRENDIZADOS'; titulo = 'Reproduzir, verificar e declarar os limites'; fonte = 'Narração sintética por Microsoft Maria Desktop; evidências locais desta captura.'
        narracao = 'O principal aprendizado é que otimização precisa preservar comportamento e demonstrar ganho no caminho realmente medido. Os artefatos, relatórios e respostas da API registram a versão usada. Revisões adversariais por bloco ajudam a encontrar falhas e exigem análise dos achados. Os limites de infraestrutura permanecem explícitos. Esta apresentação usa narração sintética e foi montada a partir de evidências locais, sem simular telas de sistemas ou validação clínica.'
    }
)

$QuantidadePalavras = ((($Cenas | ForEach-Object { $_.narracao }) -join ' ') -split '\s+').Count
$Manifesto = [ordered]@{
    inicio_utc = $Instante
    tipo = 'Apresentação STAR com narração sintética e imagens programáticas'
    voz = 'Microsoft Maria Desktop'
    velocidade_voz = 3
    versao_modelo = $Modelo
    api_url = $ApiUrl
    api_prontidao = $Prontidao
    api_predicao = $Predicao
    api_erro = $FalhaApi
    api_mesma_versao_relatorios = ($null -ne $Predicao)
    stack_verificada = $StackConcluida
    versao_modelo_stack = $VersaoStack
    estado_stack = $EstadoStack
    dag_verificada = $DagConcluida
    versao_modelo_dag = $VersaoDag
    estado_dag = $EstadoDag
    airflow_execucao = $Airflow
    airflow_construcao = $AirflowBuild
    fonte_airflow_construcao = $FonteBuildAirflow
    palavras_narracao = $QuantidadePalavras
    fontes = @()
    cenas = @()
}
foreach ($Nome in @('reports/qualidade.json', 'reports/latencia_modelo.json',
    'reports/latencia_http_local.json', 'dags/retreino_medico.py', '.github/workflows/ci.yml')) {
    $Manifesto.fontes += @{ caminho = $Nome; sha256 = (Get-FileHash -LiteralPath (Join-Path $Raiz $Nome) -Algorithm SHA256).Hash.ToLowerInvariant() }
}
if ($null -ne $Stack) {
    $Manifesto.fontes += @{ caminho = 'reports/smoke_stack.json'; sha256 = (Get-FileHash -LiteralPath (Join-Path $Raiz 'reports/smoke_stack.json') -Algorithm SHA256).Hash.ToLowerInvariant() }
}
foreach ($Nome in @('reports/airflow_execucao.json', $FonteBuildAirflow)) {
    if ($null -eq $Nome) { continue }
    if (Test-Path -LiteralPath (Join-Path $Raiz $Nome)) {
        $Manifesto.fontes += @{ caminho = $Nome; sha256 = (Get-FileHash -LiteralPath (Join-Path $Raiz $Nome) -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
}

for ($Indice = 0; $Indice -lt $Cenas.Count; $Indice++) {
    $Cena = $Cenas[$Indice]
    $NumeroCena = $Indice + 1
    $Imagem = Join-Path $Temporarios ('cena-{0:D2}.png' -f $NumeroCena)
    $Bitmap = New-Object System.Drawing.Bitmap($Largura, $Altura)
    $Grafico = [System.Drawing.Graphics]::FromImage($Bitmap)
    $Grafico.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $Grafico.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    try {
        $Grafico.Clear($Papel)
        Retangulo $Grafico 0 0 1280 12 $Verde
        Texto $Grafico ('TECH CHALLENGE / FASE 3    •    ' + $Cena.etapa) 64 42 1120 35 22 $Verde -Negrito
        Texto $Grafico $Cena.titulo 64 97 1152 112 47 $Marinho -Negrito
        switch ($NumeroCena) {
            1 {
                Texto $Grafico "Resumos em inglês.`nCinco categorias médicas.`nUm ciclo de operação verificável." 64 251 668 260 41 $Marinho -Negrito
                Retangulo $Grafico 798 225 418 330 $Marinho
                Texto $Grafico "01  Neoplasias`n02  Sistema digestivo`n03  Sistema nervoso`n04  Cardiovasculares`n05  Condições gerais" 828 250 354 285 28 $Branco
                Texto $Grafico 'Uso educacional • sem classificação de urgência ou diagnóstico' 64 589 1145 40 24 $Cinza
            }
            2 {
                $Etapas = @('Corpus', 'Treino', 'Versão', 'FastAPI', 'Resposta')
                for ($Bloco = 0; $Bloco -lt $Etapas.Count; $Bloco++) {
                    $X = 64 + $Bloco * 234
                    Retangulo $Grafico $X 262 216 118 $Branco
                    Texto $Grafico $Etapas[$Bloco] ($X + 17) 300 183 47 29 $Marinho -Negrito
                    if ($Bloco -lt 4) { Texto $Grafico '›' ($X + 217) 288 22 53 40 $Verde }
                }
                Texto $Grafico 'Airflow: ingestão → treinamento → validação → publicação' 64 426 1130 55 30 $Marinho -Negrito
                Texto $Grafico "CI: lint, testes e build`nOperação: métricas HTTP, Prometheus e Grafana" 64 506 1130 112 29 $Cinza
            }
            3 {
                Estatistica $Grafico (Numero $Auditoria.treino 0) 'exemplos de ajuste' 64 229
                Estatistica $Grafico (Numero $Auditoria.validacao 0) 'exemplos de validação' 457 229
                Estatistica $Grafico (Numero $Auditoria.teste_oficial 0) 'exemplos de teste oficial' 850 229
                Texto $Grafico ((Numero $Auditoria.sobreposicoes_removidas_treino 0) + ' sobreposições removidas do treino') 64 426 1120 53 34 $Marinho -Negrito
                Texto $Grafico ((Numero $Auditoria.rotulos_conflitantes_removidos 0) + ' linhas com rótulos conflitantes removidas') 64 493 1120 58 34 $Marinho -Negrito
                Texto $Grafico 'TF-IDF ajustado só no treino; decisões técnicas sem usar o teste final.' 64 583 1120 48 26 $Cinza
            }
            4 {
                Retangulo $Grafico 64 227 547 365 $Marinho
                Texto $Grafico 'ENTRADA PÚBLICA / POST /predict' 88 250 498 42 23 $Amarelo -Negrito
                Texto $Grafico $Exemplo 88 314 495 207 31 $Branco
                Retangulo $Grafico 638 227 578 365 $Branco
                $RotuloResposta = 'CAPTURA INDISPONÍVEL NESTE INSTANTE'
                if ($null -ne $Predicao) { $RotuloResposta = 'RESPOSTAS REAIS: /ready + /predict' }
                Texto $Grafico $RotuloResposta 662 250 528 48 22 $Verde -Negrito
                Texto $Grafico $TrechoApi 662 314 528 238 25 $Marinho
                Texto $Grafico 'Contrato: 20 a 20.000 caracteres; probabilidades sem calibração clínica.' 64 609 1152 39 23 $Cinza
            }
            5 {
                Retangulo $Grafico 64 220 548 306 $Branco
                Texto $Grafico $RotuloDag 88 244 500 41 23 $Verde -Negrito
                Texto $Grafico $TrechoDag 88 299 500 198 23 $Marinho
                Retangulo $Grafico 638 220 578 306 $Branco
                Texto $Grafico 'GITHUB ACTIONS / TRECHO ESTÁTICO' 662 244 526 42 22 $Verde -Negrito
                Texto $Grafico $TrechoCi 662 299 526 198 22 $Marinho
                Retangulo $Grafico 64 549 1152 90 $Marinho
                Texto $Grafico ($EstadoStack + "`n" + $EstadoDag) 89 566 1102 59 25 $Branco
            }
            6 {
                Texto $Grafico ('Acurácia teste: ' + (Numero ($Qualidade.teste.onnx.acuracia * 100)) + '%     |     F1 macro: ' + (Numero $Qualidade.teste.onnx.f1_macro 4)) 64 220 1150 52 31 $Marinho -Negrito
                Barras $Grafico 'Inferência completa / em processo' $Latencia.sklearn.p50_ms $Latencia.onnx.p50_ms $Latencia.fator_aceleracao_p50 64
                Barras $Grafico 'HTTP local / fora de Docker' $Http.sklearn.p50_ms $Http.onnx.p50_ms $Http.fator_aceleracao_p50 668
                Texto $Grafico ('Mesmo modelo • lote 1 • ordem alternada • ' + $Latencia.onnx.amostras + '/' + $Http.onnx.amostras + ' medições por motor') 64 609 1150 36 23 $Cinza
            }
            7 {
                Texto $Grafico "01  Comparar qualidade e latência`n02  Preservar versões e proveniência`n03  Revisar falhas por bloco`n04  Declarar o que ainda não foi demonstrado" 64 248 1136 281 36 $Marinho -Negrito
                Retangulo $Grafico 64 561 1152 72 $Verde
                Texto $Grafico 'Evidências capturadas nesta execução • narração sintética • uso acadêmico' 88 580 1105 39 27 $Branco -Negrito
            }
        }
        Texto $Grafico $Cena.fonte 64 669 1065 32 15 $Cinza
        Texto $Grafico ("$NumeroCena / " + $Cenas.Count) 1156 668 66 29 18 $Cinza
        $Bitmap.Save($Imagem, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally { $Grafico.Dispose(); $Bitmap.Dispose() }
    $Manifesto.cenas += [ordered]@{ numero = $NumeroCena; titulo = $Cena.titulo; imagem = $Imagem; narracao = $Cena.narracao }
}

[System.IO.File]::WriteAllText((Join-Path $Temporarios 'narracao.txt'),
    (($Cenas | ForEach-Object { $_.titulo + "`n" + $_.narracao }) -join "`n`n"), $Utf8)
if ($SomenteImagens) {
    [System.IO.File]::WriteAllText((Join-Path $Temporarios 'evidencias-imagens.json'),
        ($Manifesto | ConvertTo-Json -Depth 12), $Utf8)
    Write-Output "Imagens geradas em $Temporarios; $QuantidadePalavras palavras de narração."
    exit 0
}

$Ffmpeg = (Get-Command ffmpeg -CommandType Application -ErrorAction Stop).Source
$Ffprobe = (Get-Command ffprobe -CommandType Application -ErrorAction Stop).Source
$Sintetizador = New-Object System.Speech.Synthesis.SpeechSynthesizer
$Sintetizador.SelectVoice('Microsoft Maria Desktop')
$Sintetizador.Rate = 3
$Sintetizador.Volume = 100
$ArquivosCenas = @()
try {
    for ($Indice = 0; $Indice -lt $Cenas.Count; $Indice++) {
        $NumeroCena = $Indice + 1
        $Prefixo = Join-Path $Temporarios ('cena-{0:D2}' -f $NumeroCena)
        $Wav = $Prefixo + '.wav'
        $Video = $Prefixo + '.mp4'
        $Sintetizador.SetOutputToWaveFile($Wav)
        $Sintetizador.Speak($Cenas[$Indice].narracao)
        $Sintetizador.SetOutputToNull()
        $DuracaoTexto = & $Ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $Wav
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao medir o áudio da cena.' }
        $Duracao = [double]::Parse(($DuracaoTexto -join '').Trim(), $Invariante) + 1.5
        $DuracaoFfmpeg = $Duracao.ToString('0.000', $Invariante)
        & $Ffmpeg -hide_banner -loglevel error -y -loop 1 -framerate 5 -i ($Prefixo + '.png') `
            -i $Wav -c:v libx264 -preset veryfast -crf 26 -tune stillimage -threads 2 `
            -pix_fmt yuv420p -r 5 -c:a aac -b:a 80k -af apad -t $DuracaoFfmpeg -movflags +faststart $Video
        if ($LASTEXITCODE -ne 0) { throw "Falha do FFmpeg na cena $NumeroCena." }
        $Manifesto.cenas[$Indice].audio = $Wav
        $Manifesto.cenas[$Indice].video = $Video
        $Manifesto.cenas[$Indice].duracao_segundos = $Duracao
        $ArquivosCenas += "file '$(($Video -replace '\\', '/') -replace "'", "'\''")'"
        Write-Output "Cena $NumeroCena concluída: $DuracaoFfmpeg segundos."
    }
}
finally { $Sintetizador.Dispose() }

$Lista = Join-Path $Temporarios 'cenas.txt'
[System.IO.File]::WriteAllText($Lista, ($ArquivosCenas -join "`n"), $Utf8)
$Final = Join-Path $Entrega 'apresentacao_star.mp4'
& $Ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i $Lista -c copy -movflags +faststart $Final
if ($LASTEXITCODE -ne 0) { throw 'Falha ao concatenar o vídeo final.' }
$Detalhes = & $Ffprobe -v error -show_entries 'format=duration,size:stream=codec_name,width,height' -of json $Final
if ($LASTEXITCODE -ne 0) { throw 'Falha na validação final com ffprobe.' }
$Sonda = ($Detalhes -join "`n") | ConvertFrom-Json
$DuracaoFinal = [double]::Parse($Sonda.format.duration, $Invariante)
if ($DuracaoFinal -gt 300) { throw "O vídeo excede cinco minutos: $DuracaoFinal segundos." }
$TamanhoTemporarios = (Get-ChildItem -LiteralPath $Temporarios -File | Measure-Object Length -Sum).Sum
if ($TamanhoTemporarios -gt 100MB) { throw 'Os arquivos temporários excederam 100 MB.' }
$Manifesto.fim_utc = [DateTime]::UtcNow.ToString('o')
$Manifesto.arquivo_final = 'reports/video/apresentacao_star.mp4'
$Manifesto.sha256_video = (Get-FileHash -LiteralPath $Final -Algorithm SHA256).Hash.ToLowerInvariant()
$Manifesto.ffprobe = $Sonda
$Manifesto.temporarios_bytes = $TamanhoTemporarios
$Manifesto.duracao_validada = $true
[System.IO.File]::WriteAllText((Join-Path $Entrega 'evidencias.json'),
    ($Manifesto | ConvertTo-Json -Depth 12), $Utf8)
Write-Output "Vídeo validado: $Final; duração $DuracaoFinal segundos; temporários $TamanhoTemporarios bytes."
