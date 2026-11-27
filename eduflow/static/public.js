import {allPages, api, element, formatDateTime, link, showError} from "/static/api.js";

const page = document.querySelector("[data-public-page]");
const select = (selector) => page.querySelector(selector);

function cover(course, lazy = false) {
  if (course.image) {
    const image = element("img", undefined, "hero-art");
    image.src = course.image.url;
    image.alt = course.image.alt;
    if (lazy) image.loading = "lazy";
    return image;
  }
  const art = element("div", undefined, "hero-art artwork");
  art.setAttribute("role", "img");
  art.setAttribute("aria-label", "교육 대표 일러스트");
  for (const shape of ["circle", "sheet", "orbit", "star"]) {
    art.append(element("span", shape === "star" ? "✦" : undefined, "art-" + shape));
  }
  return art;
}

async function load() {
  if (page.dataset.publicPage === "catalog") {
    const courses = await allPages("/api/v1/courses/");
    const grid = select("[data-courses]");
    for (const course of courses) {
      const card = link(undefined, "/courses/" + encodeURIComponent(course.slug) + "/", "card catalog-card");
      const content = element("div", undefined, "catalog-card-content");
      const heading = element("h2", course.title);
      const arrow = element("span", "↗");
      arrow.setAttribute("aria-hidden", "true");
      heading.append(arrow);
      content.append(heading, element("p", course.tagline));
      card.append(cover(course, true), content);
      grid.append(card);
    }
    if (!courses.length) grid.append(element("p", "현재 공개된 교육이 없습니다."));
    return;
  }

  const slug = page.dataset.slug;
  const course = await api("/api/v1/courses/" + encodeURIComponent(slug) + "/");
  select("[data-title]").textContent = course.title;
  document.title = course.title + " · EduFlow";
  const open = course.intake.code === "OPEN";
  const intake = select("[data-intake]");
  if (!open) {
    intake.textContent = course.intake.label;
    intake.hidden = false;
  }
  if (page.dataset.publicPage === "course") {
    select("[data-tagline]").textContent = course.tagline;
    select("[data-image]").append(cover(course));
    select("[data-capacity]").textContent = course.capacity + "명";
    select("[data-deadline]").textContent = formatDateTime(course.application_deadline_at);
    const lessons = select("[data-curriculum]");
    for (const lesson of course.curriculum) lessons.append(element("li", lesson));
    if (!course.curriculum.length) lessons.append(element("li", "커리큘럼은 준비 중입니다."));
    const apply = select("[data-apply]");
    apply.href = "/courses/" + encodeURIComponent(slug) + "/apply/";
    apply.hidden = !open;
    select("[data-content]").hidden = false;
  } else if (open) {
    setupApplication(course);
  }
}

function setupApplication(course) {
  const form = select("[data-apply-form]");
  form.elements.contact_date.min = course.contact_date_min;
  form.hidden = false;
  let submissionId = crypto.randomUUID();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    const error = select("[data-form-error]");
    button.disabled = true;
    error.hidden = true;
    for (const field of form.querySelectorAll("[aria-invalid]")) {
      field.removeAttribute("aria-invalid");
    }
    const data = Object.fromEntries(new FormData(form));
    try {
      await api("/api/v1/applications/", {
        method: "POST",
        data: {...data, course_slug: course.slug, submission_id: submissionId},
      });
      form.hidden = true;
      const confirmation = select("[data-confirmation]");
      confirmation.hidden = false;
      confirmation.focus();
    } catch (failure) {
      const code = failure.data?.code;
      if (code === "SUBMISSION_CONFLICT") submissionId = crypto.randomUUID();
      for (const name of Object.keys(failure.data?.errors || {})) {
        form.elements.namedItem(name)?.setAttribute("aria-invalid", "true");
      }
      showError(error, failure, "신청 결과를 확인하지 못했습니다. 잠시 후 다시 제출해 주세요.");
    } finally {
      button.disabled = false;
    }
  });
}

load().catch((failure) => {
  const message = failure.status === 404 ? "교육을 찾을 수 없습니다." : "교육 정보를 불러오지 못했습니다.";
  showError(select("[data-error]"), failure.status === 404 ? {} : failure, message);
}).finally(() => {
  select("[data-loading]").hidden = true;
});
