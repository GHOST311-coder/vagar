# Vagar SAC supplemental policy â€” staging notes (Nov 18, 2026)

Staged 178 Vagar-signed .pyd/.dll files (326.3 MB) under wdac/staging/, plus the public certificate wdac/certs/vagar-signing.cer (thumbprint 1BF33FDE074368731FDC0FA8D911CCBC7D20393F, CN=Vagar Local Code Signing, expires 2036-11-16).

## What staging is for

Staging only feeds New-CIPolicy -Level Publisher on the GitHub Actions runner: it discovers the Vagar publisher and generates publisher rules. What actually allows the files is the Add-SignerRule step in the workflow, which trusts the Vagar certificate itself â€” so EVERY file signed by that certificate is allowed whether it was staged or not.

## Left out, and why

- Files over 100 MB cannot be pushed to GitHub (per-file limit): torch_cpu.dll (291.7 MB), _polars_runtime.pyd (167.7 MB), llvmlite.dll (114.8 MB). All three are Vagar-signed and covered by the signer rule.
- Packages outside the voice/text/token import closure were not staged: scipy, sklearn, pandas, matplotlib, numba, cv2, torchvision, win32/pywin32, tcl, PIL, lxml, fontTools, and similar. They are Vagar-signed (where signed) and covered by the signer rule; they can be signed later without a reboot once the policy is live (plan section 12).
- Files that are NOT Vagar-signed were never staged (plan section 9: stage ONLY Vagar-signed files). The PSF-signed stdlib files (socket, ssl, hashlib, etc.) and Microsoft-signed runtimes load fine today â€” SAC treats those signers as reputable, proven by live import tests Nov 18.

Excluded Vagar-signed files not staged: 349 files, ~835.200000000001 MB.

## Build

Workflow: .github/workflows/build-sac-policy.yml (runs on windows-latest via workflow_dispatch after the PAT lands and this branch is pushed). It verifies ConfigCI, verifies every staged file is Vagar-signed, runs New-CIPolicy -MultiplePolicyFormat -Level Publisher -ScanPath wdac/staging -NoScript -Fallback Hash, adds the signer rule (no -Supplemental switch), strips base-only rule options, validates with Test-CIPolicy, sets the policy ID supplementing base 0283ac0f-fff1-49ae-ada1-8a933130cad6, converts to .cip, and uploads it as an artifact.

## After the build

Download the .cip from the Actions run, copy it to C:\Windows\System32\CodeIntegrity\CiPolicies\Active\, verify with CiTool -lp, then reboot on justin's timing and run the section 12 verification. Do NOT deploy before the reboot gate.
