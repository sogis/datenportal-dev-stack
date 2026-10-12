# datenportal-dev-stack

Lokaler Integrationsstack für Entwicklung, Tests und Demos: Garage-S3,
APISIX für sämtliche öffentlichen HTTP-Zugänge, Datenblatt-Editor, Portal und
Jenkins/GRETL sowie die Dokumentation. Die Komponenten und ihre Buildlogik bleiben in den jeweiligen
Schwester-Repositories.

Für eine Testumgebung nur mit veröffentlichten, versionsgetaggten Images genügt
dieser Checkout (Docker Compose >= 2.24.4, Git, Bash, OpenSSL, curl und Python 3):

```bash
./scripts/up.sh --registry-only
docker compose -f compose.yaml -f compose.registry.yaml ps -a
```

`compose.registry.yaml` ersetzt die Schwesterrepo-Mounts durch die Test-JCasC
in diesem Repository. Jenkins verwendet `managed-git` und bezieht
`https://github.com/sogis/datenportal-themenrepo.git` (Branch `main`) selbst.
Git-Rückschreiben bleibt aus. Sodata verwendet das native Image
`sogis/datenportal-sodata:0.1.18`, Jenkins `0.1.0-6`, Dokumentation `0.1.24`.
Alle acht Image-Referenzen des Registry-Stacks wurden am 12.10.2026 direkt in
der Registry geprüft und sind für `linux/amd64` und `linux/arm64` verfügbar.
Bei einem frischen Checkout erzeugt `up.sh` die `.env` automatisch mit diesen
Vorgaben; manuelle Image-Korrekturen sind nicht nötig. Nur bei einer älteren
`.env` diese drei Image-Werte abgleichen und gegebenenfalls aktualisieren;
Secrets werden nicht ersetzt. Für ein bestehendes System das neue Sodata-Image
laden und den Container neu erstellen; siehe [Image-Update](docs/biblios/start.adoc#_sodata_in_einer_bestehenden_registry_installation_aktualisieren).
Alle direkten Compose-Aufrufe dieser Variante
verwenden beide Dateien. Keine Kombination mit `--local-*`.
`up.sh` liest die zu prüfenden Images für Jenkins, Sodata und Dokumentation
aus der effektiven Compose-Konfiguration; Shell- und `.env`-Overrides gelten
damit auch für die Image-Prüfung. Die Defaults in Compose und `.env.example`
werden gemeinsam durch Regressionstests abgesichert.
Der vollständige Ablauf mit Seed, Erstpublikation und einzeln heruntergeladenen
Beispieldateien steht in der
[Betriebsdoku](https://github.com/sogis/datenportal-dokumentation-betrieb/blob/main/docs/biblios/lokal-kennenlernen.adoc).

Für den empfohlenen Entwicklungsweg werden Docker mit Compose v2, Bash,
OpenSSL, Git, rsync, Python 3, Maven sowie Java 17 und Java 21 benötigt. Die benötigten Checkouts und Java-Einstellungen stehen unter
[Voraussetzungen und Start](docs/biblios/start.adoc).

Aus dem Stack-Repository:

```bash
./scripts/up.sh --local-editor --local-jenkins --local-sodata
```

Das baut die lokalen Komponenten, installiert das Plugin im Jenkins-Volume
und bereitet den Stack vollständig vor: erfolgreicher Seed, bei einem frischen
lokalen Garage-Bestand Erstpublikation und anschliessend Portalstart. Ohne
CSV-Lieferung ist der Katalog zunächst leer, enthält aber eine gültige DuckDB.
Bei jedem erneuten Aufruf wird neu geseedet; ein vorhandener Publikationsstand
wird geprüft und erhalten. Die [Inbetriebnahme](docs/biblios/inbetriebnahme.adoc)
beschreibt Lieferungen, Migration und Fehlerfälle.

Für lokale Themenrepo-Änderungen mit veröffentlichten Komponentenimages genügt
`./scripts/up.sh` und `../datenportal-themenrepo`. Der zusätzliche Checkout
`../datenportal-jenkins-dev` ist nur für lokale Jenkins-Builds erforderlich.
Die gemeinsame lokale Test-JCasC gehört zum Dev-Stack.

Der Themenintegrator verwendet denselben Start und `scripts/bootstrap.sh`.
Der Helfer vervollständigt bereits laufende Basisdienste und akzeptiert dieselben
Compose-Dateien über `-f`. `--check-only` prüft einen vorhandenen Bestand ohne
Seed oder Container-Neuerstellung. Für bewusstes administratives Initialisieren
oder Migration `up.sh --infrastructure-only` verwenden.

| Dienst | Standardadresse vom Host/Browser |
|---|---|
| Jenkins, lokal `admin` / `admin` | http://localhost:8081/anlieferung |
| Jenkins-Administration | http://localhost:8081/jenkins/ |
| Öffentlicher Bucket | http://localhost:8081/ch.so.daten/ |
| RDF-Export nach erfolgreicher Publikation | http://localhost:8081/ch.so.daten/opendata.rdf |
| Gültiger Gesamtstand nach Initialisierung | http://localhost:8081/ch.so.daten/current.json |
| Editor | http://localhost:8081/datenblatt-editor/ |
| Dokumentation | http://localhost:8081/dokumentation/ |
| Portal | http://localhost:8081/ |
| Authentifizierte S3-API | http://localhost:3900 |

Die vollständige [Entwicklungsdokumentation](docs/biblios/index.adoc)
führt durch:

- [Voraussetzungen, Startoptionen und Images](docs/biblios/start.adoc)
- [Initialisierung, Lieferungen, Vorschau und Portal-Anschluss](docs/biblios/inbetriebnahme.adoc)
- [Parameter, Prioritäten und feste Compose-Werte](docs/biblios/konfiguration.adoc)
- [Komponentenupdate und Tests](docs/biblios/entwicklung.adoc)
- [Fehlerdiagnose, Datenhaltung und Dokumentationszuständigkeiten](docs/biblios/fehlerdiagnose.adoc)

`working-tree` verhindert Git-Rückschreiben. S3-Publikation nach Garage ist im
Stack dagegen standardmässig aktiviert. Lokale Secrets einschliesslich des gemeinsam verwendeten Reload-Tokens werden
bei Bedarf erzeugt und liegen ausschliesslich in ignorierten Dateien. `./scripts/down.sh` stoppt den Stack und erhält die
Volumes; eine Volume-Löschung entfernt auch Jenkins-Jobs und Buildhistorien.

Alle öffentlichen Anwendungen laufen über APISIX. Die Pfade entsprechen dem
Produktionsziel auf `daten.so.ch`; öffentliche Dateien erhalten dort eine
separate Subdomain. S3-Schreiben und Portal-Reload bleiben intern. Die bisherigen
Direktports 8080/8082 und die Variablen `JENKINS_PORT`/`SODATA_PORT` entfallen.
Alte Editorpfade unter `/metadaten-editor` werden weitergeleitet. Der bestehende
Downloadpfad bleibt erhalten; vorhandene Volumes nicht neu initialisieren.

Die Dokumentation verwendet standardmässig `sogis/datenportal-dokumentation:0.1.24`
(überschreibbar mit `DATENPORTAL_DOCS_IMAGE`), ohne lokalen Registry-Fallback.
Mit `./scripts/up.sh --local-docs` werden zuerst die lokalen Dokumentationsquellen
inklusive uncommitteter Inhalte mit Thoth und danach das Image gebaut. Benötigt
werden Java 25, Python mit PyYAML und der benachbarte Thoth-Checkout oder
`THOTH_JAR`. Der Schalter ist mit den anderen lokalen Buildoptionen kombinierbar,
aber nicht mit `--registry-only`. Siehe [lokaler Docs-Build](docs/biblios/entwicklung.adoc).
