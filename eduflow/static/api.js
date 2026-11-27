let csrf;

export async function api(path, {method = "GET", data, signal} = {}) {
  const headers = {Accept: "application/json"};
  if (method !== "GET") {
    csrf ||= (await api("/api/v1/session/")).csrf_token;
    headers["X-CSRFToken"] = csrf;
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(path, {
    method, headers, signal,
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  if (response.status === 204) return null;
  const type = response.headers.get("Content-Type") || "";
  const result = type.includes("application/json") ? await response.json() : {};
  if (!response.ok || !type.includes("application/json")) {
    const error = new Error("API request failed");
    error.status = response.status;
    error.data = result;
    throw error;
  }
  if (result.csrf_token) csrf = result.csrf_token;
  return result;
}

export async function allPages(path) {
  const results = [];
  while (path) {
    const page = await api(path);
    results.push(...page.results);
    path = page.next;
  }
  return results;
}

export function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

export function link(text, href, className) {
  const anchor = element("a", text, className);
  anchor.href = href;
  return anchor;
}

export function showError(container, error, fallback) {
  const data = error.data || {};
  const parts = [];
  for (const value of Object.values(data.errors || data)) {
    if (Array.isArray(value)) parts.push(...value);
  }
  container.textContent = data.message || parts.join(" ") || data.detail || fallback;
  container.hidden = false;
}

const dateTime = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit",
});

export function formatDateTime(value) {
  return value ? dateTime.format(new Date(value)) : "—";
}
