# datenportal-dev-stack

Lokaler Docker-Compose-Stack für Entwicklung, Integrationstests und Demos des
Datenportals.

Der Stack integriert Garage als lokalen S3-kompatiblen Object Storage, einen
anonymen Read-only-Browser für den öffentlichen Bucket, den Datenblatt-Editor
als statische Webapp und Jenkins als Datenportal-/GRETL-Integrationsumgebung.
Die Images und Buildlogik der Komponenten werden in ihren jeweiligen Projekten
gepflegt; in diesem Repository liegen nur die Orchestrierung und die dafür
nötigen Integrationsdateien.

## Garage-S3

Der Stack startet eine persistente Single-Node-Garage-Instanz mit dem Bucket
`ch.so.daten`.

| Zweck | Adresse |
|---|---|
| S3 API vom Host aus | `http://localhost:3900` |
| S3 API aus einem Compose-Service | `http://garage:3900` |
| Öffentlicher Bucket-Browser | `http://localhost:8081/ch.so.daten/` |
| Öffentliche Objekt-Links | `http://localhost:8081/ch.so.daten/<objekt-key>` |
| Datenblatt-Editor | `http://localhost:8081/metadaten-editor/` |
| Jenkins | `http://localhost:8080/` |
| S3-Region | `garage` |

Die S3-API ist für GRETL, Gradle und lokale Werkzeuge mit den generierten
Dev-Zugangsdaten authentifiziert. Öffentliche Lesezugriffe und die navigierbare
Verzeichnisansicht erfolgen nur über den HTTP-Pfad für den explizit als Website
freigegebenen Bucket. Es gibt keine anonymen Schreibzugriffe und keine
Auflistung privater Buckets.

Der Caddy-Service stellt den stabilen pfadbasierten HTTP-Endpunkt und CORS für
Browser-Anfragen bereit. Vor jedem Bucket-Zugriff prüft er über Garages
`/check`-Endpunkt, ob der Website-Zugriff weiterhin aktiviert ist. Der
`s3-browser`-Service verwendet `rclone serve http`, ist auf `ch.so.daten`
begrenzt und arbeitet mit einem eigenen Garage-Schlüssel, der nur Leserechte
besitzt. Weder rclone noch die Garage-Admin-API werden direkt auf einem
Host-Port veröffentlicht.

## Voraussetzungen

- Docker mit Docker Compose v2

Prüfen:

```bash
docker --version
docker compose version
```

## Starten

Die Initialisierung erzeugt einmalig lokale Schreib- und Browser-Zugangsdaten
sowie Garage-Secrets unter `.env` beziehungsweise
`services/garage/garage.toml`. Beide Dateien werden nicht versioniert.

```bash
./scripts/init.sh
docker compose config --quiet
docker compose build
./scripts/up.sh
docker compose ps
```

`docker compose build` meldet in der Standardvariante `No services to build`,
weil das Registry-Image des Editors verwendet wird und die übrigen Services
fertige Upstream-Images nutzen. Für einen lokalen Build des Editors aus dem
Geschwister-Repository:

```bash
./scripts/up.sh --local-editor
```

Das entspricht explizit:

```bash
docker compose -f compose.yaml -f compose.editor-local.yaml \
  build datenblatt-editor
```

Jenkins wird standardmässig aus dem versionierten Registry-Image gestartet.
Wenn der konfigurierte Registry-Tag noch nicht existiert, baut `up.sh` nur bei
einem eindeutig als `Not Found` erkannten Pull-Fehler automatisch das lokale
Image aus `../datenportal-jenkins-dev` (bei erneutem Start wird ein vorhandenes
`datenportal-jenkins:local` wiederverwendet). Ein Pull- oder Berechtigungsfehler
wird nicht als fehlendes Image behandelt. Für einen expliziten lokalen
Jenkins-Build:

```bash
./scripts/up.sh --local-jenkins
```

Der lokale Build verwendet mit `PLUGIN_SOURCE=auto` den lokalen Checkout von
`../datenportal-jenkins-gretl-plugin`; alternativ kann in `.env` oder der
Build-Umgebung `PLUGIN_SOURCE=maven` gesetzt werden. Die Maven-Auflösung nutzt
standardmässig `https://jars.interlis.guru/snapshots`. Mit
`--registry-only` ist kein lokaler Fallback erlaubt:

```bash
./scripts/up.sh --registry-only
./scripts/up.sh --local-editor --local-jenkins
```

Bei `--local-jenkins` wird die Plugin-HPI nach dem Image-Build zusätzlich in
das persistente Compose-Volume `jenkins-home` synchronisiert. Anschliessend
wird nur der Jenkins-Service neu erzeugt, damit auch bereits geladene Jelly-
Views aktualisiert werden. Jobs und Build-Historien im Volume bleiben dabei
erhalten; ein `docker compose down -v` ist für diesen Update-Loop nicht nötig.

`docker compose build` baut weiterhin keine Komponente in der Standardvariante,
weil Registry-Images verwendet werden. Der Jenkins-Local-Build wird bewusst
über das Buildscript des Jenkins-Dev-Repositories ausgeführt und nicht über ein
zweites Dockerfile in diesem Stack.

`garage-init` erstellt den Bucket, aktiviert den öffentlichen Website-Zugriff
mit `index.html` und `404.html` und setzt die CORS-Konfiguration. Der Dienst
ist absichtlich ein einmaliger Initialisierungscontainer und darf danach mit
Status `Exited (0)` erscheinen.

`up.sh` importiert zusätzlich den lokal erzeugten Browser-Schlüssel
idempotent in Garage. Es entzieht ihm Create-, Write- und Owner-Rechte und
gewährt ausschliesslich Read auf `ch.so.daten`.

Ein erneuter Initialisierungslauf ist sicher und idempotent:

```bash
docker compose run --rm garage-init
```

Logs:

```bash
docker compose logs -f garage
docker compose logs -f s3-browser
docker compose logs -f downloads
docker compose logs -f datenblatt-editor
docker compose logs -f jenkins
```

## S3 verwenden

Die Zugangsdaten werden beim ersten Lauf in `.env` erzeugt. Für ein lokal auf
dem Host ausgeführtes AWS-CLI oder GRETL können sie in die aktuelle Shell
geladen werden:

```bash
set -a
. ./.env
set +a

export AWS_ENDPOINT_URL="http://localhost:${GARAGE_S3_PORT:-3900}"
export AWS_DEFAULT_REGION=garage
export AWS_ACCESS_KEY_ID="$GARAGE_DEFAULT_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$GARAGE_DEFAULT_SECRET_KEY"
export AWS_EC2_METADATA_DISABLED=true
```

Beispiel für einen authentifizierten Upload:

```bash
aws s3 cp ./build/data/demo.csv \
  s3://ch.so.daten/downloads/demo.csv
```

Der gleiche Upload kann ohne lokal installiertes AWS-CLI über den optionalen
Hilfsservice erfolgen:

```bash
docker compose --profile tools run --rm \
  -v "$(realpath ./build/data/demo.csv):/tmp/demo.csv:ro" \
  aws s3 cp /tmp/demo.csv s3://ch.so.daten/downloads/demo.csv
```

## Öffentlicher Bucket-Browser und HTTP-Links

Der Bucket-Root zeigt ohne Anmeldung eine Verzeichnisliste mit Ordnernavigation
und Downloadlinks:

```text
http://localhost:8081/ch.so.daten/
```

Nach einem Upload ist das Objekt ohne Zugangsdaten abrufbar:

```bash
curl -fS \
  http://localhost:8081/ch.so.daten/downloads/demo.csv \
  -o /tmp/demo-download.csv
```

Diesen URL-Aufbau kann die Webapp weiterhin als normalen Link verwenden. Der
Browser unterstützt ausschliesslich Lesen per GET und HEAD. Änderungen aus
Jenkins, GRETL oder dem AWS-CLI erscheinen ohne zusätzlichen rclone-Verzeichniscache.

Garage aktiviert den öffentlichen Zugriff weiterhin auf Bucket-Ebene. Wird
der Website-Zugriff für `ch.so.daten` deaktiviert, blockiert Caddy sowohl die
Verzeichnisansicht als auch direkte Objekt-Links. Der Bucket-Root liefert nun
immer die Verzeichnisansicht; ein vorhandenes `index.html` wird als normale
Datei angezeigt und nicht automatisch als Startseite ausgeliefert.

Ein administratives Dashboard wie `garage-ui` wird bewusst nicht öffentlich
eingebunden: Es benötigt den Garage-Admin-Token und besitzt damit deutlich
weitergehende Rechte als die anonyme Verzeichnisansicht.

## Datenblatt-Editor

Der Editor ist eine rein clientseitige, offlinefähige SPA. Er besitzt in dieser
Stack-Phase kein Backend und schreibt weder nach Garage noch in eine andere
serverseitige Persistenz. Entwürfe werden im Browser in IndexedDB gespeichert;
XTF-Dateien werden lokal importiert und exportiert.

Caddy entfernt den öffentlichen Prefix vor der Weiterleitung an den Container
und setzt `X-Forwarded-Prefix: /metadaten-editor`. Das Editor-Image liefert
intern weiterhin Root-Pfade aus und erzeugt daraus den passenden HTML-Base-Pfad.
Dadurch funktionieren Startseite, Vue-Router-Deep-Links, Assets und die
gebündelten XTF-Quelldateien unter dem öffentlichen Prefix.

Schnellprüfung:

```bash
curl -fS http://localhost:8081/metadaten-editor/
curl -fS http://localhost:8081/metadaten-editor/draft/example
curl -fSI http://localhost:8081/metadaten-editor/mock-sources/dataset.index.xtf
```

Der vollständige HTTP-Test ist im gemeinsamen Smoke-Test enthalten:

```bash
./scripts/smoke-test.sh
```

## Smoke-Test

Der Smoke-Test erzeugt ein temporäres Objekt und prüft authentifiziertes
Schreiben, die Read-only-Rechte des Browser-Schlüssels, die anonyme
Verzeichnisansicht und direkte Downloads sowie HEAD und CORS. Er deaktiviert
den Website-Zugriff kurzzeitig, prüft die Caddy-Sperre und stellt die Freigabe
auch bei einem Fehler über den Cleanup wieder her. Zusätzlich prüft er die
Editor-Startseite und die authentifizierte Jenkins-API:

```bash
./scripts/smoke-test.sh
```

## Jenkins

Das Compose-Service heisst `jenkins` und veröffentlicht lokal Port `8080`.
Das Image ist in Dev und Produktion dasselbe; der Laufzeitunterschied wird über
`JENKINS_RUNTIME_MODE` und die externe Konfiguration bestimmt. Der Dev-Stack
setzt den Modus auf `dev`, mountet die lokale JCasC aus
`../datenportal-jenkins-dev/casc/jenkins.yaml` read-only und stellt das lokale
Themenrepo unter `/workspace/themenrepo` als read-only `working-tree`-Snapshot
bereit. Das Jenkins-Home liegt in `jenkins-home`.

Die [zentrale Jenkins-Konfigurationsreferenz](https://codeberg.org/edigonzales/datenportal-jenkins-dev/src/branch/main/docs/biblios/entwicklung/referenz-konfiguration.adoc)
erklärt ENV-Variablen, Git-Schreibfreigabe und die Unterschiede zum Shellstart
und Produktionsimage. Compose setzt hier `JENKINS_RUNTIME_MODE=dev`,
`THEMEN_REPO_MODE=working-tree`, `THEMEN_REPO_URL=""`,
`THEMEN_REPO_PATH=/workspace/themenrepo` sowie `CASC_JENKINS_CONFIG` fest.
Die Modusvariable allein wählt keine JCasC-Datei aus. Gleichnamige Einträge
in `.env` überschreiben diese festen Compose-Werte nicht; dafür wäre eine
explizite Änderung beziehungsweise Compose-Override-Konfiguration erforderlich.
`THEMEN_REPO_BRANCH` ist dagegen mit Default `main` interpoliert, wechselt
im Snapshot-Modus aber keinen lokalen Branch.

Nach Änderungen an Container-ENV oder Mounts muss der Service neu erstellt
werden; `docker compose restart` reicht dafür nicht. Nach Änderungen am
lokalen Themenrepo genügt ein erneuter Seeder-Lauf. Jeder Job arbeitet auf einer eigenen Kopie dieses Snapshots. Eine reine
Vorschau verändert den gemeinsamen Stand nicht; ein publizierender Job führt
dagegen die Gesamtdateien auf Garage als Eingang des nächsten Jobs weiter. Git-Rückschreiben bleibt im `working-tree`-Modus
ausgeschlossen. Der gemeinsame Lock serialisiert derzeit den gesamten Lieferablauf.

Das gemeinsame Image enthält Jenkins mit Java 21, Java 17 für GRETL/Gradle,
Standard-Plugins, das Datenportal-Plugin und das beim Image-Bau erzeugte
GRETL-/Gradle-Offline-Bundle. Das Bundle lädt GRETL `5.0.0-SNAPSHOT` beim Bau
aus dem im Themenrepo festgelegten Repository und wird zur Laufzeit offline
verwendet. Das Plugin-HPI wird ebenfalls beim Image-Bau installiert, nicht
beim Containerstart.

Die produktive Betriebsart ist für eine spätere Deployment-Konfiguration mit
AD, externen Secrets und `managed-git` vorbereitet. Der lokale Stack enthält
bewusst keine produktiven AD-Werte und keine produktiven Jenkins-S3-Credentials
oder serverseitige Editor-Speicherung. Für GRETL werden die
S3-Properties im Jenkins-Container zentral als `ORG_GRADLE_PROJECT_*`
Umgebungsvariablen gesetzt. Dadurch sind sie in jedem Gradle-Build als normale
Properties wie `findProperty('s3Endpoint')` verfügbar. Garage ist im Compose-
Netzwerk unter `http://garage:3900` erreichbar und kann später in einer
Deployment-Konfiguration durch einen produktiven S3-Endpunkt ersetzt werden.

Die Werte `DATENPORTAL_S3_ENDPOINT`, `DATENPORTAL_S3_REGION`,
`DATENPORTAL_S3_BUCKET` und `DATENPORTAL_S3_ACL` können lokal über `.env`
überschrieben werden. Access Key und Secret Key werden aus den lokal erzeugten
Garage-Credentials übernommen und nicht versioniert.

Jenkins-Healthcheck und Stack-Status:

```bash
docker compose ps jenkins
curl -fS http://localhost:8080/login -o /dev/null
```

## Stoppen und Zurücksetzen

Normales Stoppen behält die Garage-Daten in Docker-Volumes:

```bash
./scripts/down.sh
```

Das folgende Kommando ist destruktiv und löscht auch die persistenten Garage-
Volumes:

```bash
docker compose down -v
```

Danach kann mit `./scripts/init.sh` und `./scripts/up.sh` eine neue lokale
Instanz aufgebaut werden.

## Weiterführende Stack-Integration

Komponenten, die später in diesem Compose laufen, verwenden als S3-Endpunkt
`http://garage:3900`. Anwendungen, die auf dem Host laufen, verwenden
`http://localhost:3900`. Das GRETL-/Gradle-Schreibkonto ist lokal und darf
nicht in Themenrepo, Jenkins-Konfiguration oder versionierter Dokumentation
übernommen werden. Der Datenblatt-Editor verwendet aktuell keine S3-
Zugangsdaten. Jenkins verwendet im Dev-Stack ebenfalls nur die gemountete
lokale Testkonfiguration; produktive S3-Credentials bleiben externe
Deployment-Konfiguration. Der Datenblatt-Editor verwendet aktuell keine S3-
Zugangsdaten und hat keinen serverseitigen Speicherpfad.

## Gesamt-XTF publizieren

Compose setzt `ORG_GRADLE_PROJECT_s3Publish=true` für die lokale Garage.
`DATENPORTAL_S3_PUBLISH=false` schaltet auf Vorschau. Der Eingangsverweis liegt
intern unter `http://downloads:8081/ch.so.daten/current.json`; dies lässt sich mit
`DATENPORTAL_PUBLICATION_MANIFEST_URL` überschreiben. Öffentliche Distributionen
verwenden `http://localhost:<GARAGE_PUBLIC_PORT>/ch.so.daten`. HTTP-Downloads
laufen ohne Gradles `--offline`; Abhängigkeiten bleiben im Offline-Bundle.

Vor dem ersten Standardjob muss der administrative Root-Task
`initializePublication` des Themenrepos bei pausierten Lieferjobs ausgeführt
werden. Der [Themenrepo-Vertrag](https://codeberg.org/edigonzales/datenportal-themenrepo/src/branch/main/docs/biblios/entwicklung/lieferverarbeitung.adoc)
erklärt Aufruf und Migration. Er publiziert bei fehlenden Daten zunächst
`catalog: null` und verweigert einen bereits vorhandenen Verweis.

Das Formular bietet Lieferung mit Upload oder gezielten Repository-Abgleich
ohne Datei. Ein Seeder-Lauf aktualisiert Formularparameter und Jenkinsfile.
`DATENPORTAL_PORTAL_RELOAD_URL` und das externe Secret
`DATENPORTAL_PORTAL_RELOAD_TOKEN` ermöglichen einen pro Lauf wählbaren Reload;
standardmässig sind beide leer. Das Portal wird weiterhin über seinen eigenen
lokalen Startvertrag betrieben, nicht als zusätzlicher Compose-Service.

Der lokale Editor-Build setzt `VITE_METADATA_SOURCE_URL=/ch.so.daten/current.json`.
Beim unveränderten Registry-Image kann die Manifestadresse im Quellendialog
angegeben werden, sobald das Image diese Funktion enthält. Caddy liefert
Bucket-Inhalte ohne dauerhaften Cache; rclone verwendet `--dir-cache-time 0s`.
Nach Änderungen an der gemounteten Caddy-Konfiguration wird diese mit
`docker compose exec downloads caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile`
neu geladen; ein unveränderter Container übernimmt Dateiedits nicht durch `up -d`.

Für die isolierte S3-/Git-Abnahme:

```bash
python3 scripts/test-publication.py
```

Der Test erstellt eine eigene Garage, einen öffentlichen Lesedienst und einen
Testproxy zur Fehlerauslösung. Alle Container und das Testnetz werden danach
entfernt; Testberichte und ein lokales Bare-Repository bleiben im ausgegebenen
temporären Verzeichnis. Laufende Stack-Volumes und Zugangsdaten bleiben unberührt.

Der Portal-Test startet die bestehende lokale `bootRun`-Konfiguration gegen eine
isolierte HTTP-Quelle und prüft den leeren Anfangsstand, Reload und Fehlererhalt:

```bash
python3 scripts/test-portal-manifest.py
```

Nach Plugin-Installation und Seeder prüft der lokale Formular-Browsertest beide
Modi, die bedingte Ausgabe und das Leeren der Uploadfelder. Er startet keinen
Lieferjob und verwendet Playwright aus dem Editor-Repository:

```bash
node scripts/test-jenkins-form.mjs
```

Er verwendet standardmässig den lokalen Zugang `admin`/`admin` auf Port 8080;
abweichende lokale Werte kommen aus `JENKINS_TEST_URL`, `JENKINS_TEST_USER` und
`JENKINS_TEST_PASSWORD`.
