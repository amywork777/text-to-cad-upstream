#!/usr/bin/env bash
# studio-base's own (AGENTS.md, On studio-base): the files of Jake's text-to-cad that studio-base changes
# or removes, against the commit of Jake's it last merged, must be exactly the ones in
# scripts/studio-jake-edits.txt. A new one fails until a person adds it on purpose; one studio-base
# no longer changes fails until it comes off. So the list only shrinks unless someone decides
# otherwise, and a merge of Jake's release conflicts on no file the list doesn't name.
#
#     scripts/studio-jake-edits.sh          # check (CI)
#     scripts/studio-jake-edits.sh --write  # rewrite the list (after merging Jake, or a leak taken out)
#
# The list's header records the commit of Jake's it was taken against, so the check needs nothing of
# Jake's repository. --write takes the newest commit of Jake's that studio-base has merged, from
# JAKE_REF (default jake/main; `git fetch jake main` first).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
LIST=scripts/studio-jake-edits.txt

if [ "${1:-}" = "--write" ]; then
  base="$(git merge-base HEAD "${JAKE_REF:-jake/main}")"
else
  base="$(sed -n 's/^# Jake base: \([0-9a-f]\{40\}\)$/\1/p' "$LIST")"
  if [ -z "$base" ] || ! git merge-base --is-ancestor "$base" HEAD; then
    echo "::error::$LIST names no commit of Jake's that studio-base has merged. Run scripts/studio-jake-edits.sh --write."
    exit 1
  fi
fi
edits="$(git diff --name-only --no-renames --diff-filter=MD "$base" HEAD | sort)"

if [ "${1:-}" = "--write" ]; then
  {
    echo "# Jake's files that studio-base changes or removes (AGENTS.md, On studio-base). Checked by"
    echo "# scripts/studio-jake-edits.sh; add a line only on purpose, and take one off when its change"
    echo "# moves into Studio's own files or lands in Jake's repository."
    echo "# Jake base: $base"
    printf '%s\n' "$edits"
  } >"$LIST"
  echo "Wrote $(printf '%s\n' "$edits" | grep -c .) files to $LIST (Jake ${base:0:12})."
  exit 0
fi

listed="$(grep -v -e '^#' -e '^$' "$LIST" | sort)"
added="$(comm -23 <(printf '%s\n' "$edits") <(printf '%s\n' "$listed") | sed '/^$/d')"
gone="$(comm -13 <(printf '%s\n' "$edits") <(printf '%s\n' "$listed") | sed '/^$/d')"
status=0
if [ -n "$added" ]; then
  echo "::error::studio-base now changes files of Jake's the list doesn't name. Move the change into Studio's own files (AGENTS.md, On studio-base), or add them to $LIST on purpose. Just merged Jake? Run scripts/studio-jake-edits.sh --write:"
  printf '  %s\n' $added
  status=1
fi
if [ -n "$gone" ]; then
  echo "::error::studio-base no longer changes these files of Jake's, so take them off $LIST:"
  printf '  %s\n' $gone
  status=1
fi
[ "$status" -ne 0 ] || echo "studio-base changes the $(printf '%s\n' "$listed" | grep -c .) files of Jake's that $LIST names, against Jake ${base:0:12}."
exit "$status"
