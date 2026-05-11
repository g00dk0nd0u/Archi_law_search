const state = {
  source: "law",
  ready: false,
  hasSearched: false,
  selectedId: "",
  worker: null,
  lastTerms: [],
  recordsById: new Map(),
};

const els = {
  status: document.getElementById("status"),
  numberLabel: document.getElementById("number-label"),
  numberQuery: document.getElementById("number-query"),
  keywordQuery: document.getElementById("keyword-query"),
  lawFilterField: document.getElementById("law-filter-field"),
  lawTitleFilter: document.getElementById("law-title-filter"),
  searchButton: document.getElementById("search-button"),
  resultCount: document.getElementById("result-count"),
  results: document.getElementById("results"),
  tabs: Array.from(document.querySelectorAll(".source-option")),
  themeToggle: document.getElementById("theme-toggle"),
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

function renderInitialPrompt() {
  els.resultCount.textContent = "0件ヒット";
  els.results.innerHTML = '<div class="empty">条番号またはキーワードを入力して検索してください。</div>';
}

function populateLawTitleFilter(lawTitles) {
  const current = els.lawTitleFilter.value;
  els.lawTitleFilter.innerHTML = '<option value="">全法令</option>';
  for (const item of lawTitles || []) {
    const title = item.title || "";
    if (!title) {
      continue;
    }
    const option = document.createElement("option");
    option.value = title;
    option.textContent = title;
    els.lawTitleFilter.appendChild(option);
  }
  if (current && Array.from(els.lawTitleFilter.options).some((option) => option.value === current)) {
    els.lawTitleFilter.value = current;
  }
}

function updateThemeButton(theme) {
  const icon = els.themeToggle ? els.themeToggle.querySelector(".theme-toggle-icon") : null;
  if (!icon) {
    return;
  }
  if (theme === "dark") {
    icon.textContent = "☀";
    els.themeToggle.title = "ライトモードに切替";
    els.themeToggle.setAttribute("aria-label", "ライトモードに切替");
  } else {
    icon.textContent = "☾";
    els.themeToggle.title = "ダークモードに切替";
    els.themeToggle.setAttribute("aria-label", "ダークモードに切替");
  }
}

function applyTheme(theme, persist) {
  document.documentElement.dataset.theme = theme;
  updateThemeButton(theme);
  if (persist) {
    localStorage.setItem("archi-law-search-theme", theme);
  }
}

function initTheme() {
  const savedTheme = localStorage.getItem("archi-law-search-theme");
  const preferred = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  applyTheme(savedTheme === "light" || savedTheme === "dark" ? savedTheme : preferred, false);
  if (els.themeToggle) {
    els.themeToggle.addEventListener("click", () => {
      applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
    });
  }
}

function setSource(source) {
  state.source = source;
  const isLaw = source === "law";
  els.numberLabel.textContent = isLaw ? "条番号" : "告示番号";
  els.numberQuery.placeholder = isLaw ? "例: 112" : "例: 1436号";
  els.keywordQuery.placeholder = isLaw ? "例: 防火、容積率、準耐火" : "例: 排煙、防火設備、準不燃";
  els.lawFilterField.hidden = !isLaw;
  els.lawTitleFilter.disabled = !isLaw;
  els.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.source === source));
  clearExpandedRows();
  if (state.hasSearched) {
    runSearch();
  } else {
    renderInitialPrompt();
  }
}

function clearExpandedRows() {
  state.selectedId = "";
  Array.from(document.querySelectorAll(".result-row.expanded")).forEach((row) => {
    row.classList.remove("expanded");
    const record = state.recordsById.get(row.dataset.id);
    const bodyCell = row.querySelector(".body-cell");
    if (record && bodyCell) {
      bodyCell.innerHTML = bodyCellHtml(record, state.lastTerms, false);
    }
  });
}

function tableHeadHtml(source) {
  if (source === "law") {
    return "<thead><tr><th>法令</th><th>条</th><th>本文</th></tr></thead>";
  }
  return "<thead><tr><th>告示番号</th><th>告示名</th><th>本文</th><th>リンク</th></tr></thead>";
}

function renderResults(results, terms) {
  state.recordsById = new Map(results.map((item) => [item.id, item]));
  els.resultCount.textContent = `${results.length}件ヒット`;
  els.results.innerHTML = "";

  if (!results.length) {
    els.results.innerHTML = '<div class="empty">該当する結果が見つかりませんでした。検索語を変えて再度お試しください。</div>';
    return;
  }

  const table = document.createElement("table");
  table.className = state.source === "law" ? "result-table law-table" : "result-table kokuji-table";
  table.innerHTML = `${tableHeadHtml(state.source)}<tbody></tbody>`;
  const tbody = table.querySelector("tbody");
  for (const item of results) {
    tbody.appendChild(buildRow(item, terms));
  }
  els.results.appendChild(table);
}

function buildRow(item, terms) {
  const row = document.createElement("tr");
  row.className = "result-row";
  row.dataset.id = item.id;
  row.innerHTML = item.source === "law" ? lawRowHtml(item, terms) : kokujiRowHtml(item, terms);
  row.addEventListener("click", (event) => {
    if (event.target.closest("a")) {
      return;
    }
    if (row.classList.contains("expanded")) {
      row.classList.remove("expanded");
      const bodyCell = row.querySelector(".body-cell");
      if (bodyCell) {
        bodyCell.innerHTML = bodyCellHtml(item, state.lastTerms, false);
      }
      state.selectedId = "";
      return;
    }
    loadBody(item);
  });
  return row;
}

function lawRowHtml(item, terms) {
  const article = `${item.article_number}${item.article_title || ""}`;
  return `
    <td class="law">${highlight(item.law_title || "", terms)}</td>
    <td class="article">${highlight(article, terms)}</td>
    <td class="body body-cell">${bodyCellHtml(item, terms, false)}</td>
  `;
}

function kokujiRowHtml(item, terms) {
  const number = item.document_number_norm || item.document_number || "";
  const link = item.url
    ? `<a class="kokuji-link-button" href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.link_label || "LINK")}</a>`
    : "";
  const meta = [item.document_date, item.organization].filter(Boolean).join(" / ");
  return `
    <td class="article kokuji-number">${highlight(number, terms)}</td>
    <td class="kokuji-name">${highlight(item.notice_name || "", terms)}${meta ? `<div class="kokuji-meta">${escapeHtml(meta)}</div>` : ""}</td>
    <td class="body body-cell">${bodyCellHtml(item, terms, false)}</td>
    <td class="kokuji-link-cell">${link}</td>
  `;
}

function bodyCellHtml(item, terms, expanded, body = "") {
  const text = expanded ? body : item.preview || "";
  const className = expanded ? "body-full" : "body-preview";
  return `<div class="body-wrap"><div class="${className}">${highlight(text, terms)}</div></div>`;
}

function renderBody(item, body) {
  state.selectedId = item.id;
  Array.from(document.querySelectorAll(".result-row.expanded")).forEach((row) => {
    if (row.dataset.id !== item.id) {
      row.classList.remove("expanded");
      const record = state.recordsById.get(row.dataset.id);
      const bodyCell = row.querySelector(".body-cell");
      if (record && bodyCell) {
        bodyCell.innerHTML = bodyCellHtml(record, state.lastTerms, false);
      }
    }
  });

  const row = document.querySelector(`.result-row[data-id="${CSS.escape(item.id)}"]`);
  if (!row) {
    return;
  }
  row.classList.add("expanded");
  const bodyCell = row.querySelector(".body-cell");
  if (bodyCell) {
    bodyCell.innerHTML = bodyCellHtml(item, state.lastTerms, true, body);
  }
}

function runSearch() {
  if (!state.ready) {
    return;
  }
  state.hasSearched = true;
  setStatus("検索中");
  clearExpandedRows();
  state.worker.postMessage({
    type: "search",
    source: state.source,
    numberQuery: els.numberQuery.value,
    keywordQuery: els.keywordQuery.value,
    lawTitleFilter: state.source === "law" ? els.lawTitleFilter.value : "",
    limit: 100,
  });
}

function loadBody(item) {
  setStatus("本文読み込み中");
  state.worker.postMessage({ type: "body", source: state.source, id: item.id });
}

function initWorker() {
  try {
    state.worker = new Worker("search-worker.js?v=3856927");
  } catch (error) {
    setStatus("Workerを起動できません");
    els.results.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    return;
  }

  state.worker.addEventListener("message", (event) => {
    const message = event.data || {};
    if (message.type === "ready") {
      state.ready = true;
      populateLawTitleFilter(message.lawTitles || []);
      setStatus(`読み込み完了 法令${message.counts.law}件 / 告示${message.counts.kokuji}件`);
      renderInitialPrompt();
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
els.lawTitleFilter.addEventListener("change", () => {
  if (state.hasSearched) {
    runSearch();
  }
});
[els.numberQuery, els.keywordQuery].forEach((input) => {
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      runSearch();
    }
  });
});

initTheme();
initWorker();
