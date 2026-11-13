#!/usr/bin/env bash
# Post a PR comment, or edit the one already there.
#
#   upsert_pr_comment.sh <pr-number> <body-file>
#
# The body's first line is its marker (an HTML comment, see pr_report.py): a
# comment starting with the same line is edited in place, so each report stays
# a single comment across pushes. Needs GH_TOKEN (pull-requests: write) and
# GITHUB_REPOSITORY.
set -euo pipefail

pr="$1"
body="$2"
marker="$(head -n 1 "$body")"

existing="$(
  gh api "repos/${GITHUB_REPOSITORY}/issues/${pr}/comments" --paginate \
    --jq ".[] | select(.body | startswith(\"${marker}\")) | .id" | head -n 1
)"

if [ -n "$existing" ]; then
  gh api -X PATCH "repos/${GITHUB_REPOSITORY}/issues/comments/${existing}" -F "body=@${body}" --silent
else
  gh api -X POST "repos/${GITHUB_REPOSITORY}/issues/${pr}/comments" -F "body=@${body}" --silent
fi
