const state = {
  source: "law",
  ready: false,
  selectedId: "",
  worker: null,
  lastTerms: [],
};

const els = {
  status: document.getElementById("status"),
  numberLabel: document.getElementById("number-label"),
  numberQuery: document.getElementById("number-query"),
  keywordQuery: document.getElementById("keyword-query"),
  searchButton: document.getElementById("search-button"),
  clearButton: document.getElementById("clear-button"),
  resultCount: document.getElementById("result-count"),
  results: document.getElementById("results"),
  bodyTitle: document.getElementById("body-title"),
  bodyText: document.getElementById("body-text"),
  sourceLink: document.getElementById("source-link"),
  tabs: Array.from(document.querySelectorAll(".source-tab")),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function highlight(value, terms) {
  let html = escapeHtml(value);
  const uniqueTerms = Array.from(new Set(terms.filter(Boolean))).sort((a, b) => b.length - a.length);
  for (const term of uniqueTerms) {
    const escaped = escapeHtml(term).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    html = html.replace(new RegExp(escaped, "gi"), (match) => `<mark>${match}</mark>`);
  }
  return html;
}

function setStatus(text) {
  els.status.textContent = text;
}

function setSource(source) {
  state.source = source;
  els.numberLabel.textContent = source === "law" ? "条番号" : "告示番号";
  els.numberQuery.placeholder = source === "law" ? "例: 第五十二条" : "例: 1436号";
  els.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.source === source));
  clearBody();
  runSearch();
}

function clearBody() {
  state.selectedId = "";
  els.bodyTitle.textContent = "検索結果を選択してください。";
  els.bodyText.textContent = "";
  els.sourceLink.hidden = true;
  els.sourceLink.removeAttribute("href");
}

function renderResults(results, terms) {
  els.resultCount.textContent = `${results.length}件`;
  els.results.innerHTML = "";

  if (!results.length) {
    els.results.innerHTML = '<div class="empty">検索結果はありません。</div>';
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const item of results) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `result-item${item.id === state.selectedId ? " selected" : ""}`;
    button.dataset.id = item.id;
    button.innerHTML = resultHtml(item, terms);
    button.addEventListener("click", () => loadBody(item));
    fragment.appendChild(button);
  }
  els.results.appendChild(fragment);
}

function resultHtml(item, terms) {
  if (item.source === "law") {
    const title = `${item.law_title} ${item.article_number}${item.article_title || ""}`;
    return `
      <span class="result-title">${highlight(title, terms)}</span>
      <span class="result-meta">${escapeHtml(item.provision_kind || "")} ${escapeHtml(item.provision_context || "")}</span>
      <span class="result-preview">${highlight(item.preview || "", terms)}</span>
    `;
  }

  const number = item.document_number_norm || item.document_number || "";
  const title = `${number} ${item.notice_name || ""}`.trim();
  const meta = [item.document_date, item.organization, item.link_label].filter(Boolean).join(" / ");
  return `
    <span class="result-title">${highlight(title, terms)}</span>
    <span class="result-meta">${escapeHtml(meta)}</span>
    <span class="result-preview">${highlight(item.preview || "", terms)}</span>
  `;
}

function renderBody(item, body) {
  state.selectedId = item.id;
  els.bodyTitle.innerHTML = resultHtml(item, state.lastTerms);
  els.bodyText.innerHTML = highlight(body, state.lastTerms);
  if (item.url) {
    els.sourceLink.href = item.url;
    els.sourceLink.hidden = false;
  } else {
    els.sourceLink.hidden = true;
    els.sourceLink.removeAttribute("href");
  }
  Array.from(document.querySelectorAll(".result-item")).forEach((button) => {
    button.classList.toggle("selected", button.dataset.id === item.id);
  });
}

function runSearch() {
  if (!state.ready) {
    return;
  }
  setStatus("検索中");
  clearBody();
  state.worker.postMessage({
    type: "search",
    source: state.source,
    numberQuery: els.numberQuery.value,
    keywordQuery: els.keywordQuery.value,
    limit: 100,
  });
}

function loadBody(item) {
  setStatus("本文読み込み中");
  state.worker.postMessage({ type: "body", source: state.source, id: item.id });
}

function initWorker() {
  try {
    state.worker = new Worker("search-worker.js");
  } catch (error) {
    setStatus("Workerを起動できません");
    els.results.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    return;
  }

  state.worker.addEventListener("message", (event) => {
    const message = event.data || {};
    if (message.type === "ready") {
      state.ready = true;
      setStatus(`読み込み完了 法令${message.counts.law}件 / 告示${message.counts.kokuji}件`);
      runSearch();
      return;
    }
    if (message.type === "results") {
      state.lastTerms = message.terms || [];
      setStatus("検索完了");
      renderResults(message.results || [], state.lastTerms);
      return;
    }
    if (message.type === "body") {
      setStatus("本文表示中");
      renderBody(message.record, message.body || "");
      return;
    }
    if (message.type === "error") {
      setStatus("読み込みエラー");
      els.results.innerHTML = `<div class="empty">${escapeHtml(message.message)}</div>`;
    }
  });

  state.worker.postMessage({ type: "init" });
}

els.tabs.forEach((tab) => {
  tab.addEventListener("click", () => setSource(tab.dataset.source));
});
els.searchButton.addEventListener("click", runSearch);
els.clearButton.addEventListener("click", () => {
  els.numberQuery.value = "";
  els.keywordQuery.value = "";
  clearBody();
  runSearch();
});
[els.numberQuery, els.keywordQuery].forEach((input) => {
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      runSearch();
    }
  });
});

initWorker();
