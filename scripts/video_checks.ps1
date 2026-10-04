# Video-friendly self-checks, offline (no API key): run from the repository root.
#
#   .\scripts\video_checks.ps1
#
# 1) Module A validation summary  2) pytest  3) smoke-check  4) change tests T1-T5 dashboard
# A 2 s pause and a large header separate the steps. Not legal advice.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Show-Header([string]$Step, [string]$Title) {
    Start-Sleep -Seconds 2
    $line = "=" * 78
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Write-Host ("   STEP {0}  |  {1}" -f $Step, $Title) -ForegroundColor White -BackgroundColor DarkBlue
    Write-Host $line -ForegroundColor Cyan
    Write-Host ""
}

# out/ is git-ignored: rebuild it from the frozen snapshot if needed (offline, ~5 s)
if (-not (Test-Path (Join-Path $Root "out\validation_report.json")) -or -not (Test-Path (Join-Path $Root "out\changes.json"))) {
    Write-Host "Preparing out/ from snapshots/a-0.4.0 (offline) ..." -ForegroundColor DarkGray
    & $Py -m extractor.cli reproduce | Out-Null
    & $Py -m resolver.cli changes | Out-Null
}

# 1) Module A validation summary ---------------------------------------------------------
Show-Header "1/4" "MODULE A - every quote verified in the source text"
$summary = @'
import json
v = json.load(open("out/validation_report.json", encoding="utf-8"))["global"]
rules = json.load(open("out/rules.json", encoding="utf-8"))["rules"]
m = v["match_types"]
verified = sum(m.values())
print(f"  Candidate rules extracted ......... {v['candidates']}")
print(f"  Quotes verified in the raw text ... {verified} / {v['candidates']}")
print(f"      exact ......................... {m.get('exact', 0)}")
print(f"      normalized .................... {m.get('normalized', 0)}")
print(f"      fuzzy ......................... {m.get('fuzzy', 0)}")
print(f"  LLM quote retries ................. {v['quote_retries']}")
print(f"  Rejected (unverifiable) ........... {v['dispositions'].get('rejected', 0)}")
print(f"  Rules exported to rules.json ...... {len(rules)}  (all with citation + verified quoted_span: "
      f"{sum(bool(r.get('citation')) and bool(r.get('quoted_span')) for r in rules)}/{len(rules)})")
'@
$summary | & $Py -

# 2) pytest ------------------------------------------------------------------------------
Show-Header "2/4" "AUTOMATED TESTS (offline)"
$out = & $Py -m pytest -q -p no:cacheprovider 2>&1 | ForEach-Object { "$_" }
$last = ($out | Where-Object { $_ -match "passed|failed|error" } | Select-Object -Last 1)
$color = if ($last -match "failed|error") { "Red" } else { "Green" }
Write-Host ("  " + $last.Trim()) -ForegroundColor $color

# 3) smoke-check -------------------------------------------------------------------------
Show-Header "3/4" "SMOKE CHECK - pipeline, citations, behaviour, rule map"
& $Py -m extractor.cli smoke-check

# 4) T1-T5 dashboard ---------------------------------------------------------------------
Show-Header "4/4" "MODULE C - change tests T1-T5 dashboard"
$dash = & $Py -m resolver.cli changes 2>&1 | ForEach-Object { "$_" }
$start = [Array]::FindIndex([string[]]$dash, [Predicate[string]]{ param($l) $l -match "MODULE C" })
if ($start -gt 0) { $start = $start - 1 } else { $start = 0 }
$dash[$start..($dash.Count - 1)] | ForEach-Object { Write-Host $_ }

Start-Sleep -Seconds 2
Write-Host ""
Write-Host "  Done. Not legal advice." -ForegroundColor DarkGray
