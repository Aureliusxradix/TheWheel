#!/bin/sh
# Put the built, gated shell (dist/thewheel, from site/build.sh) into the site repo as /thewheel/.
#
#   site/build.sh && site/to-site.sh      then, in the site repo: ./deploy.sh --dry-run, commit, ./deploy.sh
#
# The site gives every page one JSON-LD graph (WebSite + Organization) from its own layout, and its discovery gate
# refuses a page without one. So index.html becomes src/thewheel.njk: the shell's HTML passed through untouched
# ({% raw %}), with the site's graph added before </head>. In the sitemap and llms.txt since his ruling 2026-10-20
# ("Let search find it"). Everything else (app.js, style.css, vendor/) is copied as is (passthrough).
set -eu
cd "$(dirname "$0")/.."
SITE="${WHEEL_SITE_REPO:-$HOME/Projects/aureliusxradix}"
[ -f dist/thewheel/index.html ] || { echo "no dist/thewheel; run site/build.sh first" >&2; exit 2; }
grep -q '<meta name="description"' dist/thewheel/index.html || { echo "REFUSED: the shell has no description" >&2; exit 3; }
rm -rf "$SITE/src/thewheel"; mkdir -p "$SITE/src/thewheel"
cp -r dist/thewheel/app.js dist/thewheel/style.css dist/thewheel/vendor "$SITE/src/thewheel/"
/usr/bin/python3 -E -s - "$SITE/src/thewheel.njk" <<'PY'
import sys
html = open("dist/thewheel/index.html").read()
head, rest = html.split("</head>", 1)
assert "{% endraw %}" not in html
ld = ('<script type="application/ld+json">{{ { url: page.url, title: title, description: description, site: site, '
      'assets: assets } | jsonld | safe }}</script>\n')
import re
desc = re.search(r'<meta name="description" content="([^"]+)"', html).group(1)
front = ("---\npermalink: /thewheel/\ntitle: The Wheel\ndescription: \"" + desc + "\"\n---\n"
         "{#- /thewheel/ — written by The Wheel's site/to-site.sh from its gated shell. Do not edit here. -#}\n")
open(sys.argv[1], "w").write(front + "{% raw %}" + head + "{% endraw %}" + ld + "{% raw %}</head>" + rest + "{% endraw %}")
PY
echo "into $SITE: src/thewheel.njk + src/thewheel/ ($(find "$SITE/src/thewheel" -type f | wc -l) files)"
