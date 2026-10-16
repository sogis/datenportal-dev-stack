# datenportal-dev-stack — Branch `s3-aws`

Dieser Branch betreibt vorübergehend nur **Sodata und APISIX**. Das Datenportal
liest den veröffentlichten Katalog, die DuckDB und die Datendownloads aus dem
AWS-Testbucket `ch.so.daten-test` in `eu-central-1`:

- [Publikationsmanifest](https://s3.eu-central-1.amazonaws.com/ch.so.daten-test/current.json)
- [Downloadbasis](https://s3.eu-central-1.amazonaws.com/ch.so.daten-test)

Garage, Initialisierung, S3-Browser, AWS-Hilfsdienst, Jenkins/GRETL,
Datenblatt-Editor und Dokumentation sind in Compose und ihren APISIX-Routen
vorübergehend auskommentiert. Die zugehörigen Build-Overrides sind ebenfalls
inaktiv. Dieser Branch publiziert keine Daten und ändert keine AWS-Objekte.

## Starten

Benötigt werden Docker mit Compose v2, Bash, Python 3 und Internetzugriff auf
Registry und AWS. Eine `.env`, AWS-Zugangsdaten und Schwester-Checkouts sind für
den Standardstart nicht erforderlich.

```bash
./scripts/up.sh
# Gleichwertig:
./scripts/up.sh --registry-only
```

Das Portal läuft unter [http://localhost:8081/](http://localhost:8081/).
APISIX bleibt als Dienst `downloads` aktiv, hat einen eigenen Netzwerkraum und
leitet nur das Portal weiter. `/admin`, `/actuator` und `/apisix/admin` bleiben
öffentlich gesperrt. Sodata veröffentlicht keinen direkten Hostport.

Der Start entfernt veraltete Container desselben Compose-Projekts, erhält aber
alle benannten Garage-/Jenkins-Volumes. Es gibt keinen Seed, keine
Erstpublikation und keinen automatischen lokalen Build-Fallback. Verwendet
werden `sogis/datenportal-sodata:0.1.20` und `apache/apisix:3.19.0-debian`.

Direkte Compose-Aufrufe funktionieren ebenfalls:

```bash
docker compose config --quiet
docker compose pull sodata downloads
docker compose up -d --remove-orphans --wait --wait-timeout 120
docker compose ps
./scripts/smoke-test.sh
```

## Konfiguration und lokale Builds

Optionale Einstellungen stehen in `.env.example`. Compose liest eine bestehende
ignorierte `.env`; exportierte Shellwerte haben Vorrang. Die Startskripte
überschreiben oder erzeugen keine `.env` und benötigen keine Garage-Secrets.
`GARAGE_PUBLIC_PORT` bleibt aus Kompatibilitätsgründen der Name für den
APISIX-Hostport und Listener (Default `8081`). Er hat keine Garage-Abhängigkeit.

`DATENPORTAL_CATALOG_HTTP_URL` überschreibt die Manifestadresse,
`DATENPORTAL_CATALOG_DOWNLOAD_URL` die öffentliche Downloadbasis einschliesslich
der für die CSP erlaubten Origin. XTF und DuckDB stammen gemeinsam aus dem
Manifest. DuckDB-Views müssen bereits auf die passenden Parquet-Adressen zeigen;
die Webapp schreibt sie nicht um. Daten werden beim Start oder einem expliziten
internen Reload neu gelesen, ohne automatisches Polling. Ein Neustart für den
aktuellen AWS-Stand:

```bash
docker compose restart sodata
```

Ohne optionalen `DATENPORTAL_PORTAL_RELOAD_TOKEN` bleiben interner Reload und
Adminstatus deaktiviert; der normale Portalstart benötigt keinen Token.
AWS-Schreibzugangsdaten werden nicht an die Container übergeben.

Für einen expliziten lokalen Portalbuild:

```bash
./scripts/up.sh --local-sodata
```

Dafür wird der Arbeitsstand von `../datenportal-sodata` verwendet, optional durch
`SODATA_REPO_DIR` in Umgebung oder `.env` überschreibbar. Dockerfile und Buildlogik
bleiben dort; nur das Portalimage wird lokal gebaut. `--registry-only` und
`--local-sodata` sind gegenseitig ausgeschlossen. `--local-editor`,
`--local-jenkins`, `--local-docs` und `--infrastructure-only` sind in diesem Branch
deaktiviert und brechen vor Docker-Aktionen mit einer Erklärung ab.

## Prüfen und Stoppen

```bash
python3 scripts/test-registry-start.py
python3 scripts/test-docs-start.py
./scripts/smoke-test.sh
./scripts/down.sh
```

Die Starttests laufen in temporären Checkouts mit echtem Compose, aber ohne
Containeränderungen. Der Smoke-Test führt nur GET/HEAD aus: Portal, Suche,
Detailseite, Erkunden-Kontext, AWS-Downloads, CORS/Range, Gateway-Sperren sowie
Gleichheit der Portal-XTF/DuckDB mit dem AWS-Manifest. Eine SQL-Abfrage im
Erkunden-Browser ist eine zusätzliche Live-Abnahme. Bei zwischenzeitlich
geändertem AWS-Release Sodata neu starten und den Smoke-Test wiederholen.
`down.sh` entfernt auch veraltete Projektcontainer und erhält die Volumes.

Die [lokalen Betriebsanleitungen](docs/biblios/index.adoc) kennzeichnen den
aktuellen AWS-Betrieb und den historischen Garage-Gesamtstack getrennt. Die
historischen Seed-, Publikations-, Jenkins-, Editor- und Dokumentationstests
sind in diesem Branch nicht anwendbar. `scripts/init.sh`, Bootstrap und
Lieferungshelfer gehören weiterhin ausschliesslich zum inaktiven Garage-Betrieb.

Die kanonischen Komponentenverträge bleiben in ihren Schwester-Repositories.
Der AWS-Anschluss erfordert keine Änderungen dort. Die Bucketangaben stammen
aus der bereitgestellten OpenShift-Vorlage `datenportal-stack/jenkins/jenkins.yaml`;
deren Deployment- und Jenkins-Anweisungen werden hier nicht übernommen.

Live geprüft am 16.10.2026 mit Sodata `0.1.20` und AWS-Release
`e4560849-cd01-4e19-ac09-11f5d3036fb1`: 23 sichtbare Katalogeinträge und eine
erfolgreiche SQL-Vorschau mit 23 Zeilen für `ch.so.ebau_statistik_dossiers`.
Compose-Konfiguration, Registry-Start, interne Readiness, 13 Starttests,
lesender Smoke-Test und `git diff --check` waren erfolgreich.
`docker compose build` hat im Registry-Betrieb keine Buildziele; der lokale
Native-Build wurde nicht ausgeführt. Als Vertragsreferenz wurde der saubere
Checkout `../datenportal-sodata` auf `main` bei `b14550c` gelesen und unverändert
belassen. Ausgangsstand des Dev-Stacks: `s3-aws` bei `915db87`.
