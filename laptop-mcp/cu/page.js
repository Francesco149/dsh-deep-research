// Runs in the "cu" isolated world of the agent browser's page (cu/browser.py). It shares the DOM
// with the page but not its JavaScript: nothing here is visible to the page's scripts, and the
// page cannot patch what this code calls. Read-only: it never changes the DOM.
var cu = (() => {
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "CANVAS", "IFRAME", "OBJECT", "EMBED", "HEAD", "META", "LINK"]);
  const BLOCK = new Set(["P", "DIV", "SECTION", "ARTICLE", "MAIN", "HEADER", "FOOTER", "ASIDE", "NAV", "FORM", "FIELDSET",
    "FIGURE", "FIGCAPTION", "DETAILS", "SUMMARY", "BLOCKQUOTE", "DL", "DT", "DD", "ADDRESS", "CENTER", "HR", "BR"]);
  const INTERACTIVE = 'a[href],button,input:not([type=hidden]),select,textarea,summary,label[for],[role=button],[role=link],' +
    '[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=option],[role=switch],[role=combobox],[role=searchbox],' +
    '[role=textbox],[contenteditable=""],[contenteditable=true],[onclick],[tabindex]:not([tabindex="-1"])';
  // What a match inside should be lifted to: real controls, not any focusable container.
  const CLICKABLE = 'a[href],button,input:not([type=hidden]),select,textarea,summary,label,[role=button],[role=link],' +
    '[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=option],[role=switch]';
  const clean = (s) => String(s ?? "").replace(/\s+/g, " ").trim();  // .value can be a number (li, meter)
  const visible = (el) => (el.checkVisibility ? el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) : !!el.offsetParent);
  const abs = (href) => { try { return new URL(href, document.baseURI).href; } catch { return href; } };
  // Open shadow roots (web components: archive.org's and Reddit's sign-in forms) are part of the
  // page a person sees. deep() walks the composed tree: an element, its shadow tree, its children.
  function* deep(root) {
    for (let el = root.firstElementChild; el; el = el.nextElementSibling) {
      yield el;
      if (el.shadowRoot) yield* deep(el.shadowRoot);
      yield* deep(el);
    }
  }
  const holds = (a, b) => { for (let n = b; n; n = n.parentNode || n.host) if (n === a) return true; return false; };
  const topAt = (x, y) => {
    let t = document.elementFromPoint(x, y);
    for (let u; t && t.shadowRoot && (u = t.shadowRoot.elementFromPoint(x, y)) && u !== t;) t = u;
    return t;
  };
  const focusedEl = () => {
    let a = document.activeElement;
    while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
    return a;
  };

  function toMarkdown(root) {
    const out = [];
    const walk = (node, ctx) => {
      if (node.nodeType === Node.TEXT_NODE) {
        const t = node.nodeValue.replace(/\s+/g, " ");
        if (t.trim() || (t === " " && out.length && !out[out.length - 1].endsWith(" "))) out.push(ctx.pre ? node.nodeValue : t);
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const el = node, tag = el.tagName.toUpperCase();
      if (SKIP.has(tag) || el.getAttribute("aria-hidden") === "true") return;
      // display: contents has no box of its own, so checkVisibility() is false while its children show
      // (2026-10-24: Ubisoft's help articles read as 0 characters, Business Wire's newsroom without its list)
      if (tag !== "BR" && !visible(el) && tag !== "DETAILS" && getComputedStyle(el).display !== "contents") return;
      if (el.shadowRoot) { for (const c of el.shadowRoot.childNodes) walk(c, ctx); }
      const kids = () => { for (const c of el.childNodes) walk(c, ctx); };
      const h = /^H([1-6])$/.exec(tag);
      if (h) { out.push("\n\n" + "#".repeat(+h[1]) + " "); kids(); out.push("\n\n"); return; }
      switch (tag) {
        case "BR": out.push("\n"); return;
        case "HR": out.push("\n\n---\n\n"); return;
        case "A": {
          const href = el.getAttribute("href");
          const start = out.length; kids();
          const text = clean(out.splice(start).join(""));
          if (!text) return;
          if (!href || href.startsWith("javascript:") || href === "#") { out.push(text); return; }
          out.push(`[${text}](${abs(href)})`); return;
        }
        case "IMG": { const alt = clean(el.alt); if (alt) out.push(`![${alt}]`); return; }
        case "PRE": {
          const c = { ...ctx, pre: true };
          out.push("\n\n```\n"); for (const k of el.childNodes) walk(k, c); out.push("\n```\n\n"); return;
        }
        case "CODE": if (!ctx.pre) { out.push("`"); kids(); out.push("`"); return; } break;
        case "STRONG": case "B": out.push("**"); kids(); out.push("**"); return;
        case "EM": case "I": out.push("_"); kids(); out.push("_"); return;
        case "LI": out.push("\n" + "  ".repeat(ctx.depth || 0) + (ctx.ol ? `${ctx.n++}. ` : "- ")); kids(); return;
        case "UL": case "OL": {
          const c = { ...ctx, depth: (ctx.depth ?? -1) + 1, ol: tag === "OL", n: 1 };
          out.push("\n"); for (const k of el.childNodes) walk(k, c); out.push("\n"); return;
        }
        case "TR": {
          const cells = [...el.children].filter((c) => c.tagName === "TD" || c.tagName === "TH");
          out.push("\n| " + cells.map((c) => clean(c.innerText).replace(/\|/g, "\\|")).join(" | ") + " |");
          if (cells.length && cells.every((c) => c.tagName === "TH")) out.push("\n|" + " --- |".repeat(cells.length));
          return;
        }
        case "TABLE": out.push("\n"); kids(); out.push("\n\n"); return;
        case "INPUT": case "TEXTAREA": case "SELECT": {
          const label = clean(el.getAttribute("aria-label") || el.placeholder || el.name);
          out.push(` [${tag.toLowerCase()}${label ? ": " + label : ""}${el.value && el.type !== "password" ? " = " + clean(el.value).slice(0, 80) : ""}] `);
          return;
        }
      }
      const block = BLOCK.has(tag) || ["block", "flex", "grid", "list-item", "table"].includes(getComputedStyle(el).display);
      if (block) out.push("\n");
      kids();
      if (block) out.push("\n");
    };
    walk(root, {});
    return out.join("").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").replace(/^ +/gm, (m) => m.length > 1 ? m : "").trim();
  }

  function geometry() {
    return { sx: screenX, sy: screenY, ow: outerWidth, oh: outerHeight, iw: innerWidth, ih: innerHeight,
      dpr: devicePixelRatio, scroll_y: scrollY, doc_h: document.documentElement.scrollHeight };
  }

  // A password field's value never leaves the page: not as a label, a match, or a read-back.
  const secret = (el) => el.tagName === "INPUT" && el.type === "password";
  const shown = (el) => (secret(el) ? "" : el.value);

  function describe(el) {
    const tag = el.tagName.toLowerCase();
    const label = clean(el.getAttribute("aria-label") || el.innerText || shown(el) || el.placeholder || el.title || el.alt ||
      (el.querySelector && el.querySelector("img[alt]")?.alt) || el.name || "").slice(0, 100);
    const d = { tag, label };
    const role = el.getAttribute("role"); if (role) d.role = role;
    if (tag === "a") d.href = abs(el.getAttribute("href"));
    if (tag === "input") d.type = el.type;
    if (el.disabled) d.disabled = true;
    return d;
  }

  function box(el) {
    const r = el.getBoundingClientRect();
    const cx = Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 2), cy = Math.min(Math.max(r.top + r.height / 2, 1), innerHeight - 2);
    const top = topAt(cx, cy);
    return { x: cx, y: cy, w: r.width, h: r.height, in_view: r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth,
      covered: !(top && (holds(el, top) || holds(top, el))) };
  }

  let els = [];

  return {
    state() {
      const frames = [...document.querySelectorAll("iframe")].map((f) => f.src || "").join(" ");
      const rc = document.querySelector('iframe[src*="recaptcha"][title*="challenge"]');
      return { url: location.href, title: document.title, ready: document.readyState, frames, content_type: document.contentType,
        recaptcha_visible: !!(rc && rc.getBoundingClientRect().height > 50), text_head: clean(document.body?.innerText).slice(0, 300) };
    },
    geometry,
    textLength() { return document.body ? document.body.innerText.length : 0; },
    read(offset = 0, max = 20000, mainOnly = false) {
      const root = (mainOnly && (document.querySelector("main, article, [role=main]"))) || document.body;
      const md = root ? toMarkdown(root) : "";
      return { url: location.href, title: document.title, total: md.length, offset, text: md.slice(offset, offset + max),
        next: offset + max < md.length ? offset + max : null };
    },
    // Numbers what can be clicked or typed into, in the viewport by default; the numbers stay valid
    // for point() until the next elements() call.
    elements(all = false) {
      els = [];
      const out = [];
      for (const el of deep(document)) {
        if (!el.matches(INTERACTIVE) || !visible(el)) continue;
        const b = box(el);
        if (b.w < 3 || b.h < 3 || (!all && !b.in_view)) continue;
        els.push(el);
        out.push({ i: els.length - 1, ...describe(el), x: Math.round(b.x), y: Math.round(b.y), in_view: b.in_view, covered: b.covered });
        if (out.length >= 400) break;
      }
      return { geometry: geometry(), elements: out };
    },
    // Visible elements whose text contains `text` (case-insensitive). Only the innermost matches
    // count (a dialog containing the button is not a hit), each lifted to the clickable element
    // around it; clickable hits come first.
    find(text, limit = 10) {
      const needle = clean(text).toLowerCase();
      const matches = [];
      for (const el of deep(document.body)) {
        if (SKIP.has(el.tagName) || !visible(el)) continue;
        const own = clean(el.innerText || shown(el) || el.placeholder || "").toLowerCase();
        const label = clean(el.getAttribute("aria-label") || el.title || "").toLowerCase();
        if (own.includes(needle) || label.includes(needle)) matches.push(el);
      }
      const inner = matches.filter((el) => !matches.some((o) => o !== el && holds(el, o)));
      const targets = [...new Set(inner.map((el) => el.closest(CLICKABLE) || el))];
      const area = (el) => { const r = el.getBoundingClientRect(); return r.width * r.height; };
      targets.sort((a, b) => (b.matches(CLICKABLE) - a.matches(CLICKABLE)) || (area(a) - area(b)));
      const hits = [];
      for (const target of targets.slice(0, limit)) {
        els.push(target);
        hits.push({ i: els.length - 1, ...describe(target), ...box(target) });
      }
      return { geometry: geometry(), elements: hits };
    },
    point(i, scroll = true) {
      const el = els[i];
      if (!el || !el.isConnected) throw new Error(`element ${i} is gone: list elements again`);
      let b = box(el);
      if (scroll && (!b.in_view || b.covered)) {
        el.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
        b = box(el);
      }
      return { ...b, geometry: geometry(), ...describe(el) };
    },
    value(i) {
      const el = els[i];
      return el ? (secret(el) ? `[${el.value.length} hidden characters]` : (el.value ?? el.innerText)) : null;
    },
    // Element [i] (or the focused one, i null) and how many characters its value holds.
    field(i) {
      const el = i == null ? focusedEl() : els[i];
      if (!el || el === document.body) return null;
      return { ...describe(el), length: (el.value ?? "").length };
    },
    // Whether typing now reaches field [i]: it has the focus, or the page swapped it on click for its
    // own field of the same kind (Wikipedia's search box). A click can also land on something on top
    // of it (Chrome's autofill popup) and send the typing somewhere else: then false.
    focusOn(i) {
      const el = els[i], f = focusedEl();
      if (!el || !f || f === document.body) return false;
      if (f === el) return true;
      const editable = (e) => e.isContentEditable || e.tagName === "TEXTAREA" || (e.tagName === "INPUT" &&
        !["button", "submit", "reset", "image", "checkbox", "radio", "file", "hidden", "range", "color"].includes(e.type));
      return (!el.isConnected || !visible(el)) && editable(f) && secret(f) === secret(el);
    },
    focused() {
      const el = focusedEl();
      return el && el !== document.body ? describe(el) : null;
    },
    async fetchBase64() {
      const buf = await (await fetch(location.href, { credentials: "include" })).arrayBuffer();
      let s = "";
      const bytes = new Uint8Array(buf);
      for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      return btoa(s);
    },
  };
})();
