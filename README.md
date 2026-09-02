# datenportal-dev-stack

Lokaler Docker-Compose-Stack für Entwicklung, Integrationstests und Demos des
Datenportals.

Der Stack integriert Garage als lokalen S3-kompatiblen Object Storage, den
Datenblatt-Editor als statische Webapp und Jenkins als Datenportal-/GRETL-
Integrationsumgebung. Die Images und Buildlogik der Komponenten werden in
ihren jeweiligen Projekten gepflegt; in diesem Repository liegen nur die
Orchestrierung und die dafür nötigen Integrationsdateien.

## Garage-S3

Der Stack startet eine persistente Single-Node-Garage-Instanz mit dem Bucket
`ch.so.daten`.

| Zweck | Adresse |
|---|---|
| S3 API vom Host aus | `http://localhost:3900` |
| S3 API aus einem Compose-Service | `http://garage:3900` |
| Öffentliche Objekt-Links | `http://localhost:8081/ch.so.daten/<objekt-key>` |
| Datenblatt-Editor | `http://localhost:8081/metadaten-editor/` |
| Jenkins | `http://localhost:8080/` |
| S3-Region | `garage` |

Die S3-API ist für GRETL, Gradle und lokale Werkzeuge mit den generierten
Dev-Zugangsdaten authentifiziert. Öffentliche Lesezugriffe erfolgen nur über
den HTTP-Downloadpfad. Es gibt keine anonymen Schreibzugriffe und keine
öffentliche S3-Bucket-Auflistung.

Der Caddy-Service vor Garage ist für den stabilen pfadbasierten HTTP-Endpunkt,
die Weiterleitung des Bucket-Hosts und CORS für Browser-Anfragen zuständig.
Garage selbst liefert die statischen Objekte über seinen Website-Endpunkt.

## Voraussetzungen

- Docker mit Docker Compose v2

Prüfen:

```bash
docker --version
docker compose version
```

## Starten

Die Initialisierung erzeugt einmalig lokale Zugangsdaten und Garage-Secrets
unter `.env` beziehungsweise `services/garage/garage.toml`. Beide Dateien
werden nicht versioniert.

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

`docker compose build` baut weiterhin keine Komponente in der Standardvariante,
weil Registry-Images verwendet werden. Der Jenkins-Local-Build wird bewusst
über das Buildscript des Jenkins-Dev-Repositories ausgeführt und nicht über ein
zweites Dockerfile in diesem Stack.

`garage-init` erstellt den Bucket, aktiviert den öffentlichen Website-Zugriff
mit `index.html` und `404.html` und setzt die CORS-Konfiguration. Der Dienst
ist absichtlich ein einmaliger Initialisierungscontainer und darf danach mit
Status `Exited (0)` erscheinen.

Ein erneuter Initialisierungslauf ist sicher und idempotent:

```bash
docker compose run --rm garage-init
```

Logs:

```bash
docker compose logs -f garage
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

## Öffentliche HTTP-Links

Nach einem Upload ist das Objekt ohne Zugangsdaten abrufbar:

```bash
curl -fS \
  http://localhost:8081/ch.so.daten/downloads/demo.csv \
  -o /tmp/demo-download.csv
```

Diesen URL-Aufbau kann die Webapp als normalen Link verwenden. Der Website-
Endpunkt unterstützt Lesen per GET und HEAD; Verzeichnisauflistungen sind nicht
vorgesehen. Der Bucket-Root funktioniert nur dann als Website, wenn ein
`index.html`-Objekt hochgeladen wurde.

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

Der Smoke-Test erzeugt ein temporäres Objekt, prüft authentifiziertes Schreiben
über die S3-API, anonymes Lesen über Caddy, HEAD und CORS und entfernt das
Testobjekt anschliessend wieder. Zusätzlich prüft er die Editor-Startseite und
die authentifizierte Jenkins-API:

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

Das gemeinsame Image enthält Jenkins mit Java 21, Java 17 für GRETL/Gradle,
Standard-Plugins, das Datenportal-Plugin und das beim Image-Bau erzeugte
GRETL-/Gradle-Offline-Bundle. Das Bundle lädt GRETL `5.0.0-SNAPSHOT` beim Bau
aus dem im Themenrepo festgelegten Repository und wird zur Laufzeit offline
verwendet. Das Plugin-HPI wird ebenfalls beim Image-Bau installiert, nicht
beim Containerstart.

Die produktive Betriebsart ist für eine spätere Deployment-Konfiguration mit
AD, externen Secrets und `managed-git` vorbereitet. Der lokale Stack enthält
bewusst keine produktiven AD-Werte und konfiguriert noch keine Jenkins-
S3-Credentials oder serverseitige Editor-Speicherung. Garage ist im Compose-
Netzwerk unter `http://garage:3900` erreichbar und kann später in einer
Deployment-Konfiguration als S3-Endpunkt verwendet werden.

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
