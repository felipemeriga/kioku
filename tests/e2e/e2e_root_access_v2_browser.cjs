#!/usr/bin/env node
/**
 * Real deployed UI acceptance. No API mocks, HAR, tracing, console forwarding, or secret artifacts.
 * Requirements: final V2 API/UI+migrations, authenticated owner storageState (0600), Playwright+Chrome.
 * KIOKU_V2_E2E_RELEASE_READY=1 KIOKU_PLAYWRIGHT_DIR=/tmp/kioku-live-ui-qa \
 * KIOKU_E2E_AUTH=/tmp/kioku-live-ui-qa/auth.json node tests/e2e/e2e_root_access_v2_browser.cjs
 * Creates its own synthetic root. KEEP_FIXTURE=1 hands it to native QA.
 * Root/provider cleanup is external unless an executable CLEANUP_HOOK is supplied.
 */
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const assert = require("node:assert/strict");
const { chromium } = require(path.join(
  process.env.KIOKU_PLAYWRIGHT_DIR || "/tmp/kioku-live-ui-qa",
  "node_modules/playwright"
));
const base = new URL(process.env.KIOKU_E2E_BASE || "https://kioku.merigafy.com")
  .origin;
const authPath =
  process.env.KIOKU_E2E_AUTH || "/tmp/kioku-live-ui-qa/auth.json";
const artifacts =
  process.env.KIOKU_E2E_ARTIFACTS || "/tmp/kioku-live-ui-qa/vault-v2-final-e2e";
if (process.env.KIOKU_V2_E2E_RELEASE_READY !== "1")
  throw new Error(
    "Set KIOKU_V2_E2E_RELEASE_READY=1 after the coordinated release."
  );
if ((fs.statSync(authPath).mode & 0o077) !== 0)
  throw new Error("Auth file must be owner-readable only (chmod 600).");
fs.mkdirSync(artifacts, { recursive: true, mode: 0o700 });
const keepFixture = process.env.KIOKU_V2_E2E_KEEP_FIXTURE === "1";
const fixturePath = path.join(artifacts, "cli-fixture.json");
const writeOperations = [];
let rootName = "";
let phase = "launch",
  rootId = null,
  browser,
  context,
  page,
  deviceToken = null;
const report = {
  base,
  noMocks: true,
  syntheticOnly: true,
  steps: [],
  pageErrors: [],
  cleanup: null,
};
const synthetic = () => crypto.randomBytes(30).toString("hex");
const initial = {
  access_key_id: "SYNTHETIC" + synthetic(),
  secret_access_key: synthetic(),
  session_token: synthetic(),
};
const rotated = {
  access_key_id: "SYNTHETIC" + synthetic(),
  secret_access_key: synthetic(),
};
const resourceName = "Synthetic AWS acceptance";
const environmentName = "Acceptance staging with a long environment name";
const deviceName = "Synthetic browser acceptance computer";
function step(name) {
  phase = name;
  report.steps.push({ name, status: "running" });
  fs.writeFileSync(
    path.join(artifacts, "progress.json"),
    JSON.stringify({
      phase: name,
      root_id: rootId,
      steps: report.steps.length,
    }),
    { mode: 0o600 }
  );
}
function done() {
  report.steps.at(-1).status = "passed";
}
async function call(endpoint, method = "GET", body, allowError = false) {
  const result = await page.evaluate(
    async ({ endpoint, method, body }) => {
      const key = Object.keys(localStorage).find(
        (k) => k.startsWith("sb-") && k.endsWith("-auth-token")
      );
      const session = JSON.parse(localStorage.getItem(key) || "{}");
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 15000);
      try {
        const response = await fetch(endpoint, {
          method,
          cache: "no-store",
          signal: controller.signal,
          headers: {
            Authorization: "Bearer " + session.access_token,
            "Content-Type": "application/json",
          },
          ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        });
        return {
          status: response.status,
          data: response.status === 204 ? null : await response.json(),
        };
      } finally {
        clearTimeout(timer);
      }
    },
    { endpoint, method, body }
  );
  if (!allowError && result.status >= 400)
    throw Object.assign(new Error("HTTP request failed"), {
      status: result.status,
    });
  return allowError ? result : result.data;
}
const catalog = () => call(`/api/root-access/${rootId}`);
async function refresh() {
  await page.goto(`${base}/folders/${rootId}/access`);
  await page
    .getByRole("button", { name: `Configure ${resourceName}`, exact: true })
    .waitFor();
}
async function openResource() {
  await page
    .getByRole("button", { name: `Configure ${resourceName}`, exact: true })
    .click();
  return page.getByRole("dialog");
}
async function choose(label, option) {
  await page.getByLabel(label).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}
async function verifyOverflow(view) {
  const result = await page.locator(".MuiDrawer-paper").evaluate((el) => {
    const bounds = el.getBoundingClientRect();
    return {
      client: el.clientWidth,
      scroll: el.scrollWidth,
      controlsOutside: [
        ...el.querySelectorAll("button,input,textarea,.access-credential-row"),
      ].filter((e) => {
        const b = e.getBoundingClientRect();
        return (
          b.width &&
          b.height &&
          (b.right > bounds.right + 1 || b.left < bounds.left - 1)
        );
      }).length,
    };
  });
  assert.ok(
    result.scroll <= result.client + 1 && result.controlsOutside === 0,
    "Drawer geometry failed"
  );
  report.geometry ??= [];
  report.geometry.push({ view, width: page.viewportSize().width, ...result });
}
async function safeScreenshot(name) {
  assert.ok(
    await page
      .locator("[data-secret]")
      .evaluateAll((nodes) => nodes.every((n) => !n.value)),
    "Secret editor must be empty before screenshot"
  );
  await page.screenshot({ path: path.join(artifacts, name + ".png") });
}
async function credentialWrite(values, region) {
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/^access key id/i).fill(values.access_key_id);
  await dialog.getByLabel(/^secret access key/i).fill(values.secret_access_key);
  await dialog.getByLabel(/^Session token/).fill(values.session_token || "");
  await dialog.getByLabel(/^Region \(non-secret/).fill(region);
  const expires = new Date(Date.now() + 2 * 60 * 60 * 1000);
  expires.setMinutes(expires.getMinutes() - expires.getTimezoneOffset());
  await dialog
    .getByLabel(/^Expiration/)
    .fill(expires.toISOString().slice(0, 16));
  await dialog
    .getByRole("button", { name: "Save credential", exact: true })
    .click();
  await dialog.getByRole("tab", { name: "Credentials", exact: true }).waitFor();
  await dialog.getByText("Stored in central vault", { exact: true }).count();
  await dialog.getByRole("button", { name: "Replace", exact: true }).waitFor();
}
async function createUsage(name, file = false) {
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("tab", { name: "How to use", exact: true }).click();
  await choose("Credential for new recipe", environmentName);
  await dialog.getByRole("button", { name: "Add usage recipe" }).click();
  await dialog.getByLabel(/^Recipe name/).fill(name);
  await dialog
    .getByLabel(/^Application or repository/)
    .fill("synthetic / acceptance");
  if (file) await choose("Delivery method", "Temporary configuration file");
  await dialog
    .getByRole("button", { name: "Save recipe", exact: true })
    .click();
  await dialog.getByRole("tab", { name: "How to use", exact: true }).waitFor();
  await dialog.getByText(name, { exact: true }).waitFor();
}
async function grantUsage(name) {
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("tab", { name: "Access", exact: true }).click();
  await choose(/^Computer/, deviceName);
  await choose(/^Usage recipe/, `${name} · synthetic / acceptance`);
  await dialog.getByRole("checkbox").check();
  const saved = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname ===
        `/api/root-access/${rootId}/usage-grants` &&
      response.request().method() === "POST"
  );
  await dialog
    .getByRole("button", { name: "Grant access", exact: true })
    .click();
  assert.ok((await saved).ok(), "Grant request failed");
  await page.waitForFunction(() =>
    [
      ...document.querySelectorAll('.access-drawer input[type="checkbox"]'),
    ].every((input) => !input.checked)
  );
}
async function resolveSummary(
  usage,
  credential,
  expected,
  region,
  denied = false
) {
  return page.evaluate(
    async ({
      rootId,
      usage,
      credential,
      expected,
      region,
      denied,
      deviceToken,
    }) => {
      const response = await fetch("/api/secret-access/resolve-v2", {
        method: "POST",
        cache: "no-store",
        signal: AbortSignal.timeout(15000),
        headers: {
          Authorization: "Bearer " + deviceToken,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          root_id: rootId,
          invocation_id: crypto.randomUUID(),
          usages: [
            {
              usage_id: usage.id,
              revision: usage.revision,
              credential_revision: credential.revision,
            },
          ],
        }),
      });
      if (denied)
        return { denied: response.status === 403, status: response.status };
      if (!response.ok) return { ok: false, status: response.status };
      const data = await response.json();
      const d = data.deliveries?.[0];
      const mapping = {
        AWS_ACCESS_KEY_ID: "access_key_id",
        AWS_SECRET_ACCESS_KEY: "secret_access_key",
        AWS_SESSION_TOKEN: "session_token",
      };
      const matches =
        d?.kind === "env"
          ? Object.entries(mapping).every(([dest, field]) =>
              expected[field] === undefined
                ? !Object.hasOwn(d.environment, dest)
                : d.environment[dest] === expected[field]
            ) && d.environment.AWS_REGION === region
          : d?.kind === "file" &&
            d.destination.name === "AWS_SHARED_CREDENTIALS_FILE" &&
            Object.entries(expected).every(([field, value]) =>
              d.patches.some(
                (p) =>
                  p.path.join(".") === "default.aws_" + field &&
                  p.value === value
              )
            ) &&
            !d.patches.some(
              (p) =>
                p.path.at(-1) === "aws_session_token" &&
                expected.session_token === undefined
            ) &&
            d.environment.AWS_REGION === region;
      return {
        ok: !!matches,
        status: response.status,
        kind: d?.kind,
        cacheControl: response.headers.get("cache-control"),
      };
    },
    { rootId, usage, credential, expected, region, denied, deviceToken }
  );
}
async function resumeRevocation() {
  const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
  assert.match(fixture.root_name, /^Vault V2 synthetic E2E /);
  assert.equal(fs.statSync(fixturePath).mode & 0o077, 0);
  rootId = fixture.root_id;
  rootName = fixture.root_name;
  deviceToken = fixture.device_token;
  report.root_id = rootId;
  await refresh();
  let snapshot = await catalog();
  const credential = snapshot.credentials.find(
    (c) => c.id === fixture.credential.id
  );
  let envUsage = snapshot.usages.find((u) => u.name === "Synthetic AWS env");
  const fileUsage = snapshot.usages.find(
    (u) => u.name === "Synthetic AWS profile"
  );
  assert.ok(credential && envUsage && fileUsage);
  step("stale displayed grant revision rejected");
  const edit = await call(
    `/api/root-access/${rootId}/usages/${envUsage.id}`,
    "PATCH",
    {
      credential_id: credential.id,
      name: envUsage.name,
      consumer: envUsage.consumer,
      delivery: { ...envUsage.delivery, clear_env: ["SYNTHETIC_OLD_TOKEN"] },
      enabled: true,
      expected_revision: envUsage.revision,
    }
  );
  const stale = await call(
    `/api/root-access/${rootId}/usage-grants`,
    "POST",
    {
      device_id: fixture.device_id,
      usage_id: envUsage.id,
      expected_usage_revision: envUsage.revision,
      allowed_fields: credential.fields,
      capabilities: ["env"],
      expires_at: null,
    },
    true
  );
  assert.equal(stale.status, 409);
  envUsage = edit;
  assert.equal(
    (await resolveSummary(envUsage, credential, {}, fixture.region, true))
      .denied,
    true
  );
  done();
  step("regrant reviewed current revision and revoke through UI");
  await refresh();
  let dialog = await openResource();
  await grantUsage("Synthetic AWS env");
  snapshot = await catalog();
  const grant = snapshot.usage_grants.find(
    (g) => g.usage_id === envUsage.id && !g.revoked_at
  );
  assert.equal(grant.usage_revision, envUsage.revision);
  const card = dialog
    .locator(".access-recipe-card")
    .filter({ hasText: `Synthetic AWS env · revision ${envUsage.revision}` });
  const revoked = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname ===
        `/api/root-access/${rootId}/usage-grants/${grant.id}/revoke` &&
      response.request().method() === "POST"
  );
  await card
    .getByRole("button", { name: "Revoke access", exact: true })
    .click();
  assert.ok((await revoked).ok());
  snapshot = await catalog();
  assert.ok(snapshot.usage_grants.find((g) => g.id === grant.id).revoked_at);
  assert.equal(
    (await resolveSummary(envUsage, credential, {}, fixture.region, true))
      .denied,
    true
  );
  done();
  step("responsive saved-state drawers");
  for (const width of [390, 720, 1024, 1512]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const tab of ["Credentials", "How to use", "Access"]) {
      await dialog.getByRole("tab", { name: tab, exact: true }).click();
      await verifyOverflow(tab);
    }
    await safeScreenshot(`saved-${width}`);
  }
  done();
  step("revoke computer through UI and deny remaining profile");
  await dialog.getByRole("button", { name: "Done", exact: true }).click();
  await page
    .getByRole("tab", { name: "Computers & access", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Revoke computer", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "Revoke access", exact: true })
    .click();
  await dialog.waitFor({ state: "hidden" });
  assert.equal(
    (await resolveSummary(fileUsage, credential, {}, fixture.region, true))
      .denied,
    true
  );
  done();
  fixture.phase = "revoked";
  fixture.usages = snapshot.usages.map((u) => ({
    id: u.id,
    revision: u.revision,
    name: u.name,
    kind: u.delivery.kind,
    credential_revision: credential.revision,
  }));
  fs.writeFileSync(fixturePath, JSON.stringify(fixture, null, 2), {
    mode: 0o600,
  });
  assert.deepEqual(report.pageErrors, []);
}
(async () => {
  try {
    browser = await chromium.launch({
      headless: true,
      executablePath:
        process.env.KIOKU_CHROME_PATH ||
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    });
    const state = JSON.parse(fs.readFileSync(authPath, "utf8"));
    if (!state.origins.some((o) => o.origin === base))
      state.origins.push({ ...state.origins[0], origin: base });
    context = await browser.newContext({
      storageState: state,
      viewport: { width: 1512, height: 1000 },
    });
    page = await context.newPage();
    page.setDefaultTimeout(20000);
    page.on("pageerror", (e) => report.pageErrors.push(e.name));
    page.on("request", (request) => {
      const match = new URL(request.url()).pathname.match(
        /^\/api\/root-access\/([^/]+)\/credentials\/([^/]+)\/value$/
      );
      if (match && request.method() === "POST") {
        try {
          const body = request.postDataJSON();
          writeOperations.push({
            root_id: match[1],
            credential_id: match[2],
            expected_revision: body.expected_revision,
            idempotency_key: body.idempotency_key,
          });
        } catch {
          /* Do not retain request values or diagnostics. */
        }
      }
    });
    step("authenticated production path");
    await page.goto(base + "/documents");
    await page.getByRole("heading", { name: /All documents/i }).waitFor();
    done();
    if (process.argv[2] === "resume") {
      await resumeRevocation();
      report.status = "passed";
      return;
    }
    step("dedicated synthetic root");
    const root = await call("/api/folders", "POST", {
      name: "Vault V2 synthetic E2E " + new Date().toISOString(),
      parent_id: null,
    });
    assert.match(root.id, /^[0-9a-f-]{36}$/i);
    rootId = root.id;
    rootName = root.name;
    report.root_id = rootId;
    await page.goto(`${base}/folders/${rootId}/access`);
    await page
      .getByRole("button", { name: "＋ Resource", exact: true })
      .waitFor();
    assert.equal((await catalog()).provider.configured, true);
    done();
    step("environment creation through UI");
    await page.getByRole("tab", { name: "Environments", exact: true }).click();
    await page
      .getByRole("button", { name: "Add environment", exact: true })
      .click();
    let dialog = page.getByRole("dialog");
    await dialog.getByLabel(/^Name/).fill(environmentName);
    await dialog.getByLabel(/^Identifier/).fill("synthetic-staging");
    await dialog
      .getByRole("button", { name: "Add environment", exact: true })
      .click();
    await dialog.waitFor({ state: "hidden" });
    done();
    step("AWS resource creation through UI");
    await page.getByRole("tab", { name: "Resources", exact: true }).click();
    await page
      .getByRole("button", { name: "＋ Resource", exact: true })
      .click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel(/^Resource name/).fill(resourceName);
    await choose("Resource type", "cloud");
    await dialog
      .getByLabel("Description")
      .fill(
        "Temporary synthetic-only acceptance resource; no real AWS account."
      );
    await choose("Credential type", "AWS credentials");
    await dialog
      .getByRole("checkbox", { name: environmentName, exact: true })
      .check();
    await dialog
      .getByRole("button", { name: "Save resource", exact: true })
      .click();
    await dialog.waitFor({ state: "hidden" });
    done();
    step("direct AWS bundle storage without mapping");
    dialog = await openResource();
    await dialog
      .getByRole("button", { name: "Add credential", exact: true })
      .click();
    await credentialWrite(initial, "us-east-1");
    let snapshot = await catalog();
    let credential = snapshot.credentials[0];
    assert.equal(credential.has_secret, true);
    assert.equal(snapshot.bindings.length, 0);
    assert.deepEqual(
      new Set(credential.fields),
      new Set(["access_key_id", "secret_access_key", "session_token"])
    );
    report.credential_id = credential.id;
    done();
    step("multi-field environment usage");
    await createUsage("Synthetic AWS env");
    await dialog.getByRole("button", { name: "Done", exact: true }).click();
    snapshot = await catalog();
    let envUsage = snapshot.usages.find((u) => u.name === "Synthetic AWS env");
    assert.equal(Object.keys(envUsage.delivery.field_mapping).length, 3);
    done();
    step("enroll synthetic computer with explicit browser approval");
    const enrollment = await call("/api/secret-access/enroll", "POST", {
      root_id: rootId,
      label: deviceName,
    });
    await page.goto(
      `${base}/folders/${rootId}/access?request_id=${enrollment.request_id}`
    );
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("button", { name: "Review enrollment request" })
      .click();
    await dialog
      .getByRole("button", { name: "Approve selected access" })
      .click();
    await dialog.waitFor({ state: "hidden" });
    const polled = await call("/api/secret-access/enroll/poll", "POST", {
      request_id: enrollment.request_id,
      device_code: enrollment.device_code,
    });
    assert.equal(polled.status, "approved");
    deviceToken = polled.device_token;
    assert.ok(deviceToken);
    done();
    step("grant exact environment recipe revision");
    await refresh();
    dialog = await openResource();
    await grantUsage("Synthetic AWS env");
    snapshot = await catalog();
    let grant = snapshot.usage_grants.find(
      (g) => g.usage_id === envUsage.id && !g.revoked_at
    );
    assert.ok(grant);
    assert.equal(grant.usage_revision, envUsage.revision);
    let resolved = await resolveSummary(
      envUsage,
      credential,
      initial,
      "us-east-1"
    );
    assert.equal(resolved.ok, true);
    assert.match(resolved.cacheControl || "", /no-store/);
    done();
    step("rotate bundle and omit prior session token");
    await dialog.getByRole("tab", { name: "Credentials", exact: true }).click();
    await dialog.getByRole("button", { name: "Replace", exact: true }).click();
    await credentialWrite(rotated, "eu-west-1");
    snapshot = await catalog();
    const rotatedCredential = snapshot.credentials.find(
      (c) => c.id === credential.id
    );
    assert.ok(rotatedCredential.revision > credential.revision);
    credential = rotatedCredential;
    resolved = await resolveSummary(envUsage, credential, rotated, "eu-west-1");
    assert.equal(resolved.ok, true);
    done();
    step("temporary AWS profile recipe and grant");
    await createUsage("Synthetic AWS profile", true);
    await grantUsage("Synthetic AWS profile");
    snapshot = await catalog();
    const fileUsage = snapshot.usages.find(
      (u) => u.name === "Synthetic AWS profile"
    );
    resolved = await resolveSummary(
      fileUsage,
      credential,
      rotated,
      "eu-west-1"
    );
    assert.equal(resolved.ok, true);
    done();
    if (keepFixture) {
      const saved = await catalog();
      fs.writeFileSync(
        fixturePath,
        JSON.stringify(
          {
            root_id: rootId,
            root_name: rootName,
            base_url: process.env.KIOKU_E2E_API_BASE || base,
            device_id: saved.devices.find((d) => d.label === deviceName).id,
            device_token: deviceToken,
            credential: { id: credential.id, revision: credential.revision },
            usages: saved.usages.map((u) => ({
              id: u.id,
              revision: u.revision,
              name: u.name,
              kind: u.delivery.kind,
              credential_revision: credential.revision,
            })),
            expected_sha256: Object.fromEntries(
              Object.entries(rotated).map(([field, value]) => [
                field,
                crypto.createHash("sha256").update(value).digest("hex"),
              ])
            ),
            region: "eu-west-1",
            write_operations: writeOperations,
            phase: "awaiting-native-cli",
          },
          null,
          2
        ),
        { mode: 0o600 }
      );
      report.status = "awaiting-native-cli";
      report.fixture = fixturePath;
      return;
    }
    step("stale grant revision rejected");
    const edit = await call(
      `/api/root-access/${rootId}/usages/${envUsage.id}`,
      "PATCH",
      {
        credential_id: credential.id,
        name: envUsage.name,
        consumer: envUsage.consumer,
        delivery: { ...envUsage.delivery, clear_env: ["SYNTHETIC_OLD_TOKEN"] },
        enabled: true,
        expected_revision: envUsage.revision,
      }
    );
    const device = (await catalog()).devices.find(
      (d) => d.label === deviceName
    );
    const stale = await call(
      `/api/root-access/${rootId}/usage-grants`,
      "POST",
      {
        device_id: device.id,
        usage_id: envUsage.id,
        expected_usage_revision: envUsage.revision,
        allowed_fields: credential.fields,
        capabilities: ["env"],
        expires_at: null,
      },
      true
    );
    assert.equal(stale.status, 409);
    envUsage = edit;
    resolved = await resolveSummary(
      envUsage,
      credential,
      rotated,
      "eu-west-1",
      true
    );
    assert.equal(resolved.denied, true);
    done();
    step("regrant current revision and revoke through UI");
    await dialog.getByRole("button", { name: "Done", exact: true }).click();
    await refresh();
    dialog = await openResource();
    await grantUsage("Synthetic AWS env");
    snapshot = await catalog();
    grant = snapshot.usage_grants.find(
      (g) => g.usage_id === envUsage.id && !g.revoked_at
    );
    assert.equal(grant.usage_revision, envUsage.revision);
    const card = dialog
      .locator(".access-recipe-card")
      .filter({ hasText: `Synthetic AWS env · revision ${envUsage.revision}` });
    const revoked = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/root-access/${rootId}/usage-grants/${grant.id}/revoke` &&
        response.request().method() === "POST"
    );
    await card
      .getByRole("button", { name: "Revoke access", exact: true })
      .click();
    assert.ok((await revoked).ok(), "Revoke request failed");
    snapshot = await catalog();
    assert.ok(snapshot.usage_grants.find((g) => g.id === grant.id).revoked_at);
    resolved = await resolveSummary(
      envUsage,
      credential,
      rotated,
      "eu-west-1",
      true
    );
    assert.equal(resolved.denied, true);
    done();
    step("responsive saved-state drawers");
    for (const width of [390, 720, 1024, 1512]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const tab of ["Credentials", "How to use", "Access"]) {
        await dialog.getByRole("tab", { name: tab, exact: true }).click();
        await verifyOverflow(tab);
      }
      await safeScreenshot(`saved-${width}`);
    }
    done();
    step("revoke computer and deny remaining profile access");
    await dialog.getByRole("button", { name: "Done", exact: true }).click();
    await page
      .getByRole("tab", { name: "Computers & access", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Revoke computer", exact: true })
      .click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByRole("button", { name: "Revoke access", exact: true })
      .click();
    await dialog.waitFor({ state: "hidden" });
    resolved = await resolveSummary(
      fileUsage,
      credential,
      rotated,
      "eu-west-1",
      true
    );
    assert.equal(resolved.denied, true);
    done();
    assert.deepEqual(report.pageErrors, []);
    report.status = "passed";
  } catch (error) {
    report.status = "failed";
    report.failedPhase = phase;
    report.error = { name: error.name, status: error.status || null };
    if (report.steps.at(-1)?.status === "running")
      report.steps.at(-1).status = "failed";
    process.exitCode = 1;
  } finally {
    deviceToken = null;
    if (rootId && page) {
      const hook = process.env.KIOKU_V2_E2E_CLEANUP_HOOK;
      if (keepFixture || !hook) {
        report.cleanup = {
          deleted: false,
          retainedForNativeOrProviderCleanup: true,
          root_id: rootId,
        };
        if (!fs.existsSync(fixturePath))
          fs.writeFileSync(
            fixturePath,
            JSON.stringify({
              root_id: rootId,
              root_name: rootName,
              write_operations: writeOperations,
              phase: "provider-cleanup-required",
            }),
            { mode: 0o600 }
          );
      } else {
        try {
          execFileSync(hook, [rootId, fixturePath], {
            stdio: "ignore",
            timeout: 60000,
          });
          const check = await call(
            `/api/root-access/${rootId}`,
            "GET",
            undefined,
            true
          );
          report.cleanup = {
            deleted: check.status === 404,
            status: check.status,
          };
          if (!report.cleanup.deleted) process.exitCode = 1;
          else fs.rmSync(fixturePath, { force: true });
        } catch (error) {
          report.cleanup = { deleted: false, status: error.status || null };
          process.exitCode = 1;
        }
      }
    }
    if (context) {
      try {
        await context.storageState({
          path: path.join(artifacts, "auth-refreshed.json"),
        });
        fs.chmodSync(path.join(artifacts, "auth-refreshed.json"), 0o600);
      } catch {
        report.authStateSaved = false;
      }
    }
    if (browser) await browser.close();
    fs.writeFileSync(
      path.join(
        artifacts,
        process.argv[2] === "resume"
          ? "result-resume.json"
          : "result-create.json"
      ),
      JSON.stringify(report, null, 2),
      { mode: 0o600 }
    );
    fs.writeFileSync(
      path.join(artifacts, "result.json"),
      JSON.stringify(report, null, 2),
      { mode: 0o600 }
    );
    console.log(
      JSON.stringify({
        status: report.status,
        failedPhase: report.failedPhase || null,
        steps: report.steps.length,
        cleanup: report.cleanup,
        artifacts,
      })
    );
  }
})();
