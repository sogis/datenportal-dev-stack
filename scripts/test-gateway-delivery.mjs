// Publishes the documented local pilot fixture through the browser and requests reload.
// Requires the initialized local stack, a successful seed and a configured reload token.
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
const require = createRequire(new URL('../../datenportal-datenblatt-editor/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const base = (process.env.JENKINS_TEST_URL || 'http://localhost:8081/jenkins').replace(/\/$/, '');
assert(['localhost', '127.0.0.1'].includes(new URL(base).hostname), 'Only local Jenkins may be tested');
const origin = new URL(base).origin;
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  await page.goto(origin + '/anlieferung');
  await page.locator('[name="j_username"]').fill(process.env.JENKINS_TEST_USER || 'admin');
  await page.locator('[name="j_password"]').fill(process.env.JENKINS_TEST_PASSWORD || 'admin');
  await page.locator('[name="Submit"]').click();
  const job = base + '/job/gretl-datenportal-statistikdienst';
  const before = await (await page.request.get(job + '/api/json')).json();
  assert(!before.inQueue, 'Job already queued');
  if (before.lastBuild) {
    const previous = await (await page.request.get(before.lastBuild.url + 'api/json')).json();
    assert(!previous.building, 'Job already running');
  }
  const manifestBefore = await (await page.request.get(origin + '/ch.so.daten/current.json')).json();
  await page.goto(base + '/gretl-datenportal/start?organization=statistikdienst&dataset=ch.so.bevoelkerung.altersstruktur');
  const fixture = new URL('../../datenportal-pilot-daten/ch.so.bevoelkerung.altersstruktur/', import.meta.url);
  await page.locator('[name="DATA_FILE"]').setInputFiles(fileURLToPath(new URL('so_bevo_altersstruktur_2025.csv', fixture)));
  await page.locator('[name="METADATA_FILE"]').setInputFiles(fileURLToPath(new URL('meta-ch.so.bevoelkerung.altersstruktur.xtf', fixture)));
  await page.locator('[name="SERIES_ID"]').fill('2025');
  await page.locator('[name="RELOAD_PORTAL"]').check();
  await page.getByRole('button', {name: 'Job starten', exact: true}).click();
  await page.waitForURL(url => url.pathname.startsWith('/jenkins/gretl-datenportal/run'));
  const buildUrl = job + '/' + before.nextBuildNumber;
  let build;
  for (let attempt = 0; attempt < 180; attempt++) {
    const response = await page.request.get(buildUrl + '/api/json');
    if (response.ok()) {
      build = await response.json();
      if (!build.building) break;
    }
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  assert.equal(build?.result, 'SUCCESS', `Delivery failed or timed out: ${buildUrl}`);
  const reportArtifact = build.artifacts.find(a => a.fileName === 'report.json');
  assert(reportArtifact, 'Missing publication report');
  const report = await (await page.request.get(buildUrl + '/artifact/' + reportArtifact.relativePath)).json();
  assert.equal(report.publication, 'accepted');
  assert.equal(report.reload, 'succeeded');
  assert.equal(report.opendata?.status, 'accepted');
  console.log(`Publication ${report.releaseId}: accepted, RDF accepted, reload succeeded`);
  const manifest = await (await page.request.get(origin + '/ch.so.daten/current.json')).json();
  assert.notEqual(manifest.releaseId, manifestBefore.releaseId, 'No new manifest generation');
  const published = await (await page.request.get(origin + '/ch.so.daten/' + manifest.duckdb)).body();
  const active = await (await page.request.get(origin + '/catalog/catalog.duckdb')).body();
  assert(published.equals(active), 'Reload did not activate the published DuckDB');
  console.log(`PASS: multipart upload, publication and reload through ${buildUrl}`);
} finally {
  await browser.close();
}
