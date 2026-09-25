# datenportal-dev-stack

Lokaler Integrationsstack für Entwicklung, Tests und Demos: Garage-S3,
APISIX für öffentliche Downloads und Editor, Datenblatt-Editor, Portal und
Jenkins/GRETL. Die Komponenten und ihre Buildlogik bleiben in den jeweiligen
Schwester-Repositories.

Für den empfohlenen Entwicklungsweg werden Docker mit Compose v2, Bash,
OpenSSL, Git, rsync, Python 3, Maven sowie Java 17 und Java 21 benötigt. Die benötigten Checkouts und Java-Einstellungen stehen unter
[Voraussetzungen und Start](docs/biblios/start.adoc).

Aus dem Stack-Repository:

```bash
./scripts/up.sh --local-editor --local-jenkins --local-sodata
```

Das baut die lokalen Komponenten, installiert das Plugin im Jenkins-Volume
und startet die Dienste. Anschliessend folgen **Seeder und administrativer
Initialaufbau** gemäss [Inbetriebnahme](docs/biblios/inbetriebnahme.adoc).
Ein gestarteter Container allein ist noch kein publizierbarer Datenbestand.
Das Portal benötigt eine gültige `current.json`; `up.sh` startet Sodata bei
HTTP 404 oder einem Altmanifest ohne DuckDB deshalb noch nicht und gibt den späteren Startbefehl aus.

| Dienst | Standardadresse vom Host/Browser |
|---|---|
| Jenkins, lokal `admin` / `admin` | http://localhost:8080/gretl-datenportal/ |
| Öffentlicher Bucket | http://localhost:8081/ch.so.daten/ |
| RDF-Export nach erfolgreicher Publikation | http://localhost:8081/ch.so.daten/opendata.rdf |
| Gültiger Gesamtstand nach Initialisierung | http://localhost:8081/ch.so.daten/current.json |
| Editor | http://localhost:8081/metadaten-editor/ |
| Portal | http://localhost:8082/ |
| Authentifizierte S3-API | http://localhost:3900 |

Die vollständige [Entwicklungsdokumentation](docs/biblios/index.adoc)
führt durch:

- [Voraussetzungen, Startoptionen und Images](docs/biblios/start.adoc)
- [Initialisierung, Lieferungen, Vorschau und Portal-Anschluss](docs/biblios/inbetriebnahme.adoc)
- [Parameter, Prioritäten und feste Compose-Werte](docs/biblios/konfiguration.adoc)
- [Komponentenupdate und Tests](docs/biblios/entwicklung.adoc)
- [Fehlerdiagnose, Datenhaltung und Dokumentationszuständigkeiten](docs/biblios/fehlerdiagnose.adoc)

`working-tree` verhindert Git-Rückschreiben. S3-Publikation nach Garage ist im
Stack dagegen standardmässig aktiviert. Lokale Secrets liegen ausschliesslich
in ignorierten Dateien. `./scripts/down.sh` stoppt den Stack und erhält die
Volumes; eine Volume-Löschung entfernt auch Jenkins-Jobs und Buildhistorien.
