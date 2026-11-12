const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const source = fs.readFileSync(__dirname + "/src/window.js", "utf8");
function launch(route, saved = null, online = true) {
  const store = new Map(saved ? [["kioku.desktop.last-route", saved]] : []);
  const listeners = {};
  let redirected;
  let notice;
  const location = new URL(route, "https://kioku.merigafy.com");
  location.replace = (value) => {
    redirected = String(value);
  };
  const context = {
    URL,
    URLSearchParams,
    location,
    Date,
    navigator: { onLine: online },
    localStorage: {
      getItem: (key) => store.get(key),
      setItem: (key, value) => store.set(key, value),
    },
    addEventListener: (name, callback) => {
      listeners[name] = callback;
    },
    history: { pushState() {}, replaceState() {} },
    document: {
      readyState: "loading",
      createElement: () => ({ setAttribute() {}, style: {} }),
      body: {
        append: (value) => {
          notice = value;
        },
      },
    },
  };
  context.window = context;
  vm.runInNewContext(source, context);
  return {
    context,
    store,
    listeners,
    get redirect() {
      return redirected;
    },
    get notice() {
      return notice;
    },
  };
}
test("restores only same-origin application routes and excludes credentials", () => {
  const restored = launch(
    "/?desktop_launch=1",
    "/documents?folder=abc&access_token=secret",
  );
  const url = new URL(restored.redirect);
  assert.equal(url.pathname, "/documents");
  assert.equal(url.searchParams.get("folder"), "abc");
  assert.equal(url.searchParams.has("access_token"), false);
  assert.equal(
    launch("/?desktop_launch=1", "https://evil.example/documents").redirect,
    undefined,
  );
  assert.equal(launch("/login?access_token=secret").store.size, 0);
});
test("offline notice clears on reconnect without reloading or changing the route", () => {
  const app = launch("/documents", null, false);
  app.listeners.DOMContentLoaded();
  assert.equal(app.notice.hidden, false);
  app.context.navigator.onLine = true;
  app.listeners.online();
  assert.equal(app.notice.hidden, true);
  assert.equal(app.redirect, undefined);
});
