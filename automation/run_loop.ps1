# Iwaparesu Kaggle improvement loop - runs unattended via Task Scheduler.
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$repoDir  = "C:\projects\05kaggleポケモンカード\pokemonAI-myspace"
$logDir   = Join-Path $repoDir "automation\logs"
$promptFile = Join-Path $repoDir "automation\loop_prompt.txt"
$claudeCmd  = "C:\Users\Yoshida\AppData\Roaming\npm\claude.cmd"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$logFile = Join-Path $logDir "run_$stamp.log"

Set-Location $repoDir

"=== Iwaparesu loop run started $stamp ===" | Tee-Object -FilePath $logFile -Append

# Pipe the prompt via stdin instead of as a CLI argument -- the prompt is
# long enough to exceed the Windows command-line length limit (~8191 chars
# via cmd.exe, which claude.cmd goes through).
Get-Content -Raw -Encoding UTF8 $promptFile | & $claudeCmd -p `
    --permission-mode bypassPermissions `
    --model claude-sonnet-5 `
    --output-format text `
    --no-session-persistence *>> $logFile

"=== Iwaparesu loop run finished $(Get-Date -Format 'yyyy-MM-dd_HHmmss') (exit code $LASTEXITCODE) ===" | Tee-Object -FilePath $logFile -Append
