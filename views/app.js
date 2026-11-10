"use strict";
/* Airglide single-page app. Talks to Python through window.pywebview.api;
   Python pushes events through ag.emit(kind, payload). */

// ---- tiny DOM helpers ---------------------------------------------------
function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
        if (v == null || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "style") el.style.cssText = v;
        else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
        else if (k === "dataset") Object.assign(el.dataset, v);
        else if (v === true) el.setAttribute(k, "");
        else el.setAttribute(k, v);
    }
    append(el, kids);
    return el;
}
function append(el, ...kids) {
    for (const k of kids.flat(Infinity)) {
        if (k == null || k === false) continue;
        el.appendChild(typeof k === "string" || typeof k === "number" ? document.createTextNode(String(k)) : k);
    }
    return el;
}
function clear(el) { while (el && el.firstChild) el.removeChild(el.firstChild); return el; }
function replace(el, ...kids) { return append(clear(el), kids); }
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const store = {
    get(k, d) { try { const v = localStorage.getItem("ag." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("ag." + k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } },
};

// ---- formatting ---------------------------------------------------------
function fmtClock(s) {
    s = Math.max(0, Math.round(s || 0));
    const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
    return (hh ? hh + ":" + String(mm).padStart(2, "0") : String(mm).padStart(2, "0")) + ":" + String(ss).padStart(2, "0");
}
function fmtDur(s) {
    s = Math.round(s || 0);
    if (s < 60) return `${s} s`;
    const m = Math.floor(s / 60), r = s % 60;
    if (m < 60) return r && m < 10 ? `${m} min ${r} s` : `${m + (r >= 30 ? 1 : 0)} min`;
    const hh = Math.floor(m / 60), mm = m % 60;
    return mm ? `${hh} hr ${mm} min` : `${hh} hr`;
}
function fmtAgo(t) {
    const d = Date.now() / 1000 - t;
    if (d < 60) return "just now";
    if (d < 3600) return `${Math.floor(d / 60)} min ago`;
    if (d < 86400) return `${Math.floor(d / 3600)} hr ago`;
    return new Date(t * 1000).toLocaleDateString();
}
function deckTitle(name) { return (name || "").replace(/\.(pptx|pdf|docx|doc)$/i, ""); }
const KINDS = {
    pptx: { badge: "PPTX", color: "var(--orange)" },
    pdf: { badge: "PDF", color: "var(--red)" },
    docx: { badge: "DOCX", color: "var(--blue)" },
    doc: { badge: "DOC", color: "var(--blue)" },
    gslides: { badge: "SLIDES", color: "var(--amber)" },
};
function unitOne(entry) {
    const u = (entry && entry.unit) || "slides";
    return { slides: "Slide", pages: "Page", sections: "Section" }[u] || "Slide";
}
const ACCENTS = ["var(--blue)", "var(--green)", "var(--purple)", "var(--orange)", "var(--pink)", "var(--teal)"];
const accent = (i) => ACCENTS[i % ACCENTS.length];

// Simple, safe Markdown subset for chat replies (escape first).
function richText(text) {
    const frag = document.createDocumentFragment();
    let list = null;
    for (const raw of String(text).split("\n")) {
        const m = raw.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
        if (m) {
            if (!list) { list = h("ul"); frag.appendChild(list); }
            list.appendChild(inline(h("li"), m[1]));
            continue;
        }
        list = null;
        if (raw.trim()) frag.appendChild(inline(h("p"), raw));
    }
    return frag;
}
function inline(el, s) {
    const parts = s.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g);
    for (const p of parts) {
        if (/^\*\*[^*]+\*\*$/.test(p)) el.appendChild(h("strong", null, p.slice(2, -2)));
        else if (/^\*[^*]+\*$/.test(p)) el.appendChild(h("em", null, p.slice(1, -1)));
        else if (p) el.appendChild(document.createTextNode(p));
    }
    return el;
}

// ---- event bus (Python -> JS) ------------------------------------------
const ag = {
    handlers: {},
    on(kind, fn) { (this.handlers[kind] = this.handlers[kind] || []).push(fn); },
    emit(kind, payload) { for (const fn of this.handlers[kind] || []) { try { fn(payload); } catch (e) { console.error(e); } } },
};
window.ag = ag;
window.__errors = [];
window.addEventListener("error", (e) => window.__errors.push(String(e.message)));
window.addEventListener("unhandledrejection", (e) => window.__errors.push(String(e.reason)));

async function call(name, ...args) {
    try {
        return await window.pywebview.api[name](...args);
    } catch (e) {
        console.error(name, e);
        toast({ message: `Something went wrong (${name}). Details are in the log.`, level: "error" });
        return null;
    }
}

// ---- app state ---------------------------------------------------------
const S = {
    state: null,
    cfg: null,
    route: store.get("route", "home"),
    timelineMode: store.get("timeline", "list"),
    selected: null,
    settingsTab: "general",
    cameraOn: false,
    unseen: 0,
    chat: { log: [], busy: false },
    onboarding: null,
    liveBase: null,
};

const ROUTES = [
    { id: "home", label: "Dashboard", icon: "home" },
    { id: "gestures", label: "Gestures", icon: "hand" },
    { id: "mouse", label: "Virtual mouse", icon: "mouse" },
    { id: "assistant", label: "Assistant", icon: "sparkles" },
    { id: "library", label: "Presentations", icon: "folder" },
    { id: "settings", label: "Settings", icon: "settings" },
];

const POSE_FINGERS = {
    fist: [0, 0, 0, 0, 0], shaka: [1, 0, 0, 0, 1], four: [0, 1, 1, 1, 1], pinky: [0, 0, 0, 0, 1],
    palm: [1, 1, 1, 1, 1], point: [0, 1, 0, 0, 0], peace: [0, 1, 1, 0, 0], rock: [0, 1, 0, 0, 1],
    L: [1, 1, 0, 0, 0], three: [0, 1, 1, 1, 0], thumb: [1, 0, 0, 0, 0],
};
const POSE_HINTS = {
    fist: "All fingers folded", shaka: "Thumb and pinky out", four: "Four fingers, thumb folded",
    pinky: "Only the pinky", palm: "All five fingers spread", point: "Index finger only",
    peace: "Index and middle", rock: "Index and pinky", L: "Thumb + index, hold longer",
    three: "Index, middle and ring", thumb: "Thumb only",
};

// A tiny hand diagram: raised fingers in blue, folded ones grey.
function handGlyph(pose) {
    const f = POSE_FINGERS[pose] || [0, 0, 0, 0, 0];
    const xs = [4, 9, 13.5, 18, 22.5], tall = [9, 14, 15, 14, 11];
    let bars = "";
    f.forEach((up, i) => {
        const hgt = up ? tall[i] : 5, x = xs[i] - 1.6, y = (i === 0 ? 24 : 22) - hgt;
        bars += `<rect x="${x}" y="${y}" width="3.2" height="${hgt}" rx="1.6" fill="${up ? "var(--primary)" : "var(--text-3)"}" opacity="${up ? 1 : 0.45}"/>`;
    });
    const span = h("span", { class: "emoji", "aria-hidden": "true" });
    span.innerHTML = `<svg viewBox="0 0 26 26" width="30" height="30">${bars}<rect x="5.5" y="21" width="16" height="4" rx="2" fill="var(--text-3)" opacity=".45"/></svg>`;
    return span;
}

// ---- appearance -----------------------------------------------------------
const darkQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
function applyAppearance(a) {
    if (!a) return;
    const theme = a.theme === "system" ? (darkQuery && darkQuery.matches ? "dark" : "light") : a.theme;
    document.documentElement.dataset.theme = theme || "light";
    document.documentElement.dataset.contrast = a.high_contrast ? "high" : "normal";
    document.documentElement.style.fontSize = `${15 * (a.text_scale || 1)}px`;
}
if (darkQuery) darkQuery.addEventListener("change", () => S.state && applyAppearance(S.state.appearance));

// ---- toasts & popovers ----------------------------------------------------
const TOAST_ICONS = { error: "alert", success: "check", info: "info" };
function toast(item, action) {
    const box = $("#toasts");
    const el = h("div", { class: `toast ${item.level || "info"}`, role: "status" },
        h("div", { class: "t-head" }, h("span", { class: "ti" }, icon(TOAST_ICONS[item.level] || "info")),
            h("div", null, item.message)),
        action ? h("button", { class: "btn soft sm block", onclick: () => { action.run(); close(); } }, action.label) : null);
    box.prepend(el);
    while (box.children.length > 3) box.lastChild.remove();
    let timer = setTimeout(close, item.level === "error" ? 7000 : 4500);
    el.addEventListener("mouseenter", () => clearTimeout(timer));
    el.addEventListener("mouseleave", () => { timer = setTimeout(close, 2500); });
    function close() { el.classList.add("out"); setTimeout(() => el.remove(), 260); }
}

let openPop = null;
function popover(anchor, content, align = "end") {
    closePopover();
    const pop = h("div", { class: "popover", role: "menu" }, content);
    document.body.appendChild(pop);
    const r = anchor.getBoundingClientRect();
    const w = pop.offsetWidth;
    let left = align === "end" ? r.right - w : r.left;
    left = Math.max(12, Math.min(left, window.innerWidth - w - 12));
    let top = r.bottom + 8;
    if (top + pop.offsetHeight > window.innerHeight - 12) top = Math.max(12, r.top - pop.offsetHeight - 8);
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
    openPop = { pop, anchor };
    const first = pop.querySelector("button");
    if (first) first.focus();
    return pop;
}
function closePopover() { if (openPop) { openPop.pop.remove(); openPop = null; } }
document.addEventListener("mousedown", (e) => {
    if (openPop && !openPop.pop.contains(e.target) && !openPop.anchor.contains(e.target)) closePopover();
});
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePopover();
    if ((e.metaKey || e.ctrlKey) && /^[1-6]$/.test(e.key)) { e.preventDefault(); go(ROUTES[Number(e.key) - 1].id); }
});
window.addEventListener("resize", closePopover);

function menuItem(iconName, label, run) {
    return h("button", { class: "item", role: "menuitem", onclick: () => { closePopover(); run(); } }, icon(iconName), label);
}

// ---- reusable controls ---------------------------------------------------
function switchCtl(checked, onchange, label) {
    return h("label", { class: "switch" },
        h("input", { type: "checkbox", checked: !!checked, "aria-label": label, onchange: (e) => onchange(e.target.checked) }),
        h("span"));
}
function selectCtl(options, value, onchange, label, cls = "field") {
    const sel = h("select", { class: cls, "aria-label": label, onchange: (e) => onchange(e.target.value) },
        options.map(([v, text]) => h("option", { value: v, selected: String(v) === String(value) }, text)));
    return sel;
}
function rangeCtl(key, min, max, step, fmt) {
    const value = S.cfg.settings[key];
    const out = h("output", null, fmt(value));
    const input = h("input", {
        type: "range", min, max, step, value, "aria-label": key,
        oninput: (e) => { out.textContent = fmt(Number(e.target.value)); },
        onchange: (e) => saveSetting(key, Number(e.target.value)),
    });
    return h("span", { class: "range" }, input, out);
}
function formRow(title, desc, control) {
    return h("div", { class: "form-row" }, h("div", { class: "lbl" }, h("strong", null, title), desc ? h("span", null, desc) : null), control);
}
async function saveSetting(key, value) {
    S.cfg.settings[key] = value;
    await call("save", { [key]: value });
}
function sectionHead(title, sub, ...right) {
    return h("div", { class: "section-head" }, h("h2", null, title), sub ? h("span", { class: "sub" }, sub) : null,
        right.length ? h("div", { class: "right" }, right) : null);
}

// ---- camera component ----------------------------------------------------
function cameraView() {
    const img = h("img", { alt: "Camera preview with hand tracking" });
    const placeholder = h("div", { class: "placeholder" }, icon("camera"),
        h("div", null, S.cameraOn ? "Starting camera…" : "Camera is off"));
    const badge = h("div", { class: "badge" }, h("span", { class: "pose" }, ""), h("span", { class: "act" }, ""));
    return h("div", { class: "camera", "data-camera": "1" }, img, placeholder, badge);
}
function cameraToggle() {
    return h("button", {
        class: `btn sm ${S.cameraOn ? "" : "soft"}`, "data-camtoggle": "1",
        onclick: () => setCamera(!S.cameraOn),
    }, icon(S.cameraOn ? "cameraOff" : "camera"), S.cameraOn ? "Turn off" : "Turn on camera");
}
async function setCamera(on) {
    S.cameraOn = on;
    await call(on ? "start_preview" : "stop_preview");
    $$("[data-camera]").forEach((c) => {
        c.classList.remove("live");
        const ph = c.querySelector(".placeholder div");
        if (ph) ph.textContent = on ? "Starting camera…" : "Camera is off";
    });
    $$("[data-camtoggle]").forEach((b) => b.replaceWith(cameraToggle()));
    updateHeader();
}
ag.on("frame", (f) => {
    if (!S.cameraOn) return;
    for (const c of $$("[data-camera]")) {
        if (f.error) {
            c.classList.remove("live");
            c.querySelector(".placeholder div").textContent = f.error;
            continue;
        }
        c.classList.add("live");
        c.querySelector("img").src = "data:image/jpeg;base64," + f.img;
        c.querySelector(".badge .pose").textContent = f.hands ? (f.pose_label || "Hand detected") : "Show your hand";
        c.querySelector(".badge .act").textContent = f.action ? `→ ${f.action}` : "";
    }
    $$("[data-pose-row]").forEach((r) => r.classList.toggle("live", r.dataset.poseRow === f.pose));
});

// ---- header ----------------------------------------------------------------
function buildHeader() {
    const nav = h("nav", { class: "nav", "aria-label": "Main" },
        ROUTES.map((r) => h("button", { title: r.label, "aria-label": r.label, "data-route": r.id, onclick: () => go(r.id) }, icon(r.icon))));
    const bell = h("button", { class: "tile", id: "bell", title: "Activity", "aria-label": "Activity", onclick: showActivity }, icon("bell"));
    const cta = h("div", { id: "cta" });
    const cam = h("button", { class: "tile", id: "cam-tile", title: "Camera & gestures", "aria-label": "Camera and gestures", onclick: () => go("gestures") }, icon("camera"));
    replace($("#topbar"),
        h("button", { class: "tile logo", title: "Airglide", "aria-label": "Airglide home", onclick: () => go("home") }, brandMark()),
        nav, bell, h("div", { class: "spacer" }), cta, cam);
}
function brandMark() { const s = h("span", { style: "display:inline-flex" }); s.innerHTML = BRAND_SVG; return s; }

function updateHeader() {
    const st = S.state;
    $$(".nav button").forEach((b) => b.setAttribute("aria-current", b.dataset.route === S.route ? "page" : "false"));
    const bell = $("#bell");
    const dot = bell.querySelector(".dot");
    if (S.unseen && !dot) bell.appendChild(h("i", { class: "dot" }));
    if (!S.unseen && dot) dot.remove();
    if (!st) return;
    const presenting = st.presenter.running;
    replace($("#cta"), presenting
        ? h("button", { class: "btn lg", onclick: togglePresenter }, icon("stop"), "Stop presenting")
        : h("button", { class: "btn primary lg", onclick: togglePresenter, disabled: !st.presentation, title: st.presentation ? "" : "Add a presentation first" },
            icon("play"), "Start presenting"));
    const cam = $("#cam-tile");
    const live = st.preview || presenting || st.mouse.running || S.cameraOn;
    const cdot = cam.querySelector(".dot");
    if (live && !cdot) cam.appendChild(h("i", { class: "dot live" }));
    if (!live && cdot) cdot.remove();
}

function showActivity(e) {
    S.unseen = 0;
    updateHeader();
    const items = (S.state && S.state.activity) || [];
    const list = h("div", { class: "activity" }, items.length ? items.map((a) =>
        h("div", { class: `a ${a.level}` }, h("i"), h("div", null, a.message, h("time", null, fmtAgo(a.t)))))
        : h("div", { class: "a" }, h("div", { class: "faint" }, "Nothing yet. Notifications will show up here.")));
    popover(e.currentTarget, [
        h("div", { class: "head" }, "Activity", items.length ? h("button", { class: "btn ghost sm", onclick: async () => { await call("clear_activity"); closePopover(); refresh(); } }, "Clear") : null),
        list,
    ], "start");
}

// ---- live bar (presenting / mouse) ----------------------------------------
function updateLive() {
    const box = $("#live");
    const st = S.state;
    if (!st || (!st.presenter.running && !st.mouse.running)) { clear(box); S.liveBase = null; return; }
    if (st.presenter.running) {
        const p = st.presenter;
        S.liveBase = { elapsed: p.elapsed, at: Date.now(), paused: p.paused, started: p.started };
        let sched = null;
        if (p.schedule != null && p.started) {
            sched = p.schedule === 0 ? h("span", { class: "chip green" }, "On track")
                : p.schedule > 0 ? h("span", { class: "chip blue" }, `${fmtClock(p.schedule)} ahead`)
                    : h("span", { class: "chip amber" }, `${fmtClock(-p.schedule)} behind`);
        }
        replace(box, h("div", { class: `live-bar ${p.paused ? "paused" : ""}` },
            h("span", { class: "pulse" }),
            h("strong", null, !p.started ? "Opening your slideshow…" : p.paused ? "Gestures paused" : "Presenting"),
            p.started ? h("span", { class: "stat", id: "live-clock" }, fmtClock(p.elapsed)) : null,
            p.total ? h("span", { class: "stat" }, `Slide ${p.slide} of ${p.total}`) : null,
            sched,
            h("span", { class: "grow" }, p.last_action || p.title || ""),
            h("button", { class: "btn sm", onclick: togglePause }, icon(p.paused ? "play" : "pause"), p.paused ? "Resume" : "Pause"),
            h("button", { class: "btn sm danger", onclick: togglePresenter }, icon("stop"), "Stop")));
    } else {
        const m = st.mouse;
        replace(box, h("div", { class: `live-bar ${m.paused ? "paused" : ""}` },
            h("span", { class: "pulse" }),
            h("strong", null, m.paused ? "Virtual mouse paused" : "Virtual mouse is on"),
            h("span", { class: "grow" }, "Index finger moves · pinch index + middle to click · three fingers scroll"),
            h("button", { class: "btn sm", onclick: togglePause }, icon(m.paused ? "play" : "pause"), m.paused ? "Resume" : "Pause"),
            h("button", { class: "btn sm danger", onclick: toggleMouse }, icon("stop"), "Stop")));
    }
}
setInterval(() => {
    const el = $("#live-clock");
    const b = S.liveBase;
    if (el && b && b.started && !b.paused) el.textContent = fmtClock(b.elapsed + (Date.now() - b.at) / 1000);
}, 1000);

async function togglePresenter() { await call("toggle_presenter"); refresh(); }
async function toggleMouse() { await call("toggle_mouse"); refresh(); }
async function togglePause() { await call("toggle_pause"); refresh(); }
async function addPresentation() { await call("add_presentation"); refresh(); }

// "Add" offers a file or a Google Slides link.
function addMenu(e) {
    const anchor = e.currentTarget;
    const input = h("input", { class: "field", type: "url", placeholder: "https://docs.google.com/presentation/d/…",
        "aria-label": "Google Slides link", style: "width:100%" });
    const error = h("div", { class: "faint small", style: "margin:.4rem .2rem 0", "aria-live": "polite" });
    const addLink = async () => {
        const url = input.value.trim();
        if (!url) { input.focus(); return; }
        save.disabled = true;
        error.textContent = "Adding… (downloading slide text if the deck is shared)";
        const r = await call("add_link", url);
        save.disabled = false;
        if (r && r.ok) { closePopover(); refresh(); }
        else error.textContent = r ? r.message : "Couldn't add that link";
    };
    const save = h("button", { class: "btn primary sm", onclick: addLink }, "Add link");
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); addLink(); } });
    const pop = popover(anchor, [
        menuItem("upload", "Choose a file…  (.pptx, .pdf, .docx, .doc)", addPresentation),
        h("div", { style: "border-top:1px solid var(--border);margin:.35rem 0" }),
        h("div", { style: "padding:.4rem .5rem .5rem;width:22rem" },
            h("div", { style: "font-weight:600;font-size:.9rem;margin-bottom:.45rem;display:flex;gap:.5rem;align-items:center" }, icon("external"), "Google Slides link"),
            h("div", { class: "field-row" }, input, save),
            error),
    ]);
    pop.style.maxWidth = "26rem";
}

// ---- hero ------------------------------------------------------------------
function hero(title, chips, side) {
    const lines = Array.isArray(title) ? title : [title];
    return h("header", { class: "hero" },
        h("div", null, h("h1", null, lines.map((l, i) => [i ? h("br") : null, l])),
            chips && chips.length ? h("div", { class: "meta" }, chips) : null),
        side ? h("div", { class: "hero-side" }, side) : null);
}
function chip(iconName, text, cls = "") { return h("span", { class: `chip ${cls}` }, iconName ? icon(iconName) : null, text); }

// ---- views -------------------------------------------------------------------
const views = {};
let current = null;

function go(route) {
    if (!views[route]) route = "home";
    closePopover();
    if (current && current.unmount) current.unmount();
    S.route = route;
    store.set("route", route);
    current = views[route];
    const root = replace($("#view"));
    root.classList.remove("view");
    void root.offsetWidth;  // restart the entrance animation
    root.classList.add("view");
    current.mount(root);
    updateHeader();
    window.scrollTo(0, 0);
}

// == Dashboard ==================================================================
views.home = {
    mount(root) {
        this.root = root;
        this.render();
    },
    update() { this.render(); },
    render() {
        const st = S.state;
        const root = this.root;
        const keepScroll = $(".rows, .board", root);
        const scrollTop = window.scrollY;
        clear(root);
        if (!st) return;
        const cur = st.presentation;
        if (!cur) {
            append(root,
                hero(["Present", "hands‑free"], [chip("hand", "Gesture control"), chip("mouse", "Virtual mouse"), chip("sparkles", "AI slide assistant")],
                    h("button", { class: "btn primary lg", onclick: addMenu }, icon("upload"), "Add presentation")),
                h("div", { class: "grid-main" },
                    h("section", null, sectionHead("Get started"),
                        h("div", { class: "empty" },
                            h("div", { class: "big-ico" }, icon("upload")),
                            h("h3", null, "Add your first presentation or document"),
                            h("p", null, "PowerPoint, PDF, Word (.docx / .doc) or a Google Slides link. Airglide reads it, plans your talk timing and gets your gestures ready."),
                            h("button", { class: "btn primary", onclick: addMenu }, icon("plus"), "Add presentation")),
                        h("div", { class: "grid-3", style: "margin-top:1rem" },
                            feature("hand", "var(--blue)", "Gestures", "Change slides, point and draw without touching anything."),
                            feature("clock", "var(--purple)", "Talk timeline", "See how long each slide should take and stay on time."),
                            feature("sparkles", "var(--orange)", "Assistant", "Ask about your slides, get talking points and likely questions."))),
                    checklistSection()));
            return;
        }
        const presenting = st.presenter.running && st.presenter.started;
        append(root,
            hero(deckTitle(cur.name), [
                chip(cur.kind === "gslides" ? "external" : "monitor", `${cur.slides || "–"} ${cur.unit || "slides"}`),
                chip("clock", `${st.talk_minutes ? "Target" : "About"} ${fmtDur(st.plan_total)}`),
                chip("hand", st.profile.label),
            ], [
                h("button", { class: "btn", onclick: () => go("assistant") }, icon("sparkles"), "Ask assistant"),
            ]),
            deckTabs(),
            slideStrip(),
            h("div", { class: "grid-main" },
                h("section", null,
                    sectionHead("Talk timeline", null,
                        selectCtl([[0, "Auto length"], ...[5, 10, 15, 20, 30, 45, 60].map((m) => [m, `${m} min talk`])],
                            st.talk_minutes, async (v) => { await call("save", { talk_minutes: Number(v) }); refresh(); }, "Target talk length", "field"),
                        h("div", { class: "segmented", role: "group", "aria-label": "Timeline layout" },
                            h("button", { "aria-pressed": String(S.timelineMode === "list"), onclick: () => this.setMode("list") }, icon("list"), "List"),
                            h("button", { "aria-pressed": String(S.timelineMode === "board"), onclick: () => this.setMode("board") }, icon("board"), "Board"))),
                    !st.slides.length ? noTextCard(cur)
                        : S.timelineMode === "list" ? timelineList(presenting) : timelineBoard(presenting)),
                checklistSection()));
        if (keepScroll) window.scrollTo(0, scrollTop);
    },
    setMode(mode) { S.timelineMode = mode; store.set("timeline", mode); this.render(); },
};

function noTextCard(cur) {
    const gs = cur.kind === "gslides";
    return h("div", { class: "empty", style: "padding:2.2rem" },
        h("div", { class: "big-ico" }, icon(gs ? "external" : "notes")),
        h("h3", null, gs ? "Slide text isn't available" : "No text found"),
        h("p", null, gs
            ? "Presenting works, but to plan your timeline and use the assistant, share the deck as \"Anyone with the link can view\" in Google Slides, then add the link again."
            : "This file has no readable text (it may be scanned images). Gestures still work; the timeline and assistant need text."));
}

function feature(iconName, color, title, text) {
    return h("div", { class: "feature" }, h("span", { class: "fi", style: `background:${color}` }, icon(iconName)), h("strong", null, title), h("span", null, text));
}

function deckTabs() {
    const st = S.state;
    return h("div", { class: "tabs-line", role: "tablist", "aria-label": "Recent presentations" },
        st.recent.map((e) => h("button", {
            role: "tab", "aria-selected": String(st.presentation && e.id === st.presentation.id), title: e.name,
            onclick: async () => { await call("select_presentation", e.id); S.selected = null; refresh(); },
        }, deckTitle(e.name))),
        h("button", { class: "add", onclick: addMenu }, icon("plus"), "Add"));
}

function currentSlide() {
    const p = S.state.presenter;
    return p.running && p.started ? p.slide : null;
}

function slideStrip() {
    const st = S.state;
    const cur = currentSlide();
    const strip = h("div", { class: "strip", role: "list", "aria-label": "Slides" },
        st.slides.map((s) => h("button", {
            role: "listitem",
            class: `${s.has_notes ? "notes" : ""} ${S.selected === s.slide_number ? "selected" : ""}`,
            "aria-current": String(cur === s.slide_number),
            title: `${s.title || unitOne(st.presentation) + " " + s.slide_number} · starts at ${fmtClock(s.start)}`,
            onclick: () => pickSlide(s.slide_number),
        }, h("span", { class: "n" }, String(s.slide_number).padStart(2, "0")), h("span", { class: "t" }, fmtClock(s.start)))));
    requestAnimationFrame(() => {
        const active = strip.querySelector('[aria-current="true"]') || strip.querySelector(".selected");
        if (active) active.scrollIntoView({ block: "nearest", inline: "center" });
    });
    return strip;
}

async function pickSlide(n) {
    const st = S.state;
    if (currentSlide() && st.profile.goto) {
        const r = await call("goto_slide", n);
        if (r && !r.ok) toast({ message: r.message, level: "error" });
        return;
    }
    S.selected = n;
    views.home.render();
    const row = $(`[data-slide="${n}"]`);
    if (row) { row.scrollIntoView({ block: "center", behavior: "smooth" }); row.classList.add("flash"); }
}

function slideMenu(e, s) {
    const st = S.state;
    const items = [menuItem("sparkles", `Ask the assistant about this ${unitOne(st.presentation).toLowerCase()}`, () => { go("assistant"); askAboutSlide(s.slide_number); })];
    if (currentSlide() && st.profile.goto) items.push(menuItem("arrowRight", "Jump to this slide", () => pickSlide(s.slide_number)));
    items.push(menuItem("clock", `Starts at ${fmtClock(s.start)} · ${fmtDur(s.duration)}`, () => {}));
    popover(e.currentTarget, items);
}

function timelineList(presenting) {
    const st = S.state;
    const cur = currentSlide();
    return h("div", { class: "rows" }, st.slides.map((s, i) => h("article", {
        class: `row-card ${cur === s.slide_number ? "current" : ""}`, "data-slide": s.slide_number, style: `--accent:${accent(i)}`,
    },
    h("div", { class: "when" }, fmtClock(s.start), h("div", { class: "to" }, "to"), fmtClock(s.start + s.duration)),
    h("div", { class: "divider" }),
    h("div", { class: "facts" },
        h("span", null, icon("hourglass"), fmtDur(s.duration)),
        h("span", null, icon("notes"), s.has_notes ? "Speaker notes" : `${s.words} words`)),
    h("div", { class: "what" },
        h("div", { class: "title" }, h("span", { class: "num" }, s.slide_number), s.title || `${unitOne(st.presentation)} ${s.slide_number}`),
        s.excerpt ? h("div", { class: "excerpt" }, s.excerpt) : null),
    h("button", { class: "btn ghost icon", "aria-label": `More for slide ${s.slide_number}`, onclick: (e) => slideMenu(e, s) }, icon("more")))));
}

function timelineBoard() {
    const st = S.state;
    const cur = currentSlide();
    return h("div", { class: "board" }, st.slides.map((s, i) => h("button", {
        class: `board-card ${cur === s.slide_number ? "current" : ""}`, "data-slide": s.slide_number, style: `--accent:${accent(i)}`,
        onclick: (e) => slideMenu(e, s),
    },
    h("span", { class: "faint small tnum" }, `${unitOne(st.presentation)} ${s.slide_number} · ${fmtClock(s.start)}`),
    h("span", { class: "title" }, s.title || `${unitOne(st.presentation)} ${s.slide_number}`),
    h("span", { class: "foot" }, h("span", null, icon("hourglass"), fmtDur(s.duration)), s.has_notes ? h("span", null, icon("notes"), "Notes") : null))));
}

// -- checklist --
const CHECK_ICONS = { camera: "camera", accessibility: "keyboard", presentation: "folder", calibration: "wand", gesture: "hand", assistant: "sparkles" };
function checklistSection() {
    const checks = S.state.checks;
    const required = checks.filter((c) => !c.optional);
    const done = required.filter((c) => c.ok).length;
    return h("section", null,
        sectionHead("Pre‑flight check", null, h("button", { class: "btn", onclick: runChecks }, icon("refresh"), "Run checks")),
        h("div", { class: "card tray" },
            h("div", { style: "display:flex;align-items:center;gap:.8rem;padding:.2rem .3rem .9rem" },
                h("strong", { class: "tnum" }, `${done} of ${required.length} ready`),
                h("div", { class: "progress", style: "flex:1" }, h("div", { style: `width:${required.length ? (done / required.length) * 100 : 0}%` }))),
            h("div", { class: "checklist" }, checks.map((c) => h("button", {
                class: `check-row ${c.ok ? "done" : ""}`, onclick: () => fixCheck(c),
                "aria-label": `${c.label}: ${c.ok ? "done" : "not done"}. ${c.detail}`,
            },
            h("span", { class: "ico" }, icon(CHECK_ICONS[c.id] || "check")),
            h("span", { class: "txt" }, h("div", { class: "label" }, c.label, c.optional ? h("span", { class: "faint small" }, "  · optional") : null),
                h("div", { class: "detail" }, c.detail)),
            h("span", { class: `checkbox ${c.ok ? "on" : ""}` }, icon("check")))))));
}
async function runChecks() {
    const status = await call("check_camera");
    await refresh();
    const missing = S.state.checks.filter((c) => !c.ok && !c.optional).length;
    toast({ message: missing ? `${missing} item${missing > 1 ? "s" : ""} still need attention` : "Everything is ready. Break a leg!",
        level: missing ? "info" : "success" });
    return status;
}
async function fixCheck(c) {
    if (c.ok && c.id !== "gesture" && c.id !== "calibration") return;
    switch (c.action) {
        case "camera": {
            const status = await call("check_camera");
            if (status !== "granted") await call("open_permission", "camera");
            refresh();
            break;
        }
        case "accessibility": await call("open_permission", "accessibility"); break;
        case "add": addPresentation(); break;
        case "calibrate": go("gestures"); setTimeout(() => { const el = $("#calibration"); if (el) el.scrollIntoView({ behavior: "smooth", block: "center" }); }, 200); break;
        case "gestures": go("gestures"); if (!S.cameraOn) setCamera(true); break;
        case "assistant": S.settingsTab = "assistant"; go("settings"); break;
        default: break;
    }
}

// == Gestures =====================================================================
views.gestures = {
    mount(root) {
        const cfg = S.cfg, st = S.state;
        append(root,
            hero(["Gesture", "control"], [
                chip("hand", st ? st.profile.label : ""),
                cfg.settings.calibration ? chip("check", "Calibrated", "green") : chip("wand", "Not calibrated"),
                chip("clock", `Hold ${cfg.settings.hold_frames} frames`),
            ]),
            h("div", { class: "grid-2" },
                h("div", { class: "stack" },
                    h("section", null, sectionHead("Live camera", "Try any gesture to see what it does", cameraToggle()), cameraView()),
                    h("section", { id: "calibration" }, calibrationCard()),
                    h("section", null, sectionHead("Sensitivity"), h("div", { class: "card" }, h("div", { class: "form-rows" },
                        formRow("Hold time", "Frames a gesture must be held before it fires", rangeCtl("hold_frames", 1, 15, 1, (v) => `${v}`)),
                        formRow("Cooldown", "Pause between two actions", rangeCtl("cooldown_s", 0, 3, 0.1, (v) => `${Number(v).toFixed(1)} s`)),
                        formRow("Detection confidence", "Higher means fewer false detections", rangeCtl("detection_confidence", 0.3, 0.95, 0.05, (v) => `${Math.round(v * 100)}%`)),
                        formRow("Two‑hand zoom", "Point with both index fingers, move apart or together", switchCtl(cfg.settings.two_hand_zoom, (v) => saveSetting("two_hand_zoom", v), "Two-hand zoom")))))),
                h("div", { class: "stack" },
                    h("section", null, sectionHead("Gesture map", null, h("button", { class: "btn ghost sm", onclick: resetGestures }, icon("refresh"), "Reset")),
                        h("div", { class: "card tray" }, h("div", { class: "rows", id: "gesture-map", style: "gap:.55rem" }, gestureRows()))),
                    h("section", null, sectionHead("Presentation app"), h("div", { class: "card" }, h("div", { class: "form-rows" },
                        formRow("App", "Which keyboard shortcuts Airglide sends",
                            selectCtl(cfg.profiles.map((p) => [p.id, p.label]), cfg.settings.presenter_profile, (v) => saveSetting("presenter_profile", v), "Presentation app")),
                        formRow("Corner button", "While presenting, an Airglide button in the screen corner opens the camera, controls and gestures",
                            switchCtl(cfg.settings.launcher_enabled, (v) => saveSetting("launcher_enabled", v), "Corner button")),
                        formRow("Speaking pace", "Used to plan your talk timeline",
                            selectCtl([["relaxed", "Relaxed"], ["normal", "Normal"], ["fast", "Fast"]], cfg.settings.speaking_pace, (v) => saveSetting("speaking_pace", v), "Speaking pace")))),
                    h("p", { class: "faint small", style: "margin:.8rem .3rem 0" }, "Google Slides links open in your browser automatically. PDFs use the PDF viewer and Word documents page up / down automatically.")))));
    },
    unmount() { if (S.cameraOn) setCamera(false); },
};

function gestureRows() {
    const cfg = S.cfg;
    const options = Object.entries(cfg.actions);
    return cfg.poses.map((p, i) => h("div", { class: "map-row", "data-pose-row": p.id, style: `--accent:${accent(i)}` },
        handGlyph(p.id),
        h("div", { class: "name" }, p.name, h("small", null, POSE_HINTS[p.id] || "")),
        selectCtl(options, cfg.settings.gesture_map[p.id], (v) => {
            const map = { ...cfg.settings.gesture_map, [p.id]: v };
            saveSetting("gesture_map", map);
        }, `Action for ${p.name}`)));
}
async function resetGestures() {
    S.cfg = await call("reset", ["gesture_map", "hold_frames", "cooldown_s", "detection_confidence", "two_hand_zoom"]);
    toast({ message: "Gesture settings reset to defaults", level: "success" });
    go("gestures");
}

function calibrationCard() {
    const status = h("p", { class: "muted", "aria-live": "polite" },
        S.cfg.settings.calibration ? "Tuned to your hand. Recalibrate if lighting or distance changes a lot."
            : "Teach Airglide what your open hand and fist look like. It takes about 10 seconds.");
    const start = h("button", { class: "btn primary" }, icon("wand"), "Calibrate my hand");
    const reset = h("button", { class: "btn ghost" }, "Use defaults");
    start.onclick = async () => {
        if (!S.cameraOn) await setCamera(true);
        const ok = await runCalibration(status, [start, reset]);
        if (ok) S.cfg = await call("get_settings");
    };
    reset.onclick = async () => { await saveSetting("calibration", null); status.textContent = "Using the default thresholds."; };
    return h("div", { class: "card" }, h("h3", null, "Calibration"), status, h("div", { style: "display:flex;gap:.5rem;margin-top:.8rem" }, start, reset));
}

async function runCalibration(statusEl, buttons) {
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    const say = (text, cls = "muted") => { statusEl.className = cls; statusEl.textContent = text; };
    buttons.forEach((b) => (b.disabled = true));
    try {
        for (const [kind, text] of [["palm", "Show an open palm, fingers spread"], ["fist", "Now make a fist"]]) {
            let ok = false;
            for (let attempt = 0; attempt < 3 && !ok; attempt++) {
                for (let n = 3; n > 0; n--) { say(`${text}… ${n}`); await wait(1000); }
                say(`${text}. Hold still…`);
                const res = await call("calibrate_sample", kind);
                ok = res && res.ok;
                if (!ok) { say(res ? res.message : "Calibration failed", "muted"); await wait(1500); }
            }
            if (!ok) { say("Couldn't see your hand. Check the camera and lighting, then try again."); return false; }
        }
        const result = await call("calibrate_finish");
        say(result.problems.length ? `Calibrated. ${result.problems.join(". ")}.` : "Calibrated for your hand ✓");
        toast({ message: "Hand calibration saved", level: "success" });
        return true;
    } finally {
        buttons.forEach((b) => (b.disabled = false));
    }
}

// == Virtual mouse ================================================================
views.mouse = {
    mount(root) {
        const st = S.state;
        const running = st.mouse.running;
        append(root,
            hero(["Virtual", "mouse"], [running ? chip(null, st.mouse.paused ? "Paused" : "Running", st.mouse.paused ? "amber" : "green") : chip(null, "Off")],
                h("button", { class: `btn lg ${running ? "" : "primary"}`, onclick: async () => { await toggleMouse(); go("mouse"); } },
                    icon(running ? "stop" : "play"), running ? "Stop mouse" : "Start virtual mouse")),
            h("div", { class: "grid-2" },
                h("div", { class: "stack" },
                    h("section", null, sectionHead("How it works"), h("div", { class: "grid-2", style: "gap:1rem" },
                        feature("pointer", "var(--blue)", "Move", "Raise your index finger and move it."),
                        feature("click", "var(--green)", "Click", "Raise index + middle and pinch them together."),
                        feature("scroll", "var(--purple)", "Scroll", "Raise three fingers and move your hand up or down."),
                        feature("pause", "var(--orange)", "Pause", "Hold an L‑shape (thumb + index) still for 1.5 s to pause or resume."))),
                    h("section", null, sectionHead("Tuning"), h("div", { class: "card" }, h("div", { class: "form-rows" },
                        formRow("Smoothing", "Higher is steadier but a little slower", rangeCtl("mouse_smoothing", 1, 20, 1, (v) => `${v}`)),
                        formRow("Edge margin", "Part of the camera image ignored at the edges", rangeCtl("mouse_margin", 0, 0.35, 0.01, (v) => `${Math.round(v * 100)}%`)),
                        formRow("Pinch sensitivity", "Higher clicks with fingers further apart", rangeCtl("click_pinch", 0.1, 0.6, 0.01, (v) => Number(v).toFixed(2))))))),
                h("section", null, sectionHead("Camera", null, cameraToggle()), cameraView(),
                    h("p", { class: "faint small", style: "margin:.8rem .3rem" }, "Tip: sit about an arm's length from the camera with your hand well lit."))));
    },
    unmount() { if (S.cameraOn) setCamera(false); },
};

// == Assistant ==================================================================
const QUICK = [
    ["summary", "Summarise the deck", "Five short bullet points"],
    ["explain", "Explain the current slide", "In simple words"],
    ["talking_points", "Talking points", "For the slide you're on"],
    ["questions", "Audience questions", "Likely questions with answers"],
];
views.assistant = {
    async mount(root) {
        const st = S.state;
        this.log = h("div", { class: "chat-log", role: "log", "aria-live": "polite" });
        this.input = h("input", { class: "field", placeholder: "Ask anything about your slides…", "aria-label": "Your question",
            onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); this.send(); } } });
        this.sendBtn = h("button", { class: "btn primary", onclick: () => this.send() }, icon("send"), "Send");
        const cur = st.presentation;
        const p = st.presenter;
        const needsInstall = !st.assistant.ready;
        this.installMode = needsInstall;
        append(root,
            hero(["Slide", "assistant"], [
                cur ? chip("folder", deckTitle(cur.name)) : chip("folder", "No presentation"),
                st.assistant.ready ? assistantChip(st.assistant) : null,
            ]));
        if (needsInstall) {
            append(root, installCard(() => go("assistant")));
            return;
        }
        append(root,
            h("div", { class: "grid-main", style: "margin-top:0" },
                h("section", { class: "card chat" }, this.log, h("div", { class: "composer" }, this.input, this.sendBtn)),
                h("div", { class: "stack" },
                    h("section", null, sectionHead("Quick prompts"), h("div", { class: "rows", style: "gap:.6rem" },
                        QUICK.map(([kind, title, sub], i) => h("button", { class: "prompt-row", style: `--accent:${accent(i)}`, onclick: () => this.quick(kind) },
                            h("div", null, h("strong", null, title), h("span", null, sub)), icon("chevronRight"))))),
                    h("section", { class: "card" }, h("h3", null, "Context"),
                        h("table", { class: "simple" },
                            h("tr", null, h("td", null, "Presentation"), h("td", null, cur ? deckTitle(cur.name) : "None")),
                            h("tr", null, h("td", null, "Slides"), h("td", null, cur ? String(cur.slides) : "–")),
                            h("tr", null, h("td", null, "Current slide"), h("td", null, p.running && p.started ? `${p.slide}${p.title ? " · " + p.title : ""}` : "Not presenting"))),
                        h("button", { class: "btn ghost sm", style: "margin-top:.6rem", onclick: () => this.clearChat() }, icon("trash"), "Clear conversation")))));
        for (const m of S.chat.log) this.render(m);
        if (!S.chat.log.length) {
            const status = await call("chat_status");
            if (status) this.add(status.ok ? { kind: "bot", text: status.message } : { kind: "system", text: status.error, error: true });
        }
        this.setBusy(S.chat.busy);
        this.input.focus();
    },
    update() {
        // Switch between the "Add chatbot" panel and the chat when the status changes.
        const st = S.state;
        const needsInstall = !st.assistant.ready;
        if (needsInstall !== this.installMode) go("assistant");
        else if (needsInstall) $$("[data-install]").forEach((c) => c._render());
    },
    add(m) { S.chat.log.push(m); return this.render(m); },
    render(m) {
        if (!this.log || !this.log.isConnected) return null;
        const el = h("div", { class: `message ${m.kind}${m.error ? " error" : ""}${m.typing ? " typing" : ""}`, "data-id": m.id || "" });
        if (m.kind === "system") el.textContent = m.text; else append(el, richText(m.text || ""));
        this.log.appendChild(el);
        this.log.scrollTop = this.log.scrollHeight;
        return el;
    },
    setBusy(busy) {
        S.chat.busy = busy;
        if (this.input && this.input.isConnected) { this.input.disabled = busy; this.sendBtn.disabled = busy; if (!busy) this.input.focus(); }
    },
    async ask(text, method, ...args) {
        const id = "m" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
        if (text) this.add({ kind: "user", text });
        const pending = { kind: "bot", text: "", typing: true, id };
        S.chat.log.push(pending);
        this.render(pending);
        this.setBusy(true);
        const res = await call(method, ...args, id);
        S.chat.log = S.chat.log.filter((m) => m !== pending);
        $$(`[data-id="${id}"]`).forEach((el) => el.remove());
        if (res && res.prompt && !text) this.add({ kind: "user", text: res.prompt });
        if (res && res.ok) this.add({ kind: "bot", text: res.reply });
        else this.add({ kind: "system", text: res ? res.error : "No answer", error: true });
        this.setBusy(false);
    },
    send() {
        const text = this.input.value.trim();
        if (!text || S.chat.busy) return;
        this.input.value = "";
        this.ask(text, "chat_send", text);
    },
    quick(kind) { if (!S.chat.busy) this.ask(null, "chat_quick", kind); },
    async clearChat() {
        await call("chat_clear");
        S.chat.log = [];
        clear(this.log);
        this.add({ kind: "system", text: "New conversation started." });
    },
};
function askAboutSlide(n) {
    setTimeout(() => { if (S.route === "assistant" && !S.chat.busy) views.assistant.ask(null, "chat_about_slide", n); }, 120);
}
ag.on("chunk", ({ id, text }) => {
    const m = S.chat.log.find((x) => x.id === id);
    if (!m) return;
    m.text += text;
    m.typing = false;
    for (const el of $$(`[data-id="${id}"]`)) { el.classList.remove("typing"); replace(el, richText(m.text)); el.parentElement.scrollTop = el.parentElement.scrollHeight; }
});

function assistantChip() {
    return chip("lock", "On this computer", "green");
}

function fmtBytes(n) { return n >= 1e9 ? `${(n / 1e9).toFixed(2)} GB` : `${Math.round((n || 0) / 1e6)} MB`; }

// "Add chatbot" panel: button -> loader with progress -> ready.
function installCard(after, compact = false) {
    const box = h("section", { class: `card install ${compact ? "compact" : ""}`, "data-install": "1" });
    box._after = after;
    box._render = () => {
        const a = S.state.assistant;
        const d = a.download || {};
        const pct = Math.round((d.progress || 0) * 100);
        let body;
        if (a.ready) {
            body = [h("div", { class: "install-ico done" }, icon("check")),
                h("h3", null, "Chatbot added"), h("p", { class: "muted" }, "You can start asking questions.")];
        } else if (d.state === "downloading") {
            body = [h("div", { class: "loader", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(pct) },
                h("span", { class: "loader-pct tnum", "data-install-pct": "1" }, `${pct}%`)),
            h("h3", null, "Adding the chatbot…"),
            h("p", { class: "muted", "data-install-label": "1" }, d.total ? `${fmtBytes(d.done)} of ${fmtBytes(d.total)}` : "Starting…"),
            h("div", { class: "progress", style: "width:min(22rem,100%);margin:.4rem auto 0" }, h("div", { "data-install-bar": "1", style: `width:${pct}%` })),
            h("p", { class: "faint small", style: "margin-top:.8rem" }, "You can keep using Airglide while this finishes."),
            h("button", { class: "btn ghost sm", style: "margin-top:.4rem", onclick: () => call("cancel_install") }, "Cancel")];
        } else {
            const resumable = d.state === "paused" || d.state === "error";
            body = [h("div", { class: "install-ico" }, icon("sparkles")),
                h("h3", null, "AI chatbot"),
                h("p", { class: "muted" }, "Ask questions about your slides, get talking points and likely audience questions. It runs entirely on this computer: no account, no key, and nothing leaves your device."),
                d.state === "error" ? h("p", { class: "small", style: "color:var(--red)" }, d.error || "The download failed.") : null,
                !a.runtime ? h("p", { class: "small", style: "color:var(--red)" }, "The chatbot engine isn't installed. Run pip install -r requirements.txt.") : null,
                h("button", { class: "btn primary lg", style: "margin-top:.6rem", disabled: !a.runtime, onclick: async () => {
                    const r = await call("install_assistant");
                    if (r && !r.ok) { toast({ message: r.message, level: "error" }); return; }
                    // The download may already have finished (fast / resumed): don't overwrite that.
                    const now = S.state.assistant.download || {};
                    if (!S.state.assistant.ready && now.state !== "ready") {
                        S.state.assistant.download = { ...now, state: "downloading" };
                    }
                    for (const c of $$("[data-install]")) c._render();
                } }, icon(resumable ? "refresh" : "plus"), "Add chatbot"),
            ];
        }
        replace(box, h("div", { class: "install-body" }, body));
    };
    box._render();
    return box;
}

ag.on("model", (d) => {
    if (!S.state || !S.state.assistant) return;
    const prev = (S.state.assistant.download || {}).state;
    S.state.assistant.download = d;
    const pct = Math.round((d.progress || 0) * 100);
    $$("[data-install-pct]").forEach((el) => { el.textContent = `${pct}%`; });
    $$("[data-install-bar]").forEach((el) => { el.style.width = `${pct}%`; });
    $$("[data-install-label]").forEach((el) => { el.textContent = `${fmtBytes(d.done)} of ${fmtBytes(d.total)}`; });
    $$(".loader").forEach((el) => el.setAttribute("aria-valuenow", String(pct)));
    if (d.state !== prev || d.state !== "downloading") {
        if (d.state === "ready") toast({ message: "The chatbot is ready. Ask it anything about your slides.", level: "success" });
        if (d.state === "error") toast({ message: d.error || "Adding the chatbot failed", level: "error" });
        S.chat.log = [];
        refresh().then(() => {
            for (const c of $$("[data-install]")) { if (S.state.assistant.ready && c._after) c._after(); else c._render(); }
            if (S.route === "settings") views.settings.renderTab();
        });
    }
});


// == Library ========================================================================
views.library = {
    mount(root) { this.root = root; this.render(); },
    update() { this.render(); },
    render() {
        const st = S.state;
        clear(this.root);
        const cur = st.presentation;
        append(this.root,
            hero(["Your", "presentations"], [chip("folder", `${st.recent.length} of 8 recent`)],
                h("button", { class: "btn primary lg", onclick: addMenu }, icon("upload"), "Add presentation")),
            h("div", { class: "deck-grid" },
                h("button", { class: "deck add", onclick: addMenu }, icon("plus"), "Add a deck, PDF, Word document", h("span", { class: "faint small" }, "or a Google Slides link")),
                st.recent.map((e) => {
                    const kind = KINDS[e.kind] || KINDS.pptx;
                    const isCur = cur && cur.id === e.id;
                    return h("article", { class: `deck ${isCur ? "current" : ""}` },
                        h("div", { style: "display:flex;align-items:center;gap:.8rem" },
                            h("span", { class: "type", style: `background:${kind.color}`, title: e.kind === "gslides" ? e.url : e.name }, kind.badge),
                            isCur ? chip("check", "Current", "blue") : null),
                        h("div", { class: "name", title: e.name }, deckTitle(e.name)),
                        h("div", { class: "facts" },
                            e.kind === "gslides" && !e.has_text ? chip("alert", "No slide text", "amber") : chip("monitor", `${e.slides} ${e.unit || "slides"}`),
                            chip("clock", fmtAgo(e.added))),
                        h("div", { class: "actions" },
                            isCur ? h("button", { class: "btn soft sm", onclick: () => go("home") }, icon("list"), "Open timeline")
                                : h("button", { class: "btn sm", onclick: async () => { await call("select_presentation", e.id); await refresh(); toast({ message: `${deckTitle(e.name)} selected`, level: "success" }); } }, "Use this"),
                            h("button", { class: "btn ghost sm icon", "aria-label": `Remove ${e.name}`, title: "Remove", onclick: (ev) => confirmRemove(ev, e) }, icon("trash"))));
                })));
    },
};
function confirmRemove(ev, e) {
    popover(ev.currentTarget, [
        h("div", { class: "head" }, "Remove from Airglide?"),
        h("p", { class: "faint small", style: "margin:0 .75rem .5rem" }, "Your original file is not touched."),
        menuItem("trash", `Remove ${deckTitle(e.name)}`, async () => { await call("remove_presentation", e.id); refresh(); }),
    ]);
}

// == Settings ======================================================================
const SETTINGS_TABS = [["general", "General"], ["appearance", "Appearance"], ["camera", "Camera"], ["assistant", "Assistant"],
    ["privacy", "Privacy"], ["shortcuts", "Shortcuts"], ["about", "About"]];
views.settings = {
    mount(root) {
        this.body = h("div", { style: "margin-top:1.4rem" });
        append(root, hero("Settings", [chip("info", `Airglide ${S.cfg.version}`)]),
            h("div", { class: "tabs-line", role: "tablist" }, SETTINGS_TABS.map(([id, label]) =>
                h("button", { role: "tab", "aria-selected": String(S.settingsTab === id), onclick: (e) => {
                    S.settingsTab = id;
                    $$("[role=tab]", e.currentTarget.parentElement).forEach((b) => b.setAttribute("aria-selected", String(b === e.currentTarget)));
                    this.renderTab();
                } }, label))),
            this.body);
        this.renderTab();
    },
    renderTab() {
        const cfg = S.cfg, s = cfg.settings;
        const card = (...rows) => h("div", { class: "card", style: "max-width:52rem" }, h("div", { class: "form-rows" }, rows));
        const tabs = {
            general: () => card(
                formRow("Sound effects", "Short sounds when you start and stop features", switchCtl(s.sounds, (v) => saveSetting("sounds", v), "Sound effects")),
                formRow("Global shortcuts", "Work even when Airglide is in the background", switchCtl(s.hotkeys_enabled, (v) => saveSetting("hotkeys_enabled", v), "Global shortcuts")),
                cfg.tray_supported ? formRow("Keep running in the tray", "Closing the window hides it instead of quitting", switchCtl(s.minimize_to_tray, (v) => saveSetting("minimize_to_tray", v), "Tray")) : null,
                formRow("Check for updates", "Look for a new version when Airglide starts", switchCtl(s.check_updates, (v) => saveSetting("check_updates", v), "Updates")),
                formRow("First‑run setup", "Permissions, assistant key and calibration", h("button", { class: "btn", onclick: () => openOnboarding(0) }, "Run setup again"))),
            appearance: () => card(
                formRow("Theme", null, h("div", { class: "segmented", style: "background:var(--surface-2)" },
                    [["light", "Light", "sun"], ["dark", "Dark", "moon"], ["system", "System", "monitor"]].map(([v, label, ic]) =>
                        h("button", { "aria-pressed": String(s.theme === v), onclick: async () => { await saveSetting("theme", v); this.renderTab(); } }, icon(ic), label)))),
                formRow("Text size", "Scales the whole interface", rangeCtl("text_scale", 0.8, 1.4, 0.1, (v) => `${Math.round(v * 100)}%`)),
                formRow("High contrast", "Stronger text and borders", switchCtl(s.high_contrast, (v) => saveSetting("high_contrast", v), "High contrast"))),
            camera: () => {
                const sel = h("span");
                const fill = (ids) => replace(sel, selectCtl([
                    ...[...new Set(["0", ...ids.map(String), /^\d+$/.test(s.camera_source) ? s.camera_source : "0"])].sort().map((i) => [i, i === "0" ? "Built‑in / default camera" : `Camera ${i}`]),
                    ...(s.phone_cam_url ? [["phone", "Phone camera"]] : []),
                ], s.camera_source, (v) => saveSetting("camera_source", v), "Camera"));
                fill([]);
                const url = h("input", { class: "field", type: "url", placeholder: "http://192.168.1.20:8080/video", value: s.phone_cam_url || "", "aria-label": "Phone camera URL" });
                return card(
                    formRow("Camera", "Used for gestures and the virtual mouse", sel),
                    formRow("Find cameras", "Turn the camera off first", h("button", { class: "btn", onclick: async () => {
                        const r = await call("list_cameras");
                        if (!r || !r.ok) return toast({ message: r ? r.message : "Scan failed", level: "error" });
                        fill(r.cameras);
                        toast({ message: `Found ${r.cameras.length} camera${r.cameras.length === 1 ? "" : "s"}` });
                    } }, icon("refresh"), "Scan")),
                    h("div", { class: "form-row stack" }, h("div", { class: "lbl" }, h("strong", null, "Phone as camera"), h("span", null, "The video URL from a phone IP‑camera app")),
                        h("div", { class: "field-row" }, url, h("button", { class: "btn", onclick: async () => {
                            await saveSetting("phone_cam_url", url.value.trim());
                            toast({ message: url.value.trim() ? "Phone camera saved" : "Phone camera removed", level: "success" });
                            this.renderTab();
                        } }, "Save"))));
            },
            assistant: () => {
                const a = S.state.assistant;
                const d = a.download || {};
                const control = a.installed
                    ? h("div", { style: "display:flex;gap:.5rem;align-items:center" }, chip("check", "Added", "green"),
                        h("button", { class: "btn ghost sm", onclick: (e) => popover(e.currentTarget, [
                            h("div", { class: "head" }, "Take the chatbot off this computer?"),
                            h("p", { class: "faint small", style: "margin:0 .75rem .5rem" }, "Frees the disk space. You can add it again any time."),
                            menuItem("trash", "Take it off", async () => { await call("remove_assistant"); S.chat.log = []; await refresh(); this.renderTab(); }),
                        ]) }, icon("trash"), "Take off"))
                    : d.state === "downloading" ? chip("refresh", `Adding… ${Math.round((d.progress || 0) * 100)}%`, "blue")
                        : h("button", { class: "btn primary sm", onclick: async () => {
                            const r = await call("install_assistant");
                            if (r && !r.ok) toast({ message: r.message, level: "error" });
                            go("assistant");
                        } }, icon("plus"), "Add chatbot");
                return card(formRow("AI chatbot", "Runs on this computer. Nothing is sent anywhere.", control));
            },
            privacy: () => h("div", { style: "max-width:52rem", class: "stack" },
                h("div", { class: "card", style: "display:flex;gap:1rem;align-items:flex-start" },
                    h("span", { class: "fi", style: "width:2.8rem;height:2.8rem;border-radius:14px;display:grid;place-items:center;background:var(--success-soft);color:var(--green);flex-shrink:0" }, icon("shield")),
                    h("div", null, h("h3", null, "Your camera never leaves this computer"),
                        h("p", { class: "muted" }, "Hand tracking and the chatbot run locally. No video, images or slide text are uploaded."),
                        h("p", { class: "faint small" }, "Presentations, settings and logs are stored in ", h("code", null, cfg.data_dir)))),
                card(formRow("Offline mode", "Blocks update checks and downloads. The chatbot keeps working once it's added.",
                    switchCtl(s.offline_mode, (v) => saveSetting("offline_mode", v), "Offline mode")))),
            shortcuts: () => h("div", { class: "grid-2", style: "max-width:70rem" },
                h("section", { class: "card" }, h("h3", null, "Keyboard"),
                    S.state.hotkeys.length ? h("table", { class: "simple" }, S.state.hotkeys.map((k) => h("tr", null,
                        h("td", null, { presenter: "Start / stop presenting", mouse: "Virtual mouse on / off", pause: "Pause / resume gestures", show: "Show Airglide" }[k.action]),
                        h("td", null, h("span", { class: "kbd" }, k.keys)))))
                        : h("p", { class: "muted" }, "Global shortcuts are off (Settings → General)."),
                    h("p", { class: "faint small", style: "margin-top:.6rem" }, "In the app: ⌘/Ctrl + 1–6 switches between pages.")),
                h("section", { class: "card" }, h("h3", null, "Gestures"),
                    h("table", { class: "simple" }, cfg.poses.filter((p) => s.gesture_map[p.id] !== "none").map((p) =>
                        h("tr", null, h("td", null, p.label), h("td", null, cfg.actions[s.gesture_map[p.id]]))),
                    h("tr", null, h("td", null, "☝️☝️ Both index fingers"), h("td", null, "Zoom"))))),
            about: () => {
                const diag = h("textarea", { class: "field", readonly: true, hidden: true, "aria-label": "Diagnostics" });
                const upd = h("span", null, cfg.update ? `Version ${cfg.update.version} is available` : "Check for a newer version");
                return card(
                    formRow(`Airglide ${cfg.version}`, "Gesture‑controlled presentations", h("button", { class: "btn", onclick: async () => {
                        upd.textContent = "Checking…";
                        const r = await call("check_updates");
                        if (r && r.update) { upd.textContent = `Version ${r.update.version} is available`; call("open_url", r.update.url); }
                        else upd.textContent = `You're up to date (v${cfg.version})`;
                    } }, icon("refresh"), "Check for updates")),
                    h("div", { class: "form-row" }, h("div", { class: "lbl" }, upd)),
                    h("div", { class: "form-row stack" }, h("div", { class: "lbl" }, h("strong", null, "Diagnostics"), h("span", null, "Copy this into a bug report. It never includes your API key.")),
                        h("div", { style: "display:flex;gap:.5rem" },
                            h("button", { class: "btn", onclick: async () => {
                                diag.hidden = false;
                                diag.value = await call("diagnostics");
                                diag.select();
                                let ok = false;
                                try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
                                toast({ message: ok ? "Diagnostics copied" : "Select the text and copy it", level: ok ? "success" : "info" });
                            } }, "Copy diagnostics"),
                            h("button", { class: "btn ghost", onclick: () => call("open_log_folder") }, icon("external"), "Open log folder")),
                        diag));
            },
        };
        replace(this.body, (tabs[S.settingsTab] || tabs.general)());
    },
};

// == Onboarding ====================================================================
function openOnboarding(step = 0) {
    S.onboarding = { step };
    renderOnboarding();
}
async function closeOnboarding(finish) {
    if (S.cameraOn) await setCamera(false);
    S.onboarding = null;
    clear($("#modal"));
    if (finish) await call("finish_onboarding");
    refresh();
}
function renderOnboarding() {
    const ob = S.onboarding;
    if (!ob) return;
    const st = S.state;
    const STEPS = 5;
    const next = () => { ob.step++; renderOnboarding(); };
    const back = () => { ob.step--; renderOnboarding(); };
    let body;
    if (ob.step === 0) {
        body = [h("div", { class: "big-ico", style: "width:4rem;height:4rem;border-radius:20px;display:grid;place-items:center;background:var(--primary-soft);color:var(--primary);margin-bottom:1.2rem" }, brandMark()),
            h("h2", null, "Welcome to Airglide"),
            h("p", { class: "muted" }, "Control your slides with your hands, use your hand as a mouse, and get help from an AI assistant that knows your deck."),
            h("div", { class: "card tray", style: "margin-top:1.2rem;display:flex;gap:.9rem;align-items:flex-start" },
                h("span", { style: "color:var(--green)" }, icon("shield")),
                h("div", null, h("strong", null, "Private by design"),
                    h("p", { class: "muted small" }, "Video and the AI assistant both run on this computer. Nothing is uploaded."))),
            h("p", { class: "faint small", style: "margin-top:1rem" }, "Setup takes about a minute.")];
    } else if (ob.step === 1) {
        const rows = st.checks.filter((c) => c.id === "camera" || c.id === "accessibility");
        body = [h("h2", null, "Permissions"), h("p", { class: "muted" }, "Airglide needs the camera to see your hand" + (st.platform === "darwin" ? ", and Accessibility to press keys and move the mouse for you." : ".")),
            h("div", { class: "checklist", style: "margin-top:1.2rem" }, rows.map((c) => h("button", { class: `check-row ${c.ok ? "done" : ""}`, onclick: async () => { await fixCheck(c); setTimeout(async () => { await refresh(); renderOnboarding(); }, 600); } },
                h("span", { class: "ico" }, icon(CHECK_ICONS[c.id])),
                h("span", { class: "txt" }, h("div", { class: "label" }, c.label), h("div", { class: "detail" }, c.ok ? c.detail : `${c.detail}. Click to fix`)),
                h("span", { class: `checkbox ${c.ok ? "on" : ""}` }, icon("check"))))),
            st.platform === "darwin" ? h("p", { class: "faint small", style: "margin-top:.9rem" }, "Running from a terminal? Allow the terminal app under Privacy & Security → Accessibility. You may need to restart Airglide afterwards.") : null,
            h("button", { class: "btn ghost sm", style: "margin-top:.6rem", onclick: async () => { await call("check_camera"); await refresh(); renderOnboarding(); } }, icon("refresh"), "Check again")];
    } else if (ob.step === 2) {
        body = [h("h2", null, "AI assistant"), h("p", { class: "muted" }, "Optional. Ask questions about your deck, get talking points and likely audience questions. It runs on this computer."),
            st.assistant.ready ? h("div", { class: "card tray", style: "margin-top:1.2rem" }, chip("check", "Chatbot added", "green"))
                : h("div", { style: "margin-top:1.2rem" }, installCard(() => renderOnboarding(), true)),
            h("p", { class: "faint small", style: "margin-top:1rem" }, "You can also add it later from the Assistant page.")];
    } else if (ob.step === 3) {
        if (!S.cameraOn) setCamera(true);
        const status = h("p", { class: "muted small", "aria-live": "polite" }, "Calibration teaches Airglide your open hand and fist.");
        const calBtn = h("button", { class: "btn primary sm" }, icon("wand"), "Calibrate");
        calBtn.onclick = () => runCalibration(status, [calBtn]);
        body = [h("h2", null, "Try your gestures"),
            h("div", { class: "grid-2", style: "margin-top:1rem;gap:1.2rem" },
                h("div", null, cameraView(), h("div", { style: "margin-top:.8rem" }, status, calBtn)),
                h("div", { class: "rows", style: "gap:.45rem" }, ["shaka", "fist", "palm", "L", "rock"].map((id, i) => {
                    const p = S.cfg.poses.find((x) => x.id === id);
                    return h("div", { class: "map-row", "data-pose-row": id, style: `--accent:${accent(i)}` }, handGlyph(id),
                        h("div", { class: "name" }, p ? p.name : id, h("small", null, S.cfg.actions[S.cfg.settings.gesture_map[id]] || "")));
                })))];
    } else {
        if (S.cameraOn) setCamera(false);
        body = [h("h2", null, "You're all set"), h("p", { class: "muted" }, "Three steps to your first hands‑free talk:"),
            h("div", { class: "checklist", style: "margin-top:1rem" },
                [["upload", "Add a presentation", "PowerPoint or PDF"], ["play", "Start presenting", "Your slideshow opens and gestures go live"], ["pause", "Hold an L‑shape to pause", "So talking with your hands never changes slides"]]
                    .map(([ic, t, d]) => h("div", { class: "check-row" }, h("span", { class: "ico" }, icon(ic)), h("span", { class: "txt" }, h("div", { class: "label" }, t), h("div", { class: "detail" }, d))))),
            st.hotkeys.length ? h("p", { class: "faint small", style: "margin-top:1rem" }, "Shortcuts: ", st.hotkeys.map((k, i) => [i ? " · " : "", h("span", { class: "kbd" }, k.keys), " ", k.action])) : null];
    }
    const last = ob.step === STEPS - 1;
    replace($("#modal"), h("div", { class: "modal-backdrop" }, h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": "Set up Airglide" },
        h("div", { class: "m-body" }, h("div", { class: "steps", "aria-hidden": "true" }, Array.from({ length: STEPS }, (_, i) => h("i", { class: i <= ob.step ? "on" : "" }))), body),
        h("div", { class: "m-foot" },
            !last ? h("button", { class: "btn ghost", onclick: () => closeOnboarding(true) }, "Skip setup") : null,
            h("div", { class: "spacer" }),
            ob.step > 0 ? h("button", { class: "btn", onclick: back }, "Back") : null,
            h("button", { class: "btn primary", onclick: last ? () => closeOnboarding(true) : next }, last ? "Start using Airglide" : "Continue", icon("arrowRight"))))));
    const primary = $("#modal .m-foot .btn.primary");
    if (primary) primary.focus();
}

// ---- state refresh ------------------------------------------------------------
let refreshTimer = null, refreshing = null;
async function refresh() {
    if (refreshing) return refreshing;
    refreshing = (async () => {
        const st = await call("get_state");
        if (!st) return;
        const prevDeck = S.state && S.state.presentation && S.state.presentation.id;
        S.state = st;
        applyAppearance(st.appearance);
        updateHeader();
        updateLive();
        if (current && current.update && !S.onboarding) current.update();
        if (prevDeck !== (st.presentation && st.presentation.id)) S.chat.log = [];
        if (!st.onboarded && !S.onboarding) openOnboarding(0);
    })();
    try { await refreshing; } finally { refreshing = null; }
}
function scheduleRefresh() { clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, 120); }

ag.on("changed", scheduleRefresh);
ag.on("toast", (item) => {
    if (!S.onboarding) S.unseen++;
    toast(item);
    updateHeader();
});
ag.on("presenter", (p) => {
    if (!S.state) return;
    const wasStarted = S.state.presenter.started, prevSlide = S.state.presenter.slide;
    S.state.presenter = { ...S.state.presenter, ...p };
    updateLive();
    if (S.route === "home" && (prevSlide !== p.slide || wasStarted !== p.started)) views.home.render();
});

// ---- boot --------------------------------------------------------------------
async function boot() {
    buildHeader();
    S.cfg = await call("get_settings");
    await refresh();
    go(S.route);
    setInterval(() => { if (!document.hidden) refresh(); }, 5000);
}
if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot, { once: true });
