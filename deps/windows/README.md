# Windows dependencies

Windows checkout tooling is intentionally not committed: installers and
extracted binaries stay out of git. On a fresh checkout, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-windows.ps1
```

The script detects what is missing and installs only that:

- **gh** - pinned to `2.102.0` from
  https://github.com/cli/cli/releases/tag/v2.102.0
  (SHA-256 `ae64e556ecc240b200f7eba60d550e4bb60d78e860e69dd88c449405b86067f4`,
  verified before extraction). Extracted to git-ignored `.tools\gh`.
- **specify CLI** - only needed for scaffold-level Spec Kit work
  (`specify init`, new integrations, upgrades). The `/speckit*` agent
  commands run from `.specify/scripts/` helpers without it. When `uv` is
  available, installs `specify-cli` at the version pinned in
  `.specify/init-options.json`.

`gh auth login` stays interactive and outside the repository:

```powershell
& .tools\gh\bin\gh.exe auth login --hostname github.com --git-protocol https --web
```
