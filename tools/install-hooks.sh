#!/usr/bin/env bash
# Install git hooks: pre-commit (staged secrets, then ./check.sh), commit-msg
# (message format) and pre-push (branch naming). Rules: CONTRIBUTING.md.
set -euo pipefail
here=$(dirname "$0")
# --git-path: in a linked worktree .git is a file; hooks live in the main checkout's .git.
hooks=$(cd "$here" && cd "$(git rev-parse --git-path hooks)" && pwd)

cat > "$hooks/pre-commit" <<'HOOK'
#!/usr/bin/env bash
# check.sh scans staged changes for secrets first (gitleaks --staged), then runs every check.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
exec "$root/check.sh"
HOOK

cat > "$hooks/commit-msg" <<'HOOK'
#!/usr/bin/env bash
# <type>(#<issue>) - <description>; merge and revert commits made by git are allowed.
msg=$(head -1 "$1")
if [[ $msg =~ ^(feat|refactor|fix|chore|test)\(#[0-9]+\)\ -\ [^[:space:]].* ]] || [[ $msg =~ ^(Merge|Revert)\  ]]; then exit 0; fi
echo "commit blocked: message must look like 'feat(#12) - add sample intake form'" >&2
echo "types: feat, refactor, fix, chore, test (see CONTRIBUTING.md)" >&2
exit 1
HOOK

cat > "$hooks/pre-push" <<'HOOK'
#!/usr/bin/env bash
# Only pushes of correctly named branches; main and develop change through pull requests.
pattern='^(feature|fix|hotfix)/#[0-9]+-[a-z0-9]+(-[a-z0-9]+)*$|^release/[0-9]+\.[0-9]+\.[0-9]+$'
while read -r local_ref _ remote_ref _; do
  branch=${remote_ref#refs/heads/}
  [[ $remote_ref == refs/heads/* ]] || continue
  if [[ $branch == main || $branch == develop ]]; then
    echo "push blocked: $branch changes only through pull requests" >&2; exit 1
  fi
  if ! [[ $branch =~ $pattern ]]; then
    echo "push blocked: branch '$branch' must be feature|fix|hotfix/#<issue>-<description> or release/<x.y.z>" >&2; exit 1
  fi
done
exit 0
HOOK

chmod +x "$hooks/pre-commit" "$hooks/commit-msg" "$hooks/pre-push"
echo "hooks installed: pre-commit, commit-msg, pre-push"
