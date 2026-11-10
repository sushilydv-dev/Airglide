// Stroke icons on a 24px grid (drawn for Airglide). Usage: icon("hand")
const ICON_PATHS = {
    home: '<rect x="3" y="3" width="7.5" height="9" rx="2"/><rect x="13.5" y="3" width="7.5" height="5.5" rx="2"/><rect x="13.5" y="11.5" width="7.5" height="9.5" rx="2"/><rect x="3" y="15" width="7.5" height="6" rx="2"/>',
    hand: '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12"/><path d="M11 11V4a1.5 1.5 0 0 1 3 0v7"/><path d="M14 11V5.5a1.5 1.5 0 0 1 3 0V13"/><path d="M17 10a1.5 1.5 0 0 1 3 0v4a7 7 0 0 1-7 7h-1.2a6 6 0 0 1-4.6-2.2L4.3 15.2a1.6 1.6 0 0 1 2.4-2.1L8 14.5"/>',
    mouse: '<path d="M5 3.5 18.5 9l-6 1.8-2.2 6.2z"/><path d="m13 11 5.5 5.5"/>',
    sparkles: '<path d="M10 3.5 11.6 8a2 2 0 0 0 1.4 1.4l4.5 1.6-4.5 1.6a2 2 0 0 0-1.4 1.4L10 18.5 8.4 14a2 2 0 0 0-1.4-1.4L2.5 11 7 9.4A2 2 0 0 0 8.4 8z"/><path d="M18.5 3v4M16.5 5h4M19 16.5v3M17.5 18h3"/>',
    folder: '<path d="M3.5 7.5A2 2 0 0 1 5.5 5.5h4l2 2.2h7a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/><circle cx="12" cy="12" r="6.6"/>',
    bell: '<path d="M6 16.5V11a6 6 0 1 1 12 0v5.5l1.5 1.5h-15z"/><path d="M10 20.5a2.2 2.2 0 0 0 4 0"/>',
    play: '<path d="M7.5 5.2v13.6a.8.8 0 0 0 1.2.7l10.6-6.8a.8.8 0 0 0 0-1.4L8.7 4.5a.8.8 0 0 0-1.2.7z"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2.5"/>',
    pause: '<rect x="6.5" y="5" width="3.6" height="14" rx="1.2"/><rect x="13.9" y="5" width="3.6" height="14" rx="1.2"/>',
    camera: '<rect x="2.5" y="6" width="13.5" height="12" rx="3"/><path d="m16 10.5 5-3v9l-5-3"/>',
    cameraOff: '<path d="M16 10.5 21 7.5v9l-3.2-1.9"/><path d="M12.5 6H13a3 3 0 0 1 3 3v3.5M16 16.5a3 3 0 0 1-3 1.5H5.5a3 3 0 0 1-3-3V9a3 3 0 0 1 2-2.8"/><path d="m3 3 18 18"/>',
    hourglass: '<path d="M6.5 3h11M6.5 21h11"/><path d="M7.5 3v2.5a4.5 4.5 0 0 0 2 3.7L12 11l2.5-1.8a4.5 4.5 0 0 0 2-3.7V3"/><path d="M7.5 21v-2.5a4.5 4.5 0 0 1 2-3.7L12 13l2.5 1.8a4.5 4.5 0 0 1 2 3.7V21"/>',
    notes: '<path d="M6 3h8.5L19 7.5V19a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M14 3v5h5M8 13h8M8 17h5"/>',
    more: '<circle cx="5.5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="18.5" cy="12" r="1.6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    trash: '<path d="M4.5 7h15M9.5 7V5a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 14.5 5v2M6.5 7l.8 12a2 2 0 0 0 2 1.9h5.4a2 2 0 0 0 2-1.9l.8-12"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    list: '<path d="M10 6h10M10 12h10M10 18h10"/><path d="m3.5 6 1.2 1.2L7 5M3.5 12l1.2 1.2L7 11M3.5 18l1.2 1.2L7 17"/>',
    board: '<rect x="3.5" y="4" width="17" height="16" rx="3"/><path d="M10 4v16"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    shield: '<path d="M12 3 4.5 6v5.5c0 4.5 3.2 8.3 7.5 9.5 4.3-1.2 7.5-5 7.5-9.5V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
    keyboard: '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6.5 10h1M10 10h1M13.5 10h1M17 10h.5M6.5 14h11"/>',
    info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8h.01"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    chevronRight: '<path d="m9 6 6 6-6 6"/>',
    refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3L19.5 9"/><path d="M19.5 4v5h-5"/>',
    upload: '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5"/><path d="M4.5 15v3a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-3"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    wand: '<path d="m4 20 11-11M14 4v2.5M19.5 9.5H17M17.9 6.1l-1.6 1.6M15 9l1.8 1.8"/><path d="M20 4l-1 1"/>',
    monitor: '<rect x="2.5" y="4" width="19" height="13" rx="2.5"/><path d="M8.5 21h7M12 17v4"/>',
    arrowRight: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    alert: '<path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4M12 17h.01"/>',
    send: '<path d="M4 12 20 4l-4.5 16-3.5-6.5z"/><path d="M12 13.5 20 4"/>',
    lock: '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
    target: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/>',
    pointer: '<path d="M10 11V4.5a1.5 1.5 0 0 1 3 0V11"/><path d="M13 9.5a1.5 1.5 0 0 1 3 0V11M16 10.5a1.5 1.5 0 0 1 3 0V15a6 6 0 0 1-6 6h-1.5a5.5 5.5 0 0 1-4.3-2.1l-2.4-3a1.5 1.5 0 0 1 2.3-1.9L10 15.5"/>',
    scroll: '<rect x="7" y="2.5" width="10" height="19" rx="5"/><path d="M12 6.5v3"/>',
    click: '<path d="M9 9.5 20 13l-4.5 1.5L14 19z"/><path d="M5 3.5l1.2 2.2M3 8h2.5M9.5 2.5 9 5"/>',
};

const BRAND_SVG = '<svg viewBox="0 0 32 32" width="30" height="30" fill="none" aria-hidden="true">' +
    '<path d="M5 22.5C9 11 15 5.5 21.5 5.5c3.2 0 5.3 1.4 6 3.5-4.6-1.4-11.2 2-16.4 13.5z" fill="currentColor"/>' +
    '<path d="M9.5 26.5c5.8-9.2 11.3-12.6 17.5-11.4-1.6 5.8-7.6 11.4-17.5 11.4z" fill="currentColor" opacity=".55"/></svg>';

function icon(name, cls) {
    const span = document.createElement("span");
    span.className = "i" + (cls ? " " + cls : "");
    span.style.display = "inline-flex";
    span.setAttribute("aria-hidden", "true");
    const paths = ICON_PATHS[name] || ICON_PATHS.info;
    // Static, trusted markup from the table above.
    span.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" ' +
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + paths + "</svg>";
    return span;
}
