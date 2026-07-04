/** Map editor UI localization (separate from game concept / label-mode). */
(function () {
  const STORAGE_KEY = "vic3-map-ui-lang";
  const DEFAULT_LANG = "en";

  let uiLang = localStorage.getItem(STORAGE_KEY) || DEFAULT_LANG;
  let messages = {};
  const listeners = new Set();

  function normalizeLang(lang) {
    return lang === "en" ? "en" : "zh";
  }

  function t(key, params, fallback) {
    let s = messages[key];
    if (s == null) s = fallback != null ? fallback : key;
    if (params && typeof params === "object") {
      for (const [k, v] of Object.entries(params)) {
        s = String(s).replaceAll(`{${k}}`, v);
      }
    }
    return s;
  }

  function getUiLang() {
    return uiLang;
  }

  function applyPattern(pattern, template, text) {
    const m = text.match(pattern);
    if (!m) return null;
    let out = template;
    for (let i = 1; i < m.length; i += 1) {
      out = out.replaceAll(`{${i}}`, m[i]);
    }
    return out;
  }

  function translateMsg(text) {
    if (!text || uiLang === "zh") return text;
    const cfg = window.SERVER_I18N || {};
    const exact = cfg.exact || {};
    if (exact[text]) return exact[text];
    for (const [pattern, template] of cfg.patterns || []) {
      const translated = applyPattern(pattern, template, text);
      if (translated) return translated;
    }
    const labels = cfg.catalogLabels || {};
    for (const [zh, en] of Object.entries(labels)) {
      if (text.includes(zh)) return text.replaceAll(zh, en);
    }
    return text;
  }

  function loadMessages() {
    messages = (window.UI_MESSAGES && window.UI_MESSAGES[uiLang]) || {};
  }

  function setUiLang(lang) {
    uiLang = normalizeLang(lang);
    localStorage.setItem(STORAGE_KEY, uiLang);
    loadMessages();
    for (const sel of document.querySelectorAll(".ui-lang-select")) {
      sel.value = uiLang;
    }
    for (const fn of listeners) fn(uiLang);
  }

  function onUiLangChange(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  function applyStaticUi(root) {
    const scope = root || document;
    for (const el of scope.querySelectorAll("[data-i18n]")) {
      const key = el.getAttribute("data-i18n");
      if (!key) continue;
      el.textContent = t(key);
    }
    for (const el of scope.querySelectorAll("[data-i18n-placeholder]")) {
      const key = el.getAttribute("data-i18n-placeholder");
      if (key) el.placeholder = t(key);
    }
    for (const el of scope.querySelectorAll("[data-i18n-title]")) {
      const key = el.getAttribute("data-i18n-title");
      if (key) el.title = t(key);
    }
    const docTitleKey = document.documentElement.getAttribute("data-i18n-document-title");
    if (docTitleKey) document.title = t(docTitleKey);
  }

  function initUiLang() {
    loadMessages();
    for (const sel of document.querySelectorAll(".ui-lang-select")) {
      sel.value = uiLang;
      sel.addEventListener("change", () => setUiLang(sel.value));
    }
    applyStaticUi();
  }

  window.t = t;
  window.translateMsg = translateMsg;
  window.getUiLang = getUiLang;
  window.setUiLang = setUiLang;
  window.onUiLangChange = onUiLangChange;
  window.applyStaticUi = applyStaticUi;
  window.initUiLang = initUiLang;
})();
