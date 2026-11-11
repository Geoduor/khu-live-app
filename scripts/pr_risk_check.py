#!/usr/bin/env python3
"""Flag the parts of a contributor's branch that deserve a slow, careful read.

Usage (from the repo root, nothing is executed from the branch under review):

    git fetch origin
    python3 scripts/pr_risk_check.py origin/main origin/their-branch

It only READS the git diff. It does not run, install or build anything from
the branch. It is a checklist generator, not a verdict: a clean report does
not mean the change is safe, and a flagged line is often perfectly fine.
Exit code: 0 = nothing flagged, 1 = something to look at.
"""
import re
import subprocess
import sys

# Files where one wrong line can hand over the app, the money or the servers.
SENSITIVE_PATHS = [
    (r"^\.github/", "repo rules / CI / CODEOWNERS"),
    (r"^render\.yaml$", "backend deploy: build and start commands"),
    (r"(^|/)vercel\.json$", "frontend headers and CSP"),
    (r"^edge/", "Cloudflare Worker: rate limits, payment callback relay"),
    (r"^backend/(mpesa|shop)\.py$", "payments"),
    (r"^backend/(main|database|dbconn|backup|push)\.py$", "backend core, auth, data, backups"),
    (r"^backend/scraper\.py$", "scraper: talks to KHU's site"),
    (r"^backend/requirements\.txt$|^backend/runtime\.txt$", "backend dependencies"),
    (r"(^|/)package(-lock)?\.json$", "frontend dependencies"),
    (r"(^|/)(admin|agent)\.html$", "admin and agent pages"),
    (r"(^|/)service-worker\.js$", "service worker runs on every visitor's device"),
    (r"(^|/)src/api\.js$", "decides which server the app talks to"),
    (r"(^|/)public/index\.html$", "page shell, loads scripts"),
    (r"^android/", "Play Store app settings"),
    (r"(^|/)\.gitignore$|(^|/)\.gitattributes$", "what git tracks"),
    (r"^(SECURITY|CONTRIBUTING)\.md$|^scripts/", "security docs and review tooling"),
]

# Added lines matching these are worth a second look.
RISKY_LINE = [
    (r"\beval\s*\(|new\s+Function\s*\(", "runs text as code"),
    (r"dangerouslySetInnerHTML|\.innerHTML\s*=|insertAdjacentHTML|document\.write", "writes raw HTML (script injection risk)"),
    (r"child_process|os\.system|subprocess|\bexec\s*\(|\bspawn\s*\(", "runs shell commands"),
    (r"curl[^|\n]*\|\s*(ba)?sh|wget[^|\n]*\|\s*(ba)?sh", "downloads and runs a script"),
    (r"\"(pre|post)?install\"\s*:|\"prepare\"\s*:", "package install hook (runs on npm install)"),
    (r"document\.cookie|localStorage|sessionStorage", "reads or writes browser storage (tokens live there)"),
    (r"sendBeacon|XMLHttpRequest|new\s+WebSocket|\bfetch\s*\(|axios\.", "network call: check where it sends data"),
    (r"allow_origins|ALLOWED_ORIGINS|Access-Control-Allow", "CORS policy"),
    (r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false", "turns off TLS checking"),
    (r"EDGE_KEY|ADMIN_TOKEN|ADMIN_PASSWORD|MPESA_[A-Z_]+|DATABASE_URL|BACKUP_S3_[A-Z_]+|VAPID_[A-Z_]+", "touches a secret name"),
    (r"\.\./|/etc/passwd|/proc/", "path traversal or system paths"),
    (r"atob\s*\(|b64decode|fromCharCode|\\x[0-9a-fA-F]{2}.*\\x[0-9a-fA-F]{2}", "decodes hidden text (obfuscation)"),
    (r"[A-Za-z0-9+/=_-]{80,}", "very long random-looking string (hidden payload or key)"),
    (r"[‪-‮⁦-⁩​-‍﻿]", "invisible or text-reordering characters (can hide code)"),
]

# Hosts the app already uses. Anything else in a code file gets flagged.
KNOWN_HOSTS = {
    "khu-live-app.vercel.app", "khu-backend.onrender.com", "khu-edge.geoduor.workers.dev",
    "challenges.cloudflare.com", "fonts.googleapis.com", "fonts.gstatic.com",
    "kenyahockeyunion.org", "www.kenyahockeyunion.org", "wa.me", "github.com",
    "www.w3.org", "localhost", "127.0.0.1", "example.com", "registry.npmjs.org",
    "developers.google.com", "play.google.com", "api.safaricom.co.ke",
    "sandbox.safaricom.co.ke",
}
URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")
DOC_EXT = (".md", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".pdf", ".svg", ".ico")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    head = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
    rng = f"{base}...{head}"

    status = [l.split("\t") for l in git("diff", "--name-status", rng).splitlines() if l]
    if not status:
        print(f"No changes between {base} and {head}.")
        return 0

    flagged = 0
    print(f"Reviewing {head} against {base}: {len(status)} file(s) changed\n")

    print("1. Files that need a careful read")
    for st, *paths in status:
        path = paths[-1]
        for pat, why in SENSITIVE_PATHS:
            if re.search(pat, path):
                print(f"   [{st}] {path}  <- {why}")
                flagged += 1
                break
    if not flagged:
        print("   none of the high-risk files were touched")

    print("\n2. Brand-new or removed files")
    for st, *paths in status:
        if st[0] in "ADR":
            print(f"   [{st}] {paths[-1]}")
    binaries = [l for l in git("diff", "--numstat", rng).splitlines() if l.startswith("-\t-\t")]
    for l in binaries:
        print(f"   binary file changed (cannot be read as text): {l.split(chr(9))[2]}")
        flagged += 1

    print("\n3. Added lines worth a second look")
    current, lineno, hits = None, 0, 0
    for raw in git("diff", "-U0", "--no-color", rng).splitlines():
        if raw.startswith("+++ "):
            current = raw[6:] if raw.startswith("+++ b/") else None
            continue
        m = re.match(r"^@@ -\S+ \+(\d+)", raw)
        if m:
            lineno = int(m.group(1))
            continue
        if not raw.startswith("+") or raw.startswith("+++") or not current:
            continue
        line = raw[1:]
        here = lineno
        lineno += 1
        if current.endswith("package-lock.json"):
            if '"resolved"' in line and "registry.npmjs.org" not in line:
                print(f"   {current}:{here}  dependency downloaded from outside the npm registry: {line.strip()[:100]}")
                hits += 1
            continue
        if current.endswith(DOC_EXT) or current.startswith("scripts/pr_risk_check"):
            continue
        for pat, why in RISKY_LINE:
            if re.search(pat, line):
                print(f"   {current}:{here}  {why}\n       {line.strip()[:110]}")
                hits += 1
                break
        for host in URL_RE.findall(line):
            if host not in KNOWN_HOSTS and not host.endswith((".example.com", ".w3.org")):
                print(f"   {current}:{here}  NEW outside address: {host}\n       {line.strip()[:110]}")
                hits += 1
    if not hits:
        print("   nothing matched")
    flagged += hits

    print("\n4. New dependencies")
    deps = 0
    for path in ("frontend/khu-frontend/package.json", "backend/requirements.txt"):
        try:
            before = git("show", f"{base}:{path}")
        except subprocess.CalledProcessError:
            before = ""
        try:
            after = git("show", f"{head}:{path}")
        except subprocess.CalledProcessError:
            continue
        old = set(re.findall(r'^\s*"?([A-Za-z0-9@/_.-]+)"?\s*(?:==|:)', before, re.M))
        new = set(re.findall(r'^\s*"?([A-Za-z0-9@/_.-]+)"?\s*(?:==|:)', after, re.M))
        for name in sorted(new - old - {"name", "version", "private", "scripts", "dependencies", "browserslist", "production", "development", "eslintConfig", "extends", "postinstall", "preinstall", "prepare", "start", "build", "test", "eject"}):
            print(f"   {path}: + {name}  (look it up on npm/PyPI: age, downloads, spelling close to a famous package?)")
            deps += 1
    if not deps:
        print("   none added")
    flagged += deps

    print("\nNext: read every changed file in the 'Files changed' tab, not only the description.")
    print("Review the branch with `npm ci --ignore-scripts` and no real secrets on the machine.")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
