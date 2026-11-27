import {allPages, api, element, formatDateTime, link, showError} from "/static/api.js";

const page = document.querySelector("[data-staff-page]");
const select = (selector) => page.querySelector(selector);
const collections = "/api/v1/applications/";
const listPath = "/staff/applications/";
const mailDeliveryPath = "/staff/mail-deliveries/";
const id = page.dataset.id;
const detailApi = id ? collections + id + "/" : null;
const error = select("[data-error]");

function handleFailure(failure, fallback) {
  if (failure.status === 403 && page.dataset.staffPage !== "login") {
    location.assign("/staff/login/?next=" + encodeURIComponent(location.pathname + location.search));
    return;
  }
  showError(error, failure, fallback);
}

function handleSubmit(form, task) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    error.hidden = true;
    try {
      await task(Object.fromEntries(new FormData(form)));
    } catch (failure) {
      handleFailure(failure, "요청을 처리하지 못했습니다. 다시 시도해 주세요.");
    } finally {
      if (button) button.disabled = false;
    }
  });
}

function localStaffTarget(value) {
  if (!value) return "/staff/";
  const target = new URL(value, location.origin);
  return target.origin === location.origin && target.pathname.startsWith("/staff/") ? target.href : "/staff/";
}

const logout = document.querySelector("[data-logout]");
if (logout) {
  handleSubmit(logout, async () => {
    await api("/api/v1/session/logout/", {method: "POST"});
    location.assign("/staff/login/");
  });
}

function completion(application) {
  if (application.completed_at) return formatDateTime(application.completed_at);
  return application.status === "COMPLETED" ? "기록 없음" : "—";
}

function receiptCell(id) {
  const receipt = element("td", undefined, "staff-receipt");
  const anchor = link(undefined, listPath + id + "/");
  anchor.append(element("code", id));
  receipt.append(anchor);
  return receipt;
}

function applicationRow(application) {
  const row = element("tr");
  row.append(
    receiptCell(application.id),
    element("td", application.course_title),
    element("td", application.name, "staff-name"),
    element("td", application.email, "staff-email"),
    element("td", application.status_label),
    element("td", application.contact_date),
    element("td", formatDateTime(application.created_at)),
    element("td", completion(application)),
  );
  return row;
}

function mailDeliveryRow(delivery) {
  const row = element("tr");
  const status = element("td");
  status.append(link(delivery.status_label, mailDeliveryPath + delivery.id + "/"));
  row.append(
    receiptCell(delivery.application_id),
    element("td", delivery.course_title),
    element("td", delivery.current_recipient_email, "staff-email"),
    element("td", delivery.kind_label),
    status,
    element("td", formatDateTime(delivery.scheduled_at)),
    element("td", formatDateTime(delivery.sent_at)),
    element("td", formatDateTime(delivery.next_attempt_at)),
    element("td", delivery.attempt_count),
    element("td", delivery.last_error_code || "—"),
  );
  return row;
}

function populateCourses(selectBox, courses, publishedOnly = false) {
  for (const course of courses) {
    if (publishedOnly && !course.is_published) continue;
    const option = element("option", course.title);
    option.value = course.slug;
    selectBox.append(option);
  }
}

function loadTable({
  endpoint, path, renderRow, columns, emptyMessage, filteredMessage, failureMessage, prepareForm,
}) {
  const form = select("[data-staff-filters]");
  const nav = select("[data-pages]");
  const rows = select("[data-rows]");
  const count = select("[data-count]");
  let pending;
  const formReady = prepareForm?.(form);

  async function refresh(url, updateHistory) {
    pending?.abort();
    const controller = new AbortController();
    pending = controller;
    error.hidden = true;
    try {
      const data = await api(endpoint + url.search, {
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      const items = data.results.map(renderRow);
      if (!items.length) {
        const row = element("tr");
        const filtered = [...url.searchParams].some(([key, value]) => key !== "page" && value);
        const cell = element("td", filtered ? filteredMessage : emptyMessage);
        cell.colSpan = columns;
        row.append(cell);
        items.push(row);
      }
      rows.replaceChildren(...items);
      count.textContent = "총 " + data.count + "건";
      nav.replaceChildren();
      if (data.previous) nav.append(link("이전", path + new URL(data.previous).search));
      if (data.next) nav.append(link("다음", path + new URL(data.next).search));
      nav.hidden = !data.previous && !data.next;
      if (updateHistory) history.pushState(null, "", url);
    } catch (failure) {
      if (failure.name === "AbortError") return;
      handleFailure(failure, failureMessage);
    }
  }

  async function loadFromAddress() {
    const url = new URL(location.href);
    await formReady;
    for (const field of form.elements) {
      if (field.name) field.value = url.searchParams.get(field.name) || "";
    }
    await refresh(url, false);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const url = new URL(path, location.origin);
    for (const [key, value] of new FormData(form)) {
      if (value) url.searchParams.set(key, value);
    }
    refresh(url, true);
  });
  nav.addEventListener("click", (event) => {
    const anchor = event.target.closest("a");
    if (!anchor || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    refresh(new URL(anchor.href), true);
  });
  window.addEventListener("popstate", loadFromAddress);
  return loadFromAddress();
}

function setupSheetsExport() {
  const button = select("[data-export]");
  if (!button) return;
  const result = select("[data-export-result]");
  button.addEventListener("click", async () => {
    button.disabled = true;
    error.hidden = true;
    result.hidden = true;
    try {
      const filters = new URLSearchParams(location.search);
      filters.delete("page");
      const {count, sheet_url} = await api(collections + "export/?" + filters, {method: "POST"});
      const sheet = link("Google Sheets 열기", sheet_url);
      sheet.target = "_blank";
      sheet.rel = "noopener";
      result.replaceChildren(`${count}건을 내보냈습니다. `, sheet);
      result.hidden = false;
    } catch (failure) {
      handleFailure(failure, "신청 목록을 내보내지 못했습니다.");
    } finally {
      button.disabled = false;
    }
  });
}

function fillDetails(values) {
  for (const node of page.querySelectorAll("[data-value]")) {
    node.textContent = values[node.dataset.value] ?? "—";
  }
  select("[data-detail]").hidden = false;
}

async function load() {
  const kind = page.dataset.staffPage;
  if (kind === "login") {
    handleSubmit(select("form"), async (data) => {
      await api("/api/v1/session/login/", {method: "POST", data});
      location.assign(localStaffTarget(new URLSearchParams(location.search).get("next")));
    });
    return;
  }
  if (kind === "list") {
    setupSheetsExport();
    return loadTable({
      endpoint: collections + "staff-results/",
      path: listPath,
      renderRow: applicationRow,
      columns: 8,
      emptyMessage: "아직 등록된 신청이 없습니다.",
      filteredMessage: "선택한 조건에 맞는 신청이 없습니다.",
      failureMessage: "신청 목록을 불러오지 못했습니다. 다시 조회해 주세요.",
      async prepareForm(form) {
        api("/api/v1/session/").then((session) => {
          select("[data-add]").hidden = !session.permissions.add;
        }).catch(() => {});
        populateCourses(form.elements.course, await allPages("/api/v1/courses/staff-choices/"));
      },
    });
  }
  if (kind === "mail-deliveries") {
    return loadTable({
      endpoint: collections + "reminders/",
      path: mailDeliveryPath,
      renderRow: mailDeliveryRow,
      columns: 10,
      emptyMessage: "아직 기록된 메일 발송 예약이 없습니다.",
      filteredMessage: "선택한 조건에 맞는 발송 기록이 없습니다.",
      failureMessage: "메일 발송 목록을 불러오지 못했습니다. 다시 조회해 주세요.",
    });
  }
  if (kind === "mail-delivery-detail") {
    const delivery = await api(collections + "reminders/" + id + "/");
    const receipt = select("[data-application-link]");
    receipt.href = listPath + delivery.application_id + "/";
    receipt.textContent = delivery.application_id;
    fillDetails({
      ...delivery,
      scheduled_at: formatDateTime(delivery.scheduled_at),
      sent_at: formatDateTime(delivery.sent_at),
      next_attempt_at: formatDateTime(delivery.next_attempt_at),
      last_error_code: delivery.last_error_code || "—",
    });
    return;
  }
  if (kind === "home") {
    const summary = await api(collections + "summary/");
    for (const item of [{label: "전체 신청", total: summary.total}, ...summary.statuses]) {
      const card = link(undefined, item.status ? listPath + "?status=" + item.status : listPath, "card staff-summary-card");
      card.append(element("span", item.label), element("strong", item.total + "건"));
      select("[data-summary]").append(card);
    }
    return;
  }

  const form = select("form");
  if (kind === "create") {
    populateCourses(form.elements.course_slug, await allPages("/api/v1/courses/staff-choices/"), true);
    let submission = crypto.randomUUID();
    handleSubmit(form, async (data) => {
      try {
        const application = await api(collections + "staff-create/", {
          method: "POST", data: {...data, submission_id: submission},
        });
        location.assign(listPath + application.id + "/");
      } catch (failure) {
        if (failure.data?.code === "SUBMISSION_CONFLICT") submission = crypto.randomUUID();
        throw failure;
      }
    });
    form.hidden = false;
    return;
  }

  const application = await api(detailApi);
  if (kind === "detail") {
    const mailStatus = select("[data-mail-status]");
    const delivery = application.latest_mail_delivery;
    if (mailStatus && delivery) {
      mailStatus.append(link(delivery.status_label, mailDeliveryPath + delivery.id + "/"));
    } else if (mailStatus) {
      mailStatus.textContent = "발송 내역 없음";
    }
    fillDetails({
      ...application,
      created_at: formatDateTime(application.created_at),
      completed_at: completion(application),
    });
    const session = await api("/api/v1/session/");
    select("[data-edit]").hidden = !session.permissions.change;
    select("[data-delete]").hidden = !session.permissions.delete;
  } else if (kind === "edit") {
    select("#application-receipt").value = application.id;
    select("#application-course").value = application.course_title;
    for (const field of form.elements) {
      if (field.name) field.value = application[field.name];
    }
    handleSubmit(form, async (data) => {
      await api(detailApi, {method: "PATCH", data});
      location.assign(listPath + id + "/");
    });
    form.hidden = false;
  } else {
    select("[data-course-title]").textContent = application.course_title;
    handleSubmit(form, async () => {
      await api(detailApi, {method: "DELETE"});
      location.assign(listPath);
    });
    form.hidden = false;
  }
}

load().catch((failure) => {
  handleFailure(failure, "화면을 불러오지 못했습니다.");
}).finally(() => {
  const loading = select("[data-loading]");
  if (loading) loading.hidden = true;
});
