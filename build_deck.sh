#!/bin/sh
# Build COGNAV4_TECHNICAL_REVIEW.md into a PowerPoint deck.
#
# PATH A — preferred. Renders the 13 slides as authored, with the black-and-
# white styling in the file's YAML front matter:
#
#     npm install -g @marp-team/marp-cli
#     marp COGNAV4_TECHNICAL_REVIEW.md -o COGNAV4_TECHNICAL_REVIEW.pptx
#
# PATH B — this script. Uses pandoc, which needs no network install, but is a
# rough fallback, not an equivalent:
#   * Styling is lost; you get pandoc's default template.
#   * Pandoc's pptx writer starts a new slide for any block that follows a
#     table. Most slides here put a closing remark after their table, so the
#     13 authored slides come out as ~24. Content is complete but the pagination
#     is not what was designed. Merge the stragglers by hand, or use Path A.
# The YAML front matter and the "---" slide separators are stripped below,
# because pandoc would otherwise render them as an extra blank slide each.
set -e
SRC="${1:-COGNAV4_TECHNICAL_REVIEW.md}"
OUT="${2:-COGNAV4_TECHNICAL_REVIEW.pptx}"
awk 'NR==1 && $0=="---" {fm=1; next} fm && $0=="---" {fm=0; next} fm {next} $0=="---" {next} {print}' "$SRC" \
  | pandoc -f markdown -t pptx --slide-level=1 -o "$OUT"
echo "wrote $OUT"
