# Install YT2clips as a Claude Code skill (Windows PowerShell).
# Usage: .\install_as_skill.ps1 [-Force]   (-Force replaces an existing install without asking)
param([switch]$Force)
$ErrorActionPreference = "Stop"
$SkillDir = Join-Path $HOME ".claude\skills\youtube-clipper"
$Src = $PSScriptRoot

Write-Host "Installing to $SkillDir"
$savedEnv = $null
if (Test-Path $SkillDir) {
    if (-not $Force) {
        $answer = Read-Host "Existing install found. Replace it? (y/N)"
        if ($answer -notmatch '^[Yy]') { Write-Host "Cancelled."; exit 0 }
    }
    $envFile = Join-Path $SkillDir ".env"
    if (Test-Path $envFile) { $savedEnv = Get-Content $envFile -Raw }
    Remove-Item -Recurse -Force $SkillDir
}
New-Item -ItemType Directory -Force $SkillDir | Out-Null
foreach ($item in "SKILL.md", "README.md", "LICENSE", "requirements.txt", ".env.example", "scripts", "references") {
    Copy-Item -Recurse (Join-Path $Src $item) $SkillDir
}
Remove-Item -Recurse -Force (Join-Path $SkillDir "scripts\__pycache__") -ErrorAction SilentlyContinue
if ($savedEnv) { Set-Content -Path (Join-Path $SkillDir ".env") -Value $savedEnv -Encoding utf8 }

Write-Host "Installing Python packages..."
python -m pip install -q -r (Join-Path $SkillDir "requirements.txt")

Write-Host ""
python (Join-Path $SkillDir "scripts\check_env.py")
Write-Host ""
Write-Host 'Done. In Claude Code, say: "Make TikToks from https://youtube.com/watch?v=..."'
