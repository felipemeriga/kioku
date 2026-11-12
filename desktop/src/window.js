(() => {
  if (window.__kiokuDesktop) return;
  window.__kiokuDesktop = true;
  const key = "kioku.desktop.last-route";
  const safe = (raw) => {
    try {
      const url = new URL(raw, location.origin);
      if (
        url.origin !== location.origin ||
        !(
          /^\/(?:documents|settings)?$/.test(url.pathname) ||
          url.pathname.startsWith("/folders/")
        )
      )
        return null;
      const query = new URLSearchParams();
      for (const name of ["folder", "event", "tab"]) {
        const value = url.searchParams.get(name);
        if (value && value.length < 256) query.set(name, value);
      }
      const search = query.toString();
      return url.pathname + (search ? "?" + search : "");
    } catch {
      return null;
    }
  };
  try {
    const previous = safe(localStorage.getItem(key) || "/");
    if (
      location.pathname === "/" &&
      location.search.includes("desktop_launch=") &&
      previous &&
      previous !== "/"
    ) {
      const url = new URL(previous, location.origin);
      url.searchParams.set("desktop_launch", String(Date.now()));
      location.replace(url);
      return;
    }
  } catch {
    /* Private storage may be unavailable. */
  }
  const remember = () => {
    try {
      const route = safe(location.href);
      if (route) localStorage.setItem(key, route);
    } catch {}
  };
  for (const method of ["pushState", "replaceState"]) {
    const original = history[method];
    history[method] = function (...args) {
      const result = original.apply(this, args);
      remember();
      return result;
    };
  }
  addEventListener("popstate", remember);
  remember();
  const ready = () => {
    const notice = document.createElement("div");
    notice.setAttribute("role", "status");
    notice.style.cssText =
      "position:fixed;bottom:16px;left:50%;transform:translateX(-50%);z-index:2147483647;padding:12px 20px;border:1px solid #ff1493;border-radius:8px;background:#160b22;color:#fff;font:14px system-ui;box-shadow:0 4px 24px #0008";
    notice.textContent =
      "You are offline. Kioku will reconnect when your connection returns.";
    const sync = () => {
      notice.hidden = navigator.onLine;
    };
    addEventListener("offline", sync);
    addEventListener("online", sync);
    document.body.append(notice);
    sync();
  };
  if (document.readyState === "loading")
    addEventListener("DOMContentLoaded", ready, { once: true });
  else ready();
})();
