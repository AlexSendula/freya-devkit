/* ============================================================================
   The Behavior Layer — shared shell: nav, footer, theme, TOC scrollspy.
   Pure vanilla, no fetch / no modules → works on file:// by double-click.
   Each page includes: <div id="site-header"></div> ... <div id="site-footer"></div>
   ==========================================================================*/
(function () {
  "use strict";

  var PAGES = [
    { href: "index.html",      label: "The Story" },
    { href: "concepts.html",   label: "How It Works" },
    { href: "governance.html", label: "Governance" },
    { href: "journey.html",    label: "The Journey" },
    { href: "reference.html",  label: "Reference" }
  ];

  var MARK =
    '<svg class="mark" viewBox="0 0 32 32" fill="none" aria-hidden="true">' +
    '<rect x="2" y="2" width="28" height="28" rx="8" style="fill:var(--accent)"/>' +
    '<path d="M9 16.5l4.2 4.2L23 11" stroke="#fff" stroke-width="2.6" ' +
    'stroke-linecap="round" stroke-linejoin="round"/>' +
    '<circle cx="9" cy="16.5" r="1.7" fill="#fff"/></svg>';

  var SUN =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4' +
    'M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/></svg>';
  var MOON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z"/></svg>';

  function currentFile() {
    var p = location.pathname.split("/").pop();
    return p && p.length ? p : "index.html";
  }

  /* ---- Theme ------------------------------------------------------------ */
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    var btn = document.querySelector(".theme-toggle");
    if (btn) btn.innerHTML = t === "dark" ? SUN : MOON;
  }
  function initTheme() {
    var saved;
    try { saved = localStorage.getItem("blx-theme"); } catch (e) {}
    if (!saved) {
      saved = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches)
        ? "dark" : "light";
    }
    applyTheme(saved);
  }
  function toggleTheme() {
    var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    try { localStorage.setItem("blx-theme", next); } catch (e) {}
    applyTheme(next);
  }

  /* ---- Header ----------------------------------------------------------- */
  function buildHeader() {
    var host = document.getElementById("site-header");
    if (!host) return;
    var here = currentFile();
    var links = PAGES.map(function (p) {
      var active = p.href === here ? " active" : "";
      return '<a class="nav-link' + active + '" href="' + p.href + '">' + p.label + "</a>";
    }).join("");
    host.innerHTML =
      '<nav class="site-nav"><div class="nav-inner">' +
        '<a class="brand" href="index.html">' + MARK + "<span>The Behavior Layer</span></a>" +
        '<div class="nav-links">' + links + "</div>" +
        '<button class="theme-toggle" type="button" aria-label="Toggle theme"></button>' +
      "</div></nav>";
    var btn = host.querySelector(".theme-toggle");
    if (btn) btn.addEventListener("click", toggleTheme);
    applyTheme(document.documentElement.getAttribute("data-theme") || "light");
  }

  /* ---- Footer ----------------------------------------------------------- */
  function buildFooter() {
    var host = document.getElementById("site-footer");
    if (!host) return;
    host.innerHTML =
      '<footer class="site-footer"><div class="footer-inner">' +
        '<div>An explainer for the <strong>Behavior Layer</strong> — the <code>feat/behavior-layer</code> ' +
        'initiative of the freya-devkit plugin.</div>' +
        '<div class="footer-links">' +
          '<a href="index.html">Story</a>' +
          '<a href="concepts.html">How It Works</a>' +
          '<a href="governance.html">Governance</a>' +
          '<a href="journey.html">Journey</a>' +
          '<a href="reference.html">Reference</a>' +
        "</div>" +
      "</div></footer>";
  }

  /* ---- Auto TOC + scrollspy (pages with #toc + .doc-body) --------------- */
  function slugify(s) {
    return s.toLowerCase().replace(/[^\w\s-]/g, "").trim().replace(/\s+/g, "-");
  }
  function buildTOC() {
    var toc = document.getElementById("toc");
    var body = document.querySelector(".doc-body");
    if (!toc || !body) return;
    var heads = body.querySelectorAll("section > h2, section > h3");
    if (!heads.length) return;
    var html = '<div class="toc-title">On this page</div>';
    var items = [];
    heads.forEach(function (h) {
      if (!h.id) h.id = slugify(h.textContent);
      var lvl = h.tagName === "H3" ? " lvl-3" : "";
      html += '<a class="' + lvl.trim() + '" href="#' + h.id + '">' + h.textContent + "</a>";
      items.push(h);
      // heading anchor link
      var a = document.createElement("a");
      a.className = "anchor-link"; a.href = "#" + h.id; a.textContent = "#";
      a.setAttribute("aria-hidden", "true");
      h.appendChild(a);
    });
    toc.innerHTML = html;

    var links = toc.querySelectorAll("a:not(.toc-title)");
    function spy() {
      var pos = window.scrollY + parseInt(getComputedStyle(document.documentElement).scrollPaddingTop || "80") + 4;
      var current = items[0];
      for (var i = 0; i < items.length; i++) {
        if (items[i].offsetTop <= pos) current = items[i]; else break;
      }
      links.forEach(function (l) {
        l.classList.toggle("active", l.getAttribute("href") === "#" + current.id);
      });
    }
    var ticking = false;
    window.addEventListener("scroll", function () {
      if (!ticking) { window.requestAnimationFrame(function () { spy(); ticking = false; }); ticking = true; }
    }, { passive: true });
    spy();
  }

  function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  // theme ASAP to avoid flash
  initTheme();
  ready(function () {
    buildHeader();
    buildFooter();
    buildTOC();
  });

  // expose a tiny helper namespace for page-specific interactive scripts
  window.BLX = { toggleTheme: toggleTheme, slugify: slugify };
})();
