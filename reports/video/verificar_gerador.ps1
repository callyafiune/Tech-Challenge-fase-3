<#
.SYNOPSIS
Verifica os contratos das evidências e a preservação do MP4 no modo de imagens.
.DESCRIPTION
Execute na raiz do projeto após renderizar o vídeo e disponibilizar a API do host.
Extrai apenas as definições das funções do gerador; não executa o script por dot-source.
#>
[CmdletBinding()]
param(
    [string]$ApiUrl = 'http://127.0.0.1:8004',
    [switch]$SomenteContratos
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Raiz = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$Gerador = Join-Path $Raiz 'scripts/gerar_video.ps1'
$Tokens = $null
$Erros = $null
$Ast = [System.Management.Automation.Language.Parser]::ParseFile($Gerador, [ref]$Tokens, [ref]$Erros)
if ($Erros.Count -gt 0) { throw 'O gerador contém erros de sintaxe PowerShell.' }
foreach ($Nome in @('Campo', 'Testar-SucessoBooleano', 'Testar-ExecucaoDag', 'Verificar-VersaoApi', 'Verificar-AmbienteRelatorios', 'Obter-Monitoramento', 'Obter-ExecucaoCi')) {
    $Definicoes = @($Ast.FindAll({ param($No)
        $No -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $true) | Where-Object Name -eq $Nome)
    if ($Definicoes.Count -ne 1) { throw "Função esperada não identificada: $Nome" }
    . ([scriptblock]::Create($Definicoes[0].Extent.Text))
}

$Resultados = @()
function Conferir([string]$Nome, [bool]$Condicao) {
    if (-not $Condicao) { throw "Verificação reprovada: $Nome" }
    $script:Resultados += [ordered]@{ caso = $Nome; sucesso = $true }
}

function Testar-GeradorManifesto($Registro, [string]$HashEsperado) {
    $Fontes = @(Campo $Registro 'fontes')
    $FontesGerador = @($Fontes | Where-Object { (Campo $_ 'caminho') -eq 'scripts/gerar_video.ps1' })
    return $FontesGerador.Count -eq 1 -and (Campo $FontesGerador[0] 'sha256') -ceq $HashEsperado
}

function Testar-NarracaoIgual($Primeiro, $Segundo) {
    $CenasPrimeiro = @(Campo $Primeiro 'cenas')
    $CenasSegundo = @(Campo $Segundo 'cenas')
    if ($CenasPrimeiro.Count -eq 0 -or $CenasPrimeiro.Count -ne $CenasSegundo.Count) { return $false }
    for ($Indice = 0; $Indice -lt $CenasPrimeiro.Count; $Indice++) {
        $Narracao = Campo $CenasPrimeiro[$Indice] 'narracao'
        if ([string]::IsNullOrWhiteSpace($Narracao) -or
            $Narracao -cne (Campo $CenasSegundo[$Indice] 'narracao')) { return $false }
    }
    return $true
}

$ModeloManifesto = [pscustomobject]@{ fontes = @([pscustomobject]@{ caminho = 'scripts/gerar_video.ps1'; sha256 = 'hash-atual' }); cenas = @([pscustomobject]@{ narracao = 'Narração verificada.' }) }
Conferir 'Hash do gerador aceito quando coincide' (Testar-GeradorManifesto $ModeloManifesto 'hash-atual')
Conferir 'Hash do gerador divergente rejeitado' (-not (Testar-GeradorManifesto $ModeloManifesto 'outro-hash'))
Conferir 'Manifesto sem hash do gerador rejeitado' (-not (Testar-GeradorManifesto ([pscustomobject]@{ fontes = @() }) 'hash-atual'))
Conferir 'Narrações idênticas aceitas' (Testar-NarracaoIgual $ModeloManifesto $ModeloManifesto)
$OutraNarracao = [pscustomobject]@{ cenas = @([pscustomobject]@{ narracao = 'Narração alterada.' }) }
Conferir 'Narração alterada com mesma quantidade de cenas rejeitada' (-not (Testar-NarracaoIgual $ModeloManifesto $OutraNarracao))

$JsonDag = [System.IO.File]::ReadAllText((Join-Path $Raiz 'reports/docker/pos_correcao/integracao_verificada.json'))
$DagReal = $JsonDag | ConvertFrom-Json
$Dag = $JsonDag | ConvertFrom-Json
Conferir 'Execução real completa aceita' (Testar-ExecucaoDag $Dag)
$Dag.tarefas.validacao = 'failed'
Conferir 'Tarefa reprovada rejeitada' (-not (Testar-ExecucaoDag $Dag))
$Dag = $JsonDag | ConvertFrom-Json
$Dag.sucesso = 'true'
Conferir 'Sucesso textual da DAG rejeitado' (-not (Testar-ExecucaoDag $Dag))
$Dag = $JsonDag | ConvertFrom-Json
$Dag.run_id = ''
Conferir 'Execução sem identificador rejeitada' (-not (Testar-ExecucaoDag $Dag))
$Dag = $JsonDag | ConvertFrom-Json
$Dag.modelo.release = ''
Conferir 'Execução sem versão publicada rejeitada' (-not (Testar-ExecucaoDag $Dag))
Conferir 'Documento vazio rejeitado' (-not (Testar-ExecucaoDag ([pscustomobject]@{})))
Conferir 'Sucesso textual da stack rejeitado' (-not (Testar-SucessoBooleano ([pscustomobject]@{ sucesso = 'true' })))
Conferir 'Sucesso booleano da stack aceito' (Testar-SucessoBooleano ([pscustomobject]@{ sucesso = $true }))
Conferir 'Falha booleana da stack rejeitada' (-not (Testar-SucessoBooleano ([pscustomobject]@{ sucesso = $false })))

$Pronta = [pscustomobject]@{ versao_modelo = 'versao-esperada'; backend = 'onnx' }
Verificar-VersaoApi $Pronta $Pronta 'versao-esperada'
Conferir 'API e relatórios da mesma versão aceitos' $true
$DivergenciaRejeitada = $false
try { Verificar-VersaoApi $Pronta $Pronta 'versao-diferente' }
catch { $DivergenciaRejeitada = $true }
Conferir 'API de versão divergente rejeitada' $DivergenciaRejeitada
foreach ($RespostaInvalida in @(
    [pscustomobject]@{ versao_modelo = 'outra-versao'; backend = 'onnx' },
    [pscustomobject]@{ versao_modelo = 'versao-esperada'; backend = 'sklearn' }
)) {
    $Rejeitada = $false
    try { Verificar-VersaoApi $Pronta $RespostaInvalida 'versao-esperada' }
    catch { $Rejeitada = $true }
    Conferir ("Predict divergente rejeitado: $($RespostaInvalida.versao_modelo)/$($RespostaInvalida.backend)") $Rejeitada
}
$HttpHost = [pscustomobject]@{ ambiente_servidores = 'host' }
$LatenciaModelo = [pscustomobject]@{ metodo = 'Inferência completa, sem HTTP' }
Verificar-AmbienteRelatorios $HttpHost $LatenciaModelo
Conferir 'Ambientes esperados dos gráficos aceitos' $true
foreach ($ParInvalido in @(
    @{ http = [pscustomobject]@{ ambiente_servidores = 'docker' }; latencia = $LatenciaModelo },
    @{ http = $HttpHost; latencia = [pscustomobject]@{ metodo = 'Percurso HTTP' } }
)) {
    $Rejeitado = $false
    try { Verificar-AmbienteRelatorios $ParInvalido.http $ParInvalido.latencia }
    catch { $Rejeitado = $true }
    Conferir ("Ambiente incorreto rejeitado: $($ParInvalido.http.ambiente_servidores)/$($ParInvalido.latencia.metodo)") $Rejeitado
}

$JsonStack = [IO.File]::ReadAllText((Join-Path $Raiz 'reports/docker/pos_correcao/smoke_stack.json'))
$Prometheus = [IO.File]::ReadAllText((Join-Path $Raiz 'monitoring/prometheus/prometheus.yml'))
$FonteGrafana = [IO.File]::ReadAllText((Join-Path $Raiz 'monitoring/grafana/provisioning/datasources/prometheus.yml'))
$StackReal = $JsonStack | ConvertFrom-Json
$Monitoramento = Obter-Monitoramento $StackReal $Prometheus $FonteGrafana
Conferir 'Consultas reais de volume, p95 e erros extraídas' ($Monitoramento.consultas.Count -eq 3)
Conferir 'p95 preserva a unidade em segundos da consulta' ($Monitoramento.p95_segundos -eq $Monitoramento.consultas[1].valor)
foreach ($Caso in @('sucesso textual', 'sem fonte', 'sem consulta p95', 'valor textual', 'valor infinito', 'sem instante', 'coleta indisponivel', 'janela diferente', 'dashboard diferente', 'consulta de outro alvo', 'janela PromQL diferente')) {
    $Invalida = $JsonStack | ConvertFrom-Json
    switch ($Caso) {
        'sucesso textual' { $Invalida.sucesso = 'true' }
        'sem fonte' { $Invalida.grafana.fonte_dados = 'ERROR' }
        'sem consulta p95' { $Invalida.grafana.paineis = @($Invalida.grafana.paineis | Where-Object { $_.titulo -notlike 'Latência*' }) }
        'valor textual' { $Invalida.grafana.paineis[0].consultas[0].valor = '23' }
        'valor infinito' { $Invalida.grafana.paineis[0].consultas[0].valor = [double]::PositiveInfinity }
        'sem instante' { $Invalida.prometheus.instante_metricas_utc = '' }
        'coleta indisponivel' { $Invalida.prometheus.coleta = 'inativa' }
        'janela diferente' { $Invalida.prometheus.janela_taxa = '60s' }
        'dashboard diferente' { $Invalida.grafana.dashboard = 'outro-dashboard' }
        'consulta de outro alvo' { $Invalida.grafana.paineis[0].consultas[0].expressao = $Invalida.grafana.paineis[0].consultas[0].expressao.Replace('medical-api', 'outro') }
        'janela PromQL diferente' { $Invalida.grafana.paineis[4].consultas[1].expressao = $Invalida.grafana.paineis[4].consultas[1].expressao.Replace('[20s]', '[60s]') }
    }
    $Rejeitada = $false
    try { Obter-Monitoramento $Invalida $Prometheus $FonteGrafana | Out-Null }
    catch { $Rejeitada = $true }
    Conferir ("Monitoração inválida rejeitada: $Caso") $Rejeitada
}
foreach ($Configuracao in @(
    @{ prometheus = $Prometheus.Replace('scrape_interval: 5s', 'scrape_interval: 30s'); fonte = $FonteGrafana },
    @{ prometheus = $Prometheus; fonte = $FonteGrafana.Replace('http://prometheus:9090', 'http://outro:9090') }
)) {
    $Rejeitada = $false
    try { Obter-Monitoramento $StackReal $Configuracao.prometheus $Configuracao.fonte | Out-Null }
    catch { $Rejeitada = $true }
    Conferir 'Configuração diferente do fluxo narrado rejeitada' $Rejeitada
}
$JsonCi = [IO.File]::ReadAllText((Join-Path $Raiz 'reports/ci/34908437830/execucao.json'))
$Ci = Obter-ExecucaoCi ($JsonCi | ConvertFrom-Json)
Conferir 'CI identifica o commit realmente verificado' ($Ci.commit -eq '3a7ad7f052aa2ad246d399e4743f435bde8af221')
foreach ($Caso in @('passo reprovado', 'sem commit')) {
    $Invalida = $JsonCi | ConvertFrom-Json
    if ($Caso -eq 'passo reprovado') { $Invalida.jobs[0].steps[4].conclusion = 'failure' }
    else { $Invalida.commit = '' }
    $Rejeitada = $false
    try { Obter-ExecucaoCi $Invalida | Out-Null }
    catch { $Rejeitada = $true }
    Conferir ("CI inválido rejeitado: $Caso") $Rejeitada
}

if ($SomenteContratos) {
    $Saida = Join-Path $Raiz '.local/video/verificacao-contratos.json'
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Saida)) | Out-Null
    $Registro = @{ sucesso = $true; verificacoes = $Resultados; sha256_script = (Get-FileHash -LiteralPath $Gerador -Algorithm SHA256).Hash.ToLowerInvariant() }
    [IO.File]::WriteAllText($Saida, ($Registro | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
    Write-Output "$($Resultados.Count) contratos aprovados; nenhum arquivo da entrega foi alterado."
    exit 0
}

$CaminhosFinais = @('reports/video/apresentacao_star.mp4', 'reports/video/evidencias.json')
$Antes = @{}
foreach ($Nome in $CaminhosFinais) {
    $Antes[$Nome] = (Get-FileHash -LiteralPath (Join-Path $Raiz $Nome) -Algorithm SHA256).Hash.ToLowerInvariant()
}
$Manifesto = Get-Content -LiteralPath (Join-Path $Raiz 'reports/video/evidencias.json') -Encoding UTF8 -Raw | ConvertFrom-Json
$HashGerador = (Get-FileHash -LiteralPath $Gerador -Algorithm SHA256).Hash.ToLowerInvariant()
Conferir 'Manifesto final identifica o gerador atual pelo SHA-256' (Testar-GeradorManifesto $Manifesto $HashGerador)
Conferir 'Vídeo final registra a DAG real concluída' (($Manifesto.dag_verificada -is [bool]) -and $Manifesto.dag_verificada -and (Testar-ExecucaoDag $Manifesto.airflow_execucao))
$Intermediarios = @($Manifesto.cenas | ForEach-Object { $_.imagem; $_.audio; $_.video })
$Intermediarios += @((Join-Path $Raiz '.local/video/narracao.txt'), (Join-Path $Raiz '.local/video/api-predicao.json'))
$HashesIntermediarios = @{}
foreach ($Caminho in $Intermediarios) {
    $HashesIntermediarios[$Caminho] = (Get-FileHash -LiteralPath $Caminho -Algorithm SHA256).Hash
}
Conferir 'Vídeo corresponde ao SHA-256 do manifesto' ($Antes['reports/video/apresentacao_star.mp4'] -eq $Manifesto.sha256_video)
$SondaTexto = & ffprobe -v error -show_entries 'format=duration,size:stream=codec_name,width,height' -of json (Join-Path $Raiz 'reports/video/apresentacao_star.mp4')
Conferir 'Nova leitura ffprobe conclui com sucesso' ($LASTEXITCODE -eq 0)
$Sonda = ($SondaTexto -join "`n") | ConvertFrom-Json
$Duracao = [double]::Parse($Sonda.format.duration, [Globalization.CultureInfo]::InvariantCulture)
$DuracaoManifesto = [double]::Parse($Manifesto.ffprobe.format.duration, [Globalization.CultureInfo]::InvariantCulture)
Conferir 'Duração renderizada não excede 300 segundos' ($Duracao -gt 0 -and $Duracao -le 300)
Conferir 'Duração do manifesto corresponde ao MP4' ([Math]::Abs($Duracao - $DuracaoManifesto) -lt 0.001)
Conferir 'MP4 contém vídeo H.264 1280x720 e áudio AAC' (@($Sonda.streams | Where-Object { $_.codec_name -eq 'h264' -and $_.width -eq 1280 -and $_.height -eq 720 }).Count -eq 1 -and @($Sonda.streams | Where-Object codec_name -eq 'aac').Count -eq 1)

$LogImagens = Join-Path $Raiz '.local/video/verificacao-imagens.log'
$ErroImagens = Join-Path $Raiz '.local/video/verificacao-imagens-erro.log'
$Argumentos = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $Gerador + '"'), '-ApiUrl', ('"' + $ApiUrl + '"'), '-SomenteImagens')
$Processo = Start-Process -FilePath 'powershell.exe' -ArgumentList $Argumentos -WindowStyle Hidden `
    -RedirectStandardOutput $LogImagens -RedirectStandardError $ErroImagens -PassThru -Wait
$CodigoModoImagens = $Processo.ExitCode
$SaidaModoImagens = Get-Content -LiteralPath $LogImagens
Conferir 'Modo SomenteImagens conclui com sucesso' ($CodigoModoImagens -eq 0)
foreach ($Nome in $CaminhosFinais) {
    $Depois = (Get-FileHash -LiteralPath (Join-Path $Raiz $Nome) -Algorithm SHA256).Hash.ToLowerInvariant()
    Conferir ("Modo SomenteImagens preserva $Nome") ($Antes[$Nome] -eq $Depois)
}
$IntermediariosPreservados = $true
foreach ($Caminho in $Intermediarios) {
    $IntermediariosPreservados = $IntermediariosPreservados -and ($HashesIntermediarios[$Caminho] -eq (Get-FileHash -LiteralPath $Caminho -Algorithm SHA256).Hash)
}
Conferir ("Modo SomenteImagens preserva os $($Intermediarios.Count) arquivos intermediários do vídeo") $IntermediariosPreservados
$ManifestoImagens = Get-Content -LiteralPath (Join-Path $Raiz '.local/video/imagens/evidencias-imagens.json') -Encoding UTF8 -Raw | ConvertFrom-Json
Conferir 'Modo SomenteImagens capturou a API real' ([bool]$ManifestoImagens.api_mesma_versao_relatorios)
Conferir 'Modo SomenteImagens manteve a quantidade de cenas da renderização' ($ManifestoImagens.cenas.Count -eq $Manifesto.cenas.Count)
Conferir 'Narração de cada cena coincide com a renderização final' (Testar-NarracaoIgual $Manifesto $ManifestoImagens)
Conferir 'Prévia identifica o mesmo gerador atual' (Testar-GeradorManifesto $ManifestoImagens $HashGerador)
Conferir 'Prévia confirma a execução real da DAG' (($ManifestoImagens.dag_verificada -is [bool]) -and $ManifestoImagens.dag_verificada -and (Testar-ExecucaoDag $ManifestoImagens.airflow_execucao))
$VersaoDagReal = $DagReal.modelo.release -replace '^releases/', ''
foreach ($RegistroVideo in @($Manifesto, $ManifestoImagens)) {
    Conferir 'Monitoração coincide com a versão das fontes independentes smoke e DAG' ($RegistroVideo.monitoramento.versao_modelo -eq $StackReal.modelo.versao -and $RegistroVideo.versao_modelo_dag -eq $VersaoDagReal -and $RegistroVideo.monitoramento.versao_modelo -eq $VersaoDagReal)
    Conferir 'DAG da apresentação coincide com o identificador da fonte real' ($RegistroVideo.airflow_execucao.run_id -eq $DagReal.run_id)
    Conferir 'Monitoração registra as três consultas esperadas' ($RegistroVideo.monitoramento.consultas.Count -eq 3)
    foreach ($Consulta in $RegistroVideo.monitoramento.consultas) {
        $FonteConsulta = @($StackReal.grafana.paineis.consultas | Where-Object expressao -ceq $Consulta.expressao)
        Conferir 'Resultado da consulta coincide com o smoke independente' ($FonteConsulta.Count -eq 1 -and $Consulta.valor -eq $FonteConsulta[0].valor)
    }
}

$Registro = [ordered]@{
    registrado_em_utc = [DateTime]::UtcNow.ToString('o')
    comando = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File reports/video/verificar_gerador.ps1 -ApiUrl $ApiUrl"
    sucesso = $true
    verificacoes = $Resultados
    saida_somente_imagens = ($SaidaModoImagens -join "`n")
    codigo_saida_somente_imagens = $CodigoModoImagens
    sha256_script = (Get-FileHash -LiteralPath $Gerador -Algorithm SHA256).Hash.ToLowerInvariant()
    sha256_video = $Antes['reports/video/apresentacao_star.mp4']
    sha256_manifesto_final = $Antes['reports/video/evidencias.json']
    duracao_segundos = $Duracao
    ffprobe = $Sonda
}
$Utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $Raiz 'reports/video/verificacao.json'), ($Registro | ConvertTo-Json -Depth 8), $Utf8)
Write-Output "$($Resultados.Count) verificações aprovadas; MP4 e manifesto final preservados."
