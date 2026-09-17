"""The optional browser/reload stage of test-publication.py, using its isolated services."""
import json
import os
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET


def verify(scope):
    service, run, gradle = (scope[k] for k in ('service', 'run', 'gradle'))
    work, stack, repo, public, dataset = (scope[k] for k in ('WORK', 'STACK', 'REPO', 'public', 'DATASET'))
    service('portal', os.environ.get('DATENPORTAL_SODATA_IMAGE', 'datenportal-sodata:local'), env={
        'DATENPORTAL_CATALOG_SOURCE_TYPE':'manifest',
        'DATENPORTAL_CATALOG_HTTP_URL':'http://proxy:8000/public/current.json',
        'DATENPORTAL_CATALOG_DUCKDB_SOURCE_TYPE':'manifest',
        'DATENPORTAL_CATALOG_DOWNLOAD_URL':'http://proxy:8000/public',
        'DATENPORTAL_ADMIN_RELOAD_TOKEN':'local-test-token'})
    port = run('docker','port',scope['NET']+'-portal','8080/tcp').rsplit(':',1)[1]
    portal = 'http://127.0.0.1:'+port
    for _ in range(120):
        try:
            with urllib.request.urlopen(portal+'/actuator/health', timeout=2): break
        except OSError: time.sleep(1)
    else: raise AssertionError('Portal startup timed out')

    def artifact():
        with urllib.request.urlopen(portal+'/catalog/catalog.duckdb') as response: return response.read()
    before = artifact()
    init = work/'playground-browser.gradle'
    # Reuse sodata's pinned Playwright dependency and browser installation; no new dependency version.
    init.write_text('''gradle.projectsEvaluated {
    def p = gradle.rootProject
    p.tasks.register('publicationPlaygroundSmoke', JavaExec) {
        dependsOn p.tasks.named('installPlaywrightChromium')
        classpath = p.sourceSets.test.runtimeClasspath
        javaLauncher = p.javaToolchains.launcherFor { languageVersion = JavaLanguageVersion.of(25) }
        mainClass = System.getenv('PLAYGROUND_SMOKE_SOURCE')
        args System.getenv('PLAYGROUND_SMOKE_URL'), System.getenv('PLAYGROUND_GATEWAY'), System.getenv('PLAYGROUND_VIEW_COUNT'), System.getenv('PLAYGROUND_SCREENSHOT')
        environment 'PLAYWRIGHT_BROWSERS_PATH', new File(p.projectDir,'.gradle/playwright-browsers').absolutePath
    }
}
''')
    def browser(count):
        env = dict(os.environ, PLAYGROUND_SMOKE_SOURCE=str(stack/'scripts/testing/PlaygroundSmoke.java'),
                   PLAYGROUND_SMOKE_URL=portal+'/series/'+dataset+'/issues/current/explore',
                   PLAYGROUND_GATEWAY=public.split('/public/')[0], PLAYGROUND_VIEW_COUNT=str(count),
                   PLAYGROUND_SCREENSHOT=str(work/f'playground-{count}-views.png'))
        with (work/f'playground-{count}-views.log').open('w') as log:
            subprocess.run([str(stack.parent/'datenportal-sodata/gradlew'), '-p', str(stack.parent/'datenportal-sodata'),
                            '-I',str(init),'publicationPlaygroundSmoke','--console=plain'], env=env,
                           stdout=log,stderr=subprocess.STDOUT,check=True)
    browser(1)
    # Add a documented historical issue and publish it with data, then reload the running portal.
    tree = ET.parse(repo/scope['REL'])
    issue = next(e for e in tree.iter() if e.tag.endswith('}DatasetIssue'))
    parent = next(e for e in tree.iter() if issue in list(e))
    from copy import deepcopy
    historical = deepcopy(issue)
    for e in historical.iter():
        if e.text: e.text = e.text.replace('2025','2024')
        if e.tag.endswith('}isCurrentIssue'): e.text='false'
    parent.append(historical)
    tree.write(work/'playground-history.xtf',encoding='UTF-8',xml_declaration=True)
    report = gradle('playground-new-history', ['-PmetadataFile=/test/playground-history.xtf',
        '-PdataFile=/pilot/'+dataset+'/so_bevo_altersstruktur_2025.csv', '-PseriesId=2024'])
    assert report['duckdb']['viewCount']==2
    request = urllib.request.Request(portal+'/admin/catalog/reload', data=b'',
                                     headers={'X-Reload-Token':'local-test-token'},method='POST')
    with urllib.request.urlopen(request) as response: assert json.load(response)['success']
    assert artifact()!=before
    browser(2)
    print('PASS: generated catalog in browser, historical view added after atomic portal reload',flush=True)
