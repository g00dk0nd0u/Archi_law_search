const indexes = {
  law: [],
  kokuji: [],
};

const bodyCache = new Map();

function tokenize(value) {
  return String(value || "")
    .trim()
    .split(/[\s\u3000]+/)
    .filter(Boolean);
}

function normalizeDigits(value) {
  return String(value || "").replace(/[０-９]/g, (char) =>
    String.fromCharCode(char.charCodeAt(0) - 0xfee0)
  );
}

function normalizeSearchText(value) {
  return normalizeDigits(value).toLowerCase();
}

function intToKanji(value) {
  const digits = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"];
  const units = [
    [1000, "千"],
    [100, "百"],
    [10, "十"],
    [1, ""],
  ];
  let number = Number(value);
  if (!Number.isFinite(number) || number <= 0) {
    return "";
  }
  let text = "";
  for (const [unit, label] of units) {
    const digit = Math.floor(number / unit);
    number %= unit;
    if (!digit) {
      continue;
    }
    text += unit > 1 && digit === 1 ? label : `${digits[digit]}${label}`;
  }
  return text;
}

function articleVariants(value) {
  const raw = normalizeDigits(String(value || "").trim());
  if (!raw) {
    return [];
  }
  const variants = new Set([raw]);
  if (!raw.startsWith("第")) {
    variants.add(`第${raw}`);
  }
  const match = raw
    .replace(/[－ー―]/g, "-")
    .match(/^(?:第)?(\d+)(?:条)?(?:[-の](\d+))?/);
  if (match) {
    const main = match[1];
    const branch = match[2] || "";
    const mainKanji = intToKanji(main);
    const branchKanji = branch ? intToKanji(branch) : "";
    variants.add(`第${main}条`);
    if (mainKanji) {
      variants.add(`第${mainKanji}条`);
    }
    if (branch) {
      variants.add(`第${main}条の${branch}`);
      if (mainKanji) {
        variants.add(`第${mainKanji}条の${branch}`);
      }
      if (mainKanji && branchKanji) {
        variants.add(`第${mainKanji}条の${branchKanji}`);
      }
    }
  }
  return Array.from(variants);
}

function numberMatches(record, source, numberQuery) {
  const raw = String(numberQuery || "").trim();
  if (!raw) {
    return true;
  }
  const normalized = normalizeSearchText(raw);
  if (source === "law") {
    const target = normalizeSearchText(record.article_number);
    return articleVariants(raw).some((variant) => target.startsWith(normalizeSearchText(variant)));
  }
  const digits = normalized.replace(/\D/g, "");
  const targets = [
    record.document_number,
    record.document_number_norm,
    record.document_number_digits,
    record.notice_name,
  ].map(normalizeSearchText);
  return targets.some((target) => target.includes(normalized)) ||
    Boolean(digits && targets.some((target) => target.includes(digits)));
}

function recordMetaText(record, source) {
  if (source === "law") {
    return [
      record.law_id,
      record.law_title,
      record.article_number,
      record.article_title,
      record.provision_kind,
      record.provision_context,
      record.preview,
    ].join(" ");
  }
  return [
    record.notice_name,
    record.document_number,
    record.document_number_norm,
    record.document_number_digits,
    record.document_date,
    record.organization,
    record.preview,
  ].join(" ");
}

async function loadIndex(source) {
  const response = await fetch(`data/${source === "law" ? "law" : "kokuji"}_index.json`);
  if (!response.ok) {
    throw new Error(`${response.url} を読み込めませんでした`);
  }
  const payload = await response.json();
  indexes[source] = payload.records || [];
}

async function loadBodyPath(path) {
  if (bodyCache.has(path)) {
    return bodyCache.get(path);
  }
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} を読み込めませんでした`);
  }
  const payload = await response.json();
  const bodies = payload.bodies || {};
  bodyCache.set(path, bodies);
  return bodies;
}

async function loadBody(record) {
  const bodies = await loadBodyPath(record.body_path);
  return bodies[record.id] || "";
}

async function ensureBodiesFor(source) {
  const paths = Array.from(new Set(indexes[source].map((record) => record.body_path).filter(Boolean)));
  await Promise.all(paths.map(loadBodyPath));
}

function cachedBody(record) {
  const bodies = bodyCache.get(record.body_path);
  return bodies ? bodies[record.id] || "" : "";
}

async function search(source, numberQuery, keywordQuery, limit) {
  const terms = tokenize(keywordQuery);
  if (terms.length) {
    await ensureBodiesFor(source);
  }

  const normalizedTerms = terms.map(normalizeSearchText);
  const results = [];
  for (const record of indexes[source]) {
    if (!numberMatches(record, source, numberQuery)) {
      continue;
    }
    if (normalizedTerms.length) {
      const haystack = normalizeSearchText(`${recordMetaText(record, source)} ${cachedBody(record)}`);
      if (!normalizedTerms.every((term) => haystack.includes(term))) {
        continue;
      }
    }
    results.push({ ...record, source });
    if (results.length >= limit) {
      break;
    }
  }
  return { results, terms: [...tokenize(numberQuery), ...terms] };
}

self.addEventListener("message", async (event) => {
  const message = event.data || {};
  try {
    if (message.type === "init") {
      await Promise.all([loadIndex("law"), loadIndex("kokuji")]);
      self.postMessage({
        type: "ready",
        counts: { law: indexes.law.length, kokuji: indexes.kokuji.length },
      });
      return;
    }
    if (message.type === "search") {
      const payload = await search(
        message.source || "law",
        message.numberQuery || "",
        message.keywordQuery || "",
        Number(message.limit || 100)
      );
      self.postMessage({ type: "results", ...payload });
      return;
    }
    if (message.type === "body") {
      const source = message.source || "law";
      const record = indexes[source].find((item) => item.id === message.id);
      if (!record) {
        throw new Error("本文レコードが見つかりません");
      }
      const body = await loadBody(record);
      self.postMessage({ type: "body", record: { ...record, source }, body });
    }
  } catch (error) {
    self.postMessage({ type: "error", message: error.message || String(error) });
  }
});
