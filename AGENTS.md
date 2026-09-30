# AGENTS.md — datenportal-dev-stack

Diese Datei gilt für das Repository `datenportal-dev-stack` und alle Arbeiten
am lokalen Datenportal-Gesamtsystem. Das Repository ist der pragmatische
Integrationsrahmen für lokale Entwicklung, End-to-End-Tests und Demos. Es ist
nicht die Source of Truth für die Implementierung, die fachlichen Datenverträge
oder die Dokumentationsinhalte der einzelnen Komponenten.

Der Stack ist noch im Aufbau. Solange keine Compose-Datei vorhanden ist,
dürfen keine konkreten Service-Namen, Ports, Profile oder
Umgebungsvariablen als bereits bestehender Vertrag angenommen werden.

## Schwester-Repositories

Die Repositories liegen lokal normalerweise als Geschwisterordner neben diesem
Repository. Ausgehend vom Root dieses Repositories sind die erwarteten Pfade
relativ:

| Repository | Lokaler Pfad | Rolle im Gesamtsystem |
| --- | --- | --- |
| [datenportal-themenrepo](https://github.com/sogis/datenportal-themenrepo) | `../datenportal-themenrepo` | Fachlicher Vertrag für Organisationen, Datensätze, Themenrepo-YAML, Shared Defaults, Teams, Jenkinsfile und den Gradle-/GRETL-Build-Vertrag. |
| [datenportal-pilot-daten](https://codeberg.org/edigonzales/datenportal-pilot-daten) | `../datenportal-pilot-daten` | Pilot- und Beispieldaten einschließlich XTF-Metadaten und CSV-Dateien für lokale Tests und Demos. |
| [datenportal-datenblatt-editor](https://codeberg.org/edigonzales/datenportal-datenblatt-editor) | `../datenportal-datenblatt-editor` | Offlinefähiger Vue-/Vite-Metadateneditor für `Dataset` und `DatasetSeries`; besitzt sein eigenes Frontend und Docker-/NGINX-Image. |
| [datenportal-dokumentation](https://codeberg.org/edigonzales/datenportal-dokumentation) | `../datenportal-dokumentation` | Thoth-Biblios-Konfiguration und Aggregator für die gemeinsame Datenportal-Dokumentationswebsite. |
| [datenportal-jenkins-dev](https://codeberg.org/edigonzales/datenportal-jenkins-dev) | `../datenportal-jenkins-dev` | Lokale Jenkins-Laufzeit, JCasC, Offline-Bundle, Plugin-Installation, lokale Integrationsumgebung und Jenkins-Docker-Image. |
| [datenportal-jenkins-gretl-plugin](https://codeberg.org/edigonzales/datenportal-jenkins-gretl-plugin) | `../datenportal-jenkins-gretl-plugin` | Eigentliche Implementierung und Paketierung des Jenkins-/GRETL-Datenportal-Plugins; erzeugt das HPI, das von `datenportal-jenkins-dev` verwendet wird. |
| [datenportal-sodata](https://codeberg.org/edigonzales/datenportal-sodata) | `../datenportal-sodata` | Serverseitig gerenderte Datenportal-Webanwendung mit PublishedCatalog-XTF-Import, Suche, Detailseiten und Reload-Funktion; aktuell ohne Docker-/Kubernetes-Deployment. |
| [datenportal-dokumentation-datenintegration](https://codeberg.org/edigonzales/datenportal-dokumentation-datenintegration) | `../datenportal-dokumentation-datenintegration` | Kanonische Dokumentation für Datenlieferanten und Datenintegration. |
| [datenportal-dokumentation-glossar](https://codeberg.org/edigonzales/datenportal-dokumentation-glossar) | `../datenportal-dokumentation-glossar` | Kanonisches Glossar des Datenportals. |

Die Remote-Links sind die dauerhaften Referenzen; das Themenrepo liegt auf GitHub. Die lokalen Pfade dienen
nur der Entwicklung und dürfen nicht durch benutzerspezifische absolute Pfade
wie `/Users/...` in Konfiguration oder Dokumentation ersetzt werden.

## Zuständigkeit dieses Repositories

In dieses Repository gehören die Gesamtsystem-Orchestrierung und die dafür
nötigen Integrationsartefakte:

- Docker-Compose-Dateien und deren Netzwerke, Volumes und Startreihenfolgen;
- Verbindungen zwischen den Komponenten sowie lokale Mounts und
  Umgebungsvariablen;
- Healthchecks, Demo-Konfiguration und reproduzierbare lokale Testabläufe;
- End-to-End- und Smoke-Tests, die mehr als eine Komponente prüfen;
- kurze Stack-Dokumentation und Hinweise zum lokalen Betrieb.

In dieses Repository gehören grundsätzlich nicht:

- Dockerfiles für eine fachliche oder technische Komponente, die bereits ein
  eigenes Komponenten-Repository besitzt;
- Implementierungslogik von Webapp, Editor, Jenkins oder Jenkins-Plugin;
- fachliche Verträge, Datensatzdefinitionen, Berechtigungsmodelle oder
  Pipeline-Logik aus dem Themenrepo;
- eine zweite, vom jeweiligen Source-of-Truth-Repository abweichende Version
  von Metadaten-, Daten- oder Dokumentationsinhalten.

Eine ausdrücklich nur für den Dev-Stack benötigte Infrastruktur-Hilfsdatei
kann hier liegen. Die Zuständigkeit und ihr lokaler Zweck müssen dann in der
Stack-Dokumentation klar benannt werden.

## Docker- und Build-Verantwortung

Der Dev-Stack darf die Images der Komponenten per Compose bauen oder
verwenden, aber deren Dockerfiles und Buildlogik nicht kopieren. Die
Verantwortung ist derzeit:

- `datenportal-datenblatt-editor` pflegt sein Frontend- und NGINX-Image.
- `datenportal-jenkins-dev` pflegt sein Jenkins-Controller- und
  Integrationsimage.
- `datenportal-jenkins-gretl-plugin` pflegt das Plugin und dessen HPI; das
  Jenkins-Dev-Repository installiert dieses Artefakt in die lokale Laufzeit.
- `datenportal-sodata` hat derzeit keinen dokumentierten Docker- oder
  Kubernetes-Deploymentvertrag. Für lokale Tests ist daher zunächst der im
  Repository dokumentierte Laufzeit- bzw. Entwicklungsstart maßgeblich.
- `datenportal-themenrepo` und `datenportal-pilot-daten` liefern Verträge bzw.
  Testdaten; sie sind nicht automatisch eigene Container-Images.

Wenn eine Komponente künftig containerisiert werden soll, muss der
Deploymentvertrag zuerst im zuständigen Komponenten-Repository festgelegt
werden. Der Dev-Stack integriert ihn anschließend. Ein Image darf nur dann
hier definiert werden, wenn es tatsächlich ausschließlich zur
Stack-Infrastruktur gehört.

## Arbeitsweise bei Änderungen

Vor Änderungen, die mehrere Repositories berühren könnten:

1. `git status --short --branch` in diesem Repository und in jedem betroffenen
   Schwester-Repository prüfen.
2. Das jeweilige `README.md`, vorhandene `AGENTS.md` und die für den Bereich
   genannten kanonischen Dokumente lesen.
3. Erst festlegen, welches Repository die Änderung besitzen soll. Eine
   Compose-Anpassung gehört hierher; eine Komponentenänderung gehört in das
   jeweilige Schwester-Repository.
4. Lokale, uncommittete oder untracked Änderungen in Schwester-Repositories
   erhalten und bei Tests berücksichtigen, wenn ausdrücklich der
   `working-tree`-Stand verwendet werden soll.
5. Nach Änderungen alle betroffenen Repositories und die verwendeten
   Eingabestände im Ergebnis nennen.

Schwester-Repositories dürfen im Rahmen einer Aufgabe nur geändert werden,
wenn dies ausdrücklich beauftragt oder für die vereinbarte Gesamtsystemänderung
notwendig ist. Niemals unaufgefordert `git reset`, `git checkout` oder andere
Aktionen verwenden, die fremde Arbeitsstände verwerfen.

## Lokale Compose- und Testregeln

Sobald Compose-Dateien vorhanden sind, sollen Änderungen mindestens mit dem
konkreten Compose-Setup validiert werden:

```bash
docker compose config
docker compose build
docker compose up -d
docker compose ps
```

Danach die dokumentierten Healthchecks und Integrations-/Smoke-Tests ausführen
und relevante Logs bei Fehlern prüfen. Die tatsächlichen Befehle, Service-Namen,
Ports und Profile müssen aus den vorhandenen Compose-Dateien und der
Stack-Dokumentation stammen; sie dürfen nicht vorausschauend erfunden werden.

`docker compose down` ist für normale lokale Aufräumarbeiten zulässig.
`docker compose down -v`, das Löschen von Volumes oder das Leeren persistenter
Jenkins-Daten ist destruktiv und darf nur nach expliziter Beauftragung oder
mit klar bestätigtem Testziel erfolgen.

Für komponentenspezifische Checks gelten die Anleitungen des jeweiligen
Repositories. Der Stack soll diese Befehle nicht stillschweigend durch eigene
Alternativen ersetzen. Falls eine Abhängigkeit, ein Tool, ein Image oder ein
lokales Schwester-Repository fehlt, ist das im Ergebnis klar zu melden.

## Daten, Konfiguration und Sicherheit

- Zugangsdaten, Tokens und private Registry-Konfiguration gehören in lokale,
  ignorierte Konfigurationsdateien oder die Umgebung, niemals in Git.
- `.env`-Dateien und lokale Secrets nicht committen; bei neuen lokalen Dateien
  vorab prüfen, ob die Ignore-Regeln greifen.
- Testdaten aus `datenportal-pilot-daten` nur als deklarierte Fixtures oder
  Mounts verwenden und ihre Herkunft in der Stack-Dokumentation sichtbar
  halten.
- Generierte Container-Kontexte, Jenkins-Homes, Offline-Bundles, Logs und
  Buildausgaben nicht als dauerhafte Quelldateien hinzufügen.
- Keine Secrets, Tokens oder vollständigen Zugangsdaten in Logs, Testausgaben
  oder Dokumentation ausgeben.

## Dokumentationsquellen

Für fachliche und komponentenspezifische Aussagen zuerst die kanonischen
Quellen konsultieren:

- Themenrepo: [technische Entwicklungsdokumentation](https://github.com/sogis/datenportal-themenrepo/blob/main/docs/biblios)
- Jenkins-Dev: [lokaler Jenkins und Entwicklungsdokumentation](https://codeberg.org/edigonzales/datenportal-jenkins-dev/src/branch/main/docs/biblios/entwicklung)
- Jenkins-Plugin: [Plugin-Entwicklungsdokumentation](https://codeberg.org/edigonzales/datenportal-jenkins-gretl-plugin/src/branch/main/docs/biblios/entwicklung)
- Datenportal-Webapp: [README und Agent-Regeln](https://codeberg.org/edigonzales/datenportal-sodata)
- Gemeinsame Website: [Dokumentationsaggregator](https://codeberg.org/edigonzales/datenportal-dokumentation)
- Datenintegration: [Datenlieferanten-Dokumentation](https://codeberg.org/edigonzales/datenportal-dokumentation-datenintegration)
- Glossar: [Glossar-Repository](https://codeberg.org/edigonzales/datenportal-dokumentation-glossar)

Wenn Stack-Verhalten geändert wird, die README oder die passende lokale
Dokumentation aktualisieren. Fachliche Inhalte bleiben in ihren jeweiligen
Quell-Repositories.

## Abschlussprüfung

Vor dem Abschluss einer Änderung:

- nur die beauftragten Dateien und Repositories sind verändert;
- `git diff --check` ist erfolgreich;
- Compose-Konfiguration, Builds und Smoke-Tests wurden – sofern vorhanden –
  ausgeführt oder ihre Nichtausführbarkeit wurde begründet;
- die verwendeten lokalen Schwesterpfade und gegebenenfalls uncommitteten
  Arbeitsstände sind dokumentiert;
- keine Secrets, generierten Laufzeitdaten oder fremden Änderungen wurden
  versehentlich aufgenommen.
