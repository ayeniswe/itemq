"use strict";

document.body.addEventListener("htmx:confirm", (event) => {
  const detail = event.detail;
  if (!detail || !detail.question) return;

  event.preventDefault();

  if (window.confirm(detail.question)) {
    detail.issueRequest();
  }
});
