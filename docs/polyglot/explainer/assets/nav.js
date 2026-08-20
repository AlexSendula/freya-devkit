/* ===========================================================================
   Track B explainer — shared top bar.

   Vanilla, no modules, no fetch: a <script src> works over file:// while a
   fetch() does not, and these pages are opened by double-clicking them.
   Every page carries <div id="topbar"></div> as its first element in <body>.
   ======================================================================== */
(function () {
  "use strict";

  var PAGES = [
    { href: "index.html",        label: "Start here" },
    { href: "problem.html",      label: "The problem" },
    { href: "how-it-works.html", label: "How it works" },
    { href: "building-it.html",  label: "How it was built" },
    { href: "decisions.html",    label: "Decisions" }
  ];

  function here() {
    var name = location.pathname.split("/").pop();
    return name && name.length ? name : "index.html";
  }

  function build() {
    var host = document.getElementById("topbar");
    if (!host) return;
    var current = here();
    var links = PAGES.map(function (p) {
      var cls = p.href === current ? ' class="here"' : "";
      return '<a href="' + p.href + '"' + cls + ">" + p.label + "</a>";
    }).join("");
    host.className = "topbar";
    host.innerHTML =
      '<div class="topbar-inner">' +
        '<a class="home" href="index.html"><span class="dot"></span>Track B</a>' +
        "<nav>" + links + "</nav>" +
      "</div>";
  }

  /* Highlight the table-of-contents entry for whatever section is on screen.
     Only runs on pages that have one. */
  function spy() {
    var toc = document.querySelector(".toc");
    if (!toc) return;
    var links = Array.prototype.slice.call(toc.querySelectorAll('a[href^="#"]'));
    if (!links.length) return;
    var targets = links.map(function (a) {
      return document.getElementById(decodeURIComponent(a.getAttribute("href").slice(1)));
    });

    function update() {
      var best = -1, bestTop = -Infinity;
      for (var i = 0; i < targets.length; i++) {
        if (!targets[i]) continue;
        var top = targets[i].getBoundingClientRect().top - 90;
        if (top <= 0 && top > bestTop) { bestTop = top; best = i; }
      }
      links.forEach(function (a, i) {
        if (i === best) { a.style.color = "var(--accent)"; a.style.fontWeight = "650"; }
        else { a.style.color = ""; a.style.fontWeight = ""; }
      });
    }

    var ticking = false;
    window.addEventListener("scroll", function () {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () { update(); ticking = false; });
    }, { passive: true });
    update();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { build(); spy(); });
  } else {
    build();
    spy();
  }
})();
