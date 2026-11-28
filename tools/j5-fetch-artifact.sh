#!/bin/sh
# Download a CI artifact with curl and resume (gh run download stalls on slow
# links and restarts from zero). Unpacks it flat into OUTDIR.
#
#   j5-fetch-artifact.sh RUN_ID OUTDIR [ARTIFACT_NAME]
set -eu
run=$1 out=$2 name=${3:-}
repo=TheXellix/ios-j5y17lte
mkdir -p "$out"
q='.artifacts[0].id'
[ -n "$name" ] && q=".artifacts[] | select(.name==\"$name\") | .id"
id=$(gh api "repos/$repo/actions/runs/$run/artifacts" -q "$q" | head -1)
[ -n "$id" ] || { echo "no artifact in run $run" >&2; exit 2; }
zip="$out.zip"
tok=$(gh auth token)
url=$(curl -sS -o /dev/null -w '%{redirect_url}' -H "Authorization: Bearer $tok" \
	"https://api.github.com/repos/$repo/actions/artifacts/$id/zip")
[ -n "$url" ] || { echo "no download URL" >&2; exit 2; }
i=0
until curl -sS -C - --speed-limit 1024 --speed-time 60 -o "$zip" "$url" && unzip -tq "$zip" >/dev/null 2>&1; do
	i=$((i + 1)); [ $i -lt 20 ] || { echo "download failed" >&2; exit 2; }
	echo "resume $i at $(stat -c %s "$zip") bytes" >&2; sleep 5
done
rm -rf "$out" && mkdir -p "$out"
unzip -q "$zip" -d "$out"
# Artifacts of one name may be nested in a directory of that name.
for d in "$out"/*/; do
	[ "$(ls "$out" | wc -l)" = 1 ] && [ -d "$d" ] && { mv "$d"* "$out"/ && rmdir "$d"; }
	break
done
rm -f "$zip"
echo "artifact $id -> $out"
