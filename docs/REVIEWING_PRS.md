# Reviewing a contributor's pull request

Branch protection stops anyone changing `main` without your approval. That
makes **you** the last line of defence: a change that looks helpful but hides
something is the one realistic way to take over this project. This page is the
routine for approving safely.

## The rule

**If you don't understand a change, don't approve it.** Ask him to explain it
or split it up. A pull request that is hard to read is a reason to say no.

## Before you open the code

1. Read his description. Does it match what the change really does?
2. Run the risk check. It only reads the diff and runs nothing from his branch:

   ```bash
   git fetch origin
   python3 scripts/pr_risk_check.py origin/main origin/his-branch-name
   ```

   It lists the sensitive files touched, new outside web addresses, new
   dependencies, install hooks, hidden or invisible characters, and code that
   runs text as code. A flag is a question, not a verdict.
3. Open the **Files changed** tab and read every file. Don't rely on the
   summary. Look at commits one by one if the pull request is large.

## Red flags: stop and ask

| You see | Why it matters |
| --- | --- |
| Any change in `.github/`, `render.yaml`, `vercel.json`, `edge/`, `android/` | Controls who can change the repo, how servers start, the security headers, and the Play Store app |
| `frontend/khu-frontend/src/api.js`, `public/index.html`, `service-worker.js` | Decides which server visitors talk to and what code runs on their phones |
| `backend/mpesa.py`, `shop.py`, `main.py`, `database.py`, `backup.py` | Money, logins, data and backups |
| `admin.html`, `agent.html` | Pages that hold admin and agent logins |
| A new package in `package.json` or `requirements.txt` | Look it up first: age, weekly downloads, spelling close to a famous name (typosquatting) |
| `postinstall`, `preinstall`, `prepare` in `package.json` | Runs code on every machine and on Vercel when installing |
| A web address you don't recognise | Possible place to send stolen data |
| `eval`, `new Function`, `innerHTML`, `dangerouslySetInnerHTML` | Lets text turn into running code |
| Long random-looking strings, `atob`, `base64` | Hidden payloads |
| A change to `.gitignore` | Could stop a leaked file from being ignored |
| `verify=False`, a wider CORS list, `"*"` | Weakens protections |
| A pull request that mixes a small fix with unrelated changes | Common way to hide a bad line |

## Reviewing his branch on your computer (only when needed)

Installing a package can run code. So:

```bash
cd frontend/khu-frontend
npm ci --ignore-scripts        # do not run package install hooks
```

- Do it on a machine or sandbox that has **no real passwords, keys or `.env`
  files** (use sandbox values only).
- Never run his backend with the real `DATABASE_URL`, `MPESA_*` or `EDGE_KEY`.

## Approving

- Approve only when the whole diff is understood and matches the description.
- If he pushes more commits after your approval, the approval is dropped
  automatically (the ruleset dismisses stale approvals). Read the new commits.
- Merge with "Squash and merge" so history stays readable.
- After merging, watch the first deploy and open `/api/health`.

## If something looks wrong after the fact

1. Revert the merge commit on a new branch and open a pull request.
2. Remove him under Settings → Collaborators.
3. Rotate any secret he could have seen (Render env vars, Cloudflare Worker
   secrets, M-Pesa keys, the admin password).
4. Tell me what you found and I'll audit the damage.
