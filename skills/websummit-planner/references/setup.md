# Runtime setup, including computers without Python

This guide is for a shell-capable agent. The user does not need to install Python manually. Use an existing interpreter when possible; otherwise install a user-owned runtime with uv. Internet access is required for the first runtime download, not for subsequent planning. Keep the runtime outside the installed skill and temporary repository checkout so it survives both removal of the checkout and skill upgrades.

## Choose an existing interpreter

Check the planner-managed interpreter first, then `python3`, `python`, and the Windows launcher `py -3`. The managed runtime location is:

- POSIX: `${XDG_DATA_HOME:-$HOME/.local/share}/websummit-planner/runtime/bin/python`
- Windows: `$HOME/.local/share/websummit-planner/runtime/Scripts/python.exe`

Run this probe with each candidate (avoid repeatedly invoking a Windows Store alias):

```sh
python3 -c "import sys, sqlite3; from zoneinfo import ZoneInfo; assert sys.version_info >= (3, 9); ZoneInfo('Europe/Lisbon'); print(sys.executable)"
```

Successful output gives the absolute interpreter path. Use that path for the installer and planner. Do not assume that the name `python` points to a suitable version or that timezone data is installed. If the probe fails, prepare the managed runtime below instead of modifying unrelated Python environments.

## Prepare uv only if needed

If `uv` is already available, reuse its absolute executable path. Otherwise download its official standalone installer, inspect it, then execute it as shown below. No existing Python or Node.js installation is needed. Use a temporary filename and download with the shell's native HTTP client; the examples use curl or PowerShell. Honor the host's normal approval rules. Use `UV_UNMANAGED_INSTALL` so the installer does not change shell profiles or PATH.

### macOS / Linux

```sh
planner_root="${XDG_DATA_HOME:-$HOME/.local/share}/websummit-planner"
mkdir -p "$planner_root/tools"
planner_installer=$(mktemp)
curl --fail --location --silent --show-error https://astral.sh/uv/install.sh --output "$planner_installer"
# Inspect the downloaded file before the next command.
UV_UNMANAGED_INSTALL="$planner_root/tools" sh "$planner_installer"
rm "$planner_installer"
planner_uv="$planner_root/tools/uv"
```

If uv already exists, set `planner_uv` to its absolute path and set `planner_root` as above; skip the download. If curl is absent, use an available HTTPS client to download the same URL. Do not use an unverified mirror or disable certificate verification.

Then prepare the runtime, substituting the existing uv path if applicable:

```sh
"$planner_uv" venv --python 3.12 --managed-python "$planner_root/runtime"
"$planner_uv" pip install --python "$planner_root/runtime/bin/python" tzdata
"$planner_root/runtime/bin/python" -c "import sqlite3; from zoneinfo import ZoneInfo; print(ZoneInfo('Europe/Lisbon'))"
```

### Windows PowerShell

```powershell
$plannerRoot = Join-Path $HOME '.local/share/websummit-planner'
$plannerTools = Join-Path $plannerRoot 'tools'
New-Item -ItemType Directory -Force -Path $plannerTools | Out-Null
$plannerInstaller = Join-Path ([IO.Path]::GetTempPath()) ('websummit-uv-' + [guid]::NewGuid() + '.ps1')
Invoke-WebRequest -Uri 'https://astral.sh/uv/install.ps1' -OutFile $plannerInstaller
# Inspect the downloaded file before the next commands.
$plannerPreviousInstall = $env:UV_UNMANAGED_INSTALL
try {
    $env:UV_UNMANAGED_INSTALL = $plannerTools
    & ([scriptblock]::Create((Get-Content -Raw $plannerInstaller)))
} finally {
    $env:UV_UNMANAGED_INSTALL = $plannerPreviousInstall
    Remove-Item -LiteralPath $plannerInstaller
}
$plannerUv = Join-Path $plannerTools 'uv.exe'
```

If uv already exists, set `$plannerUv` to its absolute path and `$plannerRoot` as above; skip the download. Then:

```powershell
& $plannerUv venv --python 3.12 --managed-python (Join-Path $plannerRoot 'runtime')
if ($LASTEXITCODE -ne 0) { throw 'Python runtime setup failed' }
$plannerPython = Join-Path $plannerRoot 'runtime/Scripts/python.exe'
& $plannerUv pip install --python $plannerPython tzdata
if ($LASTEXITCODE -ne 0) { throw 'Timezone data setup failed' }
& $plannerPython -c "import sqlite3; from zoneinfo import ZoneInfo; print(ZoneInfo('Europe/Lisbon'))"
```

On either platform, run commands one at a time and require success before continuing. Reuse a runtime that passes the probe. Do not overwrite an existing broken runtime silently: move only the planner's runtime folder aside before rebuilding if the user has requested repair. Preserve `2026.db` and other personal plans in its parent folder. If a platform policy blocks execution, report the restriction; do not weaken policy to install this skill.

Use the runtime's absolute Python path for normal planner commands, including later sessions. uv manages the downloaded base interpreter in its own user data directory; retain that installation as well as the runtime. Neither uv nor a package resolution step is needed at each use. The `tzdata` wheel is installed only in this dedicated runtime, allowing offline timezone support even where the OS provides none.

Official references: [uv standalone installer](https://docs.astral.sh/uv/getting-started/installation/), [installer placement without shell changes](https://docs.astral.sh/uv/reference/installer/), [managed Python](https://docs.astral.sh/uv/guides/install-python/).
