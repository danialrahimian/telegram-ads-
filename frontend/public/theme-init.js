// Applies the saved theme before first paint (kept as a file because the CSP blocks inline scripts).
(function () {
  try {
    var t = localStorage.getItem("tgads-theme") || "system";
    var dark = t === "dark" || (t === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
  } catch (e) {}
})();
