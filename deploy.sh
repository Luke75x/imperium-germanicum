#!/bin/bash
# Baut die Seite und spielt sie nach /var/www/imperium (Apache-DocumentRoot) ein.
set -euo pipefail
cd "$(dirname "$0")"
python3 _build/site.py
rsync -a --exclude=.git --exclude=_build --exclude=README.md --exclude=.gitignore --exclude=deploy.sh ./ /var/www/imperium/
chown -R www-data:www-data /var/www/imperium
echo "Deploy fertig."
