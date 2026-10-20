(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const shamsi = new Intl.DateTimeFormat("fa-IR-u-nu-latn", { month: "short", day: "numeric", timeZone: "UTC" });
  const shamsiLong = new Intl.DateTimeFormat("fa-IR-u-nu-latn", { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
  const fmt = {
    ton: (v) => (v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })),
    cps: (v) => (v == null ? "—" : v.toFixed(3)),
    int: (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-US")),
  };

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function textW(svg, s) {
    const t = el("text", { class: "tick" }, svg); t.textContent = s;
    const w = t.getComputedTextLength(); t.remove(); return w;
  }
  function niceMax(v) {
    if (!(v > 0)) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }
  function rolling(rows, key, days) {
    return rows.map((r, i) => {
      let s = 0, a = 0;
      for (let j = Math.max(0, i - days + 1); j <= i; j++) { s += rows[j].spent; a += rows[j][key]; }
      return a ? s / a : null;
    });
  }

  function draw(box) {
    const src = document.getElementById(box.dataset.src);
    if (!src) return;
    const rows = JSON.parse(src.textContent || "[]");
    box.replaceChildren();
    if (!rows.length) { const p = document.createElement("div"); p.className = "empty"; p.textContent = "هنوز داده‌ای نیست."; box.appendChild(p); return; }
    const kind = box.dataset.kind || "bars";
    const f = fmt[box.dataset.fmt || "ton"];
    let vals;
    if (box.dataset.value === "cps7") vals = rolling(rows, "starts", 7);
    else vals = rows.map((r) => Number(r[box.dataset.value]) || 0);
    const target = box.dataset.target ? Number(box.dataset.target) : null;
    const W = Math.max(box.clientWidth, 280), H = 220, top = 10, bottom = 26;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" }, box);
    const maxV = niceMax(Math.max(...vals.filter((v) => v != null), target || 0) * 1.05);
    const ticks = [0, maxV / 2, maxV];
    const ml = Math.max(...ticks.map((t) => textW(svg, f(t)))) + 10;
    const y = (v) => top + (H - top - bottom) * (1 - v / maxV);
    const step = (W - ml - 4) / rows.length;
    const x = (i) => ml + i * step;
    ticks.forEach((t) => {
      el("line", { x1: ml, x2: W - 4, y1: y(t), y2: y(t), stroke: "var(--grid)" }, svg);
      const tx = el("text", { x: ml - 6, y: y(t) + 4, "text-anchor": "end", class: "tick" }, svg); tx.textContent = f(t);
    });
    const labW = textW(svg, shamsi.format(new Date(rows[0].day))) + 14;
    const every = Math.max(1, Math.ceil(labW / step));
    rows.forEach((r, i) => {
      if ((rows.length - 1 - i) % every) return;
      const cx = x(i) + step / 2, half = labW / 2;
      const anchor = cx + half > W ? "end" : cx - half < ml ? "start" : "middle";
      const tx = el("text", { x: anchor === "end" ? W - 2 : anchor === "start" ? ml : cx, y: H - 6, "text-anchor": anchor, class: "tick" }, svg);
      tx.textContent = shamsi.format(new Date(r.day));
    });
    if (target != null) {
      el("line", { x1: ml, x2: W - 4, y1: y(target), y2: y(target), stroke: "var(--bad)", "stroke-dasharray": "4 3" }, svg);
      const tt = el("text", { x: W - 6, y: y(target) - 5, "text-anchor": "end", class: "tick" }, svg); tt.textContent = box.dataset.targetLabel || "";
    }
    if (kind === "bars") {
      const bw = Math.max(1, step * 0.7);
      vals.forEach((v, i) => {
        if (!v) return;
        el("rect", { x: x(i) + (step - bw) / 2, y: y(v), width: bw, height: Math.max(1, y(0) - y(v)), rx: Math.min(3, bw / 2), fill: "var(--chart)" }, svg);
      });
    } else {
      let d = "";
      vals.forEach((v, i) => { if (v == null) return; d += (d ? "L" : "M") + (x(i) + step / 2).toFixed(1) + "," + y(v).toFixed(1); });
      el("path", { d, fill: "none", stroke: "var(--chart)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    }
    // tooltip
    const tip = document.createElement("div"); tip.className = "tip"; box.appendChild(tip);
    const hl = el("rect", { x: 0, y: top, width: step, height: H - top - bottom, fill: "var(--soft)", opacity: 0 }, svg);
    svg.insertBefore(hl, svg.firstChild);
    svg.addEventListener("mousemove", (ev) => {
      const b = svg.getBoundingClientRect();
      const px = (ev.clientX - b.left) * (W / b.width);
      const i = Math.floor((px - ml) / step);
      if (i < 0 || i >= rows.length) { tip.style.display = "none"; hl.setAttribute("opacity", 0); return; }
      const r = rows[i];
      hl.setAttribute("x", x(i)); hl.setAttribute("opacity", 1);
      tip.replaceChildren();
      const h = document.createElement("div"); h.className = "h"; h.textContent = shamsiLong.format(new Date(r.day)); tip.appendChild(h);
      const lines = [["هزینه", fmt.ton(r.spent) + " TON"], ["استارت", fmt.int(r.starts)], ["کلیک", fmt.int(r.clicks)]];
      if (box.dataset.value === "cps7") lines.unshift(["هزینه/استارت (۷ روز)", fmt.cps(vals[i])]);
      lines.forEach(([k, v]) => { const d = document.createElement("div"); d.textContent = k + ": " + v; tip.appendChild(d); });
      tip.style.display = "block";
      const bx = box.getBoundingClientRect();
      let lx = ev.clientX - bx.left + 12;
      if (lx + tip.offsetWidth > bx.width) lx = ev.clientX - bx.left - tip.offsetWidth - 12;
      tip.style.left = Math.max(0, lx) + "px"; tip.style.top = (ev.clientY - bx.top + 12) + "px";
    });
    svg.addEventListener("mouseleave", () => { tip.style.display = "none"; hl.setAttribute("opacity", 0); });
  }

  function drawAll() { document.querySelectorAll(".chart[data-src]").forEach(draw); }
  let t; window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(drawAll, 150); });
  document.addEventListener("DOMContentLoaded", () => {
    drawAll();
    // character counters
    document.querySelectorAll("textarea[data-max]").forEach((ta) => {
      const c = document.getElementById(ta.dataset.counter);
      const upd = () => { const n = ta.value.length; c.textContent = n + " / " + ta.dataset.max; c.classList.toggle("over", n > Number(ta.dataset.max)); };
      ta.addEventListener("input", upd); upd();
    });
    // variant picker fills the text
    document.querySelectorAll("select[data-fill]").forEach((sel) => {
      const ta = document.getElementById(sel.dataset.fill);
      sel.addEventListener("change", () => {
        const o = sel.selectedOptions[0];
        if (o && o.dataset.text != null) { ta.value = o.dataset.text; ta.dispatchEvent(new Event("input")); }
      });
    });
    // show/hide fields by placement kind
    document.querySelectorAll("[data-kind-switch]").forEach((sel) => {
      const upd = () => document.querySelectorAll("[data-only]").forEach((e) => { e.hidden = e.dataset.only !== sel.value; });
      const cpm = document.getElementById(sel.dataset.cpm);
      sel.addEventListener("change", () => { upd(); if (cpm && cpm.dataset[sel.value]) cpm.value = cpm.dataset[sel.value]; });
      upd();
    });
    // confirmations
    document.querySelectorAll("form[data-confirm]").forEach((f) => f.addEventListener("submit", (e) => {
      if (!window.confirm(f.dataset.confirm)) e.preventDefault();
    }));
    // copy buttons
    document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", () => {
      const src = document.getElementById(b.dataset.copy);
      navigator.clipboard.writeText(src.textContent.trim()).then(() => { const o = b.textContent; b.textContent = "کپی شد"; setTimeout(() => (b.textContent = o), 1200); });
    }));
  });
})();
