import { createRenderer, solveLayout } from "./drop-field.js";

const PALETTE = [
  "#5a9b8e",
  "#c88d65",
  "#a9a05b",
  "#7899b4",
  "#a88aad",
  "#8ca37b",
  "#c47f84",
  "#7a9f9f",
  "#a7987b",
  "#8995bd",
];
const rgb = (hex) =>
  [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
const identityColors = new Map();
const hash = (id) => {
  let n = 2166136261;
  for (const c of id) {
    n ^= c.charCodeAt(0);
    n = Math.imul(n, 16777619);
  }
  return n >>> 0;
};
export const color = (id) =>
  identityColors.get(id) || PALETTE[hash(id) % PALETTE.length];
function prepareColors(ctx) {
  const key = "fold-colors-v2:" + ctx.tenant;
  identityColors.clear();
  try {
    for (const [id, value] of Object.entries(
      JSON.parse(localStorage.getItem(key) || "{}"),
    ))
      if (/^#[0-9a-f]{6}$/i.test(value)) identityColors.set(id, value);
  } catch {}
  const ids = new Set((ctx.landscape?.projects || []).map((p) => p.id));
  const visit = (layer) => {
    for (const item of layer?.items || []) {
      ids.add(item.id);
      visit(item.children);
    }
  };
  visit(ctx.state.root);
  for (const frame of ctx.history) visit(frame.state.root);
  const projects = ctx.landscape?.projects || [];
  const priority = [
    ...projects.slice(0, 8).map((p) => p.id),
    ...(projects.length > 8 ? ["__other__"] : []),
    ...projects.slice(8).map((p) => p.id),
    ...[...ids].sort(),
  ];
  const used = new Set();
  const extra = (index) => {
    const hue = (index * 137.508) % 360,
      saturation = 0.26,
      light = 0.56;
    const f = (n) => {
      const k = (n + hue / 30) % 12,
        a = saturation * Math.min(light, 1 - light);
      return Math.round(
        255 * (light - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))),
      )
        .toString(16)
        .padStart(2, "0");
    };
    return "#" + f(0) + f(8) + f(4);
  };
  for (const id of [...new Set(priority)]) {
    let chosen = identityColors.get(id);
    if (!chosen || used.has(chosen)) {
      const start = hash(id) % PALETTE.length;
      chosen = null;
      for (let i = 0; i < PALETTE.length; i++) {
        const value = PALETTE[(start + i) % PALETTE.length];
        if (!used.has(value)) {
          chosen = value;
          break;
        }
      }
      if (!chosen) {
        let n = hash(id) % 360;
        do {
          chosen = extra(n++);
        } while (used.has(chosen));
      }
      identityColors.set(id, chosen);
    }
    used.add(chosen);
  }
  try {
    localStorage.setItem(
      key,
      JSON.stringify(Object.fromEntries(identityColors)),
    );
  } catch {}
}
const fieldHeight = (max = 480) =>
  Math.max(235, Math.min(max, innerHeight - 350));

const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const short = (s, n = 16) =>
  [...String(s)].length > n ? [...String(s)].slice(0, n - 1).join("") + "…" : s;
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const freeId = "__free__";
const priorGeometry = new Map();
export const forms = [
  [
    "space",
    "空间版图",
    "Attention atlas",
    "当前主题与份额",
    "Current themes and shares",
  ],
  [
    "river",
    "时间河流",
    "Project river",
    "按日期比较项目记录",
    "Project records by source date",
  ],
  [
    "drops",
    "流动形态",
    "Living field",
    "主题份额的液滴视图",
    "Theme shares as droplets",
  ],
  [
    "mosaic",
    "轮次方阵",
    "Review mosaics",
    "并排比较历史布局",
    "Compare saved layouts",
  ],
  [
    "lineage",
    "主题脉络",
    "Thread lines",
    "主题的延续、改名与合并",
    "Continuity, renaming and merges",
  ],
  [
    "yield",
    "份额让位",
    "Give & take",
    "相邻复盘的份额增减",
    "Share changes between reviews",
  ],
];
const layerOf = (state, path) => {
  let layer = state.root;
  for (const id of path) {
    const next = layer.items.find((i) => i.id === id)?.children;
    if (!next) return { items: [], used: 0, budget: 64 };
    layer = next;
  }
  return layer;
};
const svgText = (x, y, text, extra = "") =>
  `<text x="${x}" y="${y}" ${extra}>${esc(text)}</text>`;
function bind(host, callbacks) {
  host.querySelectorAll("[data-item]").forEach((el) => {
    const act = () => callbacks.select({ kind: "item", id: el.dataset.item });
    el.addEventListener("click", act);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        act();
      }
    });
  });
  host.querySelectorAll("[data-project]").forEach((el) => {
    const act = () =>
      callbacks.select({ kind: "project", id: el.dataset.project });
    el.addEventListener("click", act);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        act();
      }
    });
  });
  host.querySelectorAll("[data-frame]").forEach((el) => {
    el.addEventListener("click", () =>
      callbacks.frame(Number(el.dataset.frame)),
    );
  });
}
function blank(host, title, body) {
  host.innerHTML = `<div class="visual-empty"><h2>${title}</h2><p>${body}</p></div>`;
}
function legend(items, t) {
  return `<div class="identity-legend">${items.map((i) => `<button data-item="${esc(i.id)}" style="--identity:${color(i.id)}"><i></i>${esc(short(i.title, 22))}</button>`).join("")}<span><i class="free-key"></i>${t("留白", "Unallocated")}</span></div>`;
}

function partition(nodes, x, y, w, h) {
  if (!nodes.length) return [];
  if (nodes.length === 1) return [{ ...nodes[0], x, y, w, h }];
  const total = nodes.reduce((s, n) => s + n.share, 0);
  let cut = 1,
    a = nodes[0].share;
  while (cut < nodes.length - 1 && a < total / 2) a += nodes[cut++].share;
  const f = a / total;
  return w >= h
    ? [
        ...partition(nodes.slice(0, cut), x, y, w * f, h),
        ...partition(nodes.slice(cut), x + w * f, y, w * (1 - f), h),
      ]
    : [
        ...partition(nodes.slice(0, cut), x, y, w, h * f),
        ...partition(nodes.slice(cut), x, y + h * f, w, h * (1 - f)),
      ];
}
function atlas(host, ctx, cb) {
  const { layer, t } = ctx;
  const w = host.clientWidth,
    h = fieldHeight();
  const items = [...layer.items].sort(
    (a, b) => b.share - a.share || a.id.localeCompare(b.id),
  );
  const minor = items.filter((i) => i.share <= 1),
    nodes = items.filter((i) => i.share > 1);
  if (minor.length)
    nodes.push({
      id: "__minor__",
      title: t(`${minor.length} 条细线`, `${minor.length} smaller threads`),
      share: minor.reduce((s, i) => s + i.share, 0),
    });
  if (layer.used < 64)
    nodes.push({
      id: freeId,
      title: t("未分配", "Unallocated"),
      share: 64 - layer.used,
    });
  if (!nodes.length)
    return blank(
      host,
      t("暂无主题", "No themes yet"),
      t("首次复盘后显示。", "Available after the first review."),
    );
  const rectangles = partition(nodes, 0, 0, w, h);
  host.innerHTML = `<div class="atlas" style="height:${h}px">${rectangles
    .map((n) => {
      const area = n.w * n.h,
        free = n.id === freeId,
        minor = n.id === "__minor__",
        compact = n.h < 75;
      const font = compact ? 13 : n.w < 135 ? 15 : n.w < 190 ? 17 : 21,
        padding = compact ? 7 : 12;
      const lines = Math.max(
        1,
        Math.floor(
          (n.h -
            padding * 2 -
            (compact ? 0 : 30) -
            (n.children?.items.length ? 23 : 0)) /
            (font * 1.35),
        ),
      );
      const summary = n.summary && n.w > 210 && n.h > 190;
      return `<${free ? "div" : "button"} class="atlas-region ${free ? "is-free" : ""} ${n.w < 180 || n.h < 120 ? "is-small" : ""} ${compact ? "is-compact" : ""}" ${free ? "" : minor ? "data-minor" : `data-item="${esc(n.id)}"`} data-geometry="${esc(n.id)}" style="left:${n.x}px;top:${n.y}px;width:${n.w}px;height:${n.h}px;--identity:${color(n.id)};--title-size:${font}px;--title-lines:${lines};padding:${padding}px" title="${esc(n.title)} · ${n.share}/64" aria-label="${esc(n.title)} · ${n.share}/64"><span class="region-meta"><b>${n.share}<small>/64</small></b></span><strong>${esc(n.title)}</strong>${summary ? `<p>${esc(n.summary)}</p>` : ""}${!free && area > 65000 ? `<div class="region-reason">${esc(short(n.reason || "", 100))}</div>` : ""}${n.children?.items.length ? `<span class="region-detail">${n.children.items.length} ${t("条支线 ↗", "supporting threads ↗")}</span>` : ""}</${free ? "div" : "button"}>`;
    })
    .join(
      "",
    )}</div><p class="visual-caption">${t("面积：关注份额 · 点选查看详情", "Area: attention share · Select for details")}</p>`;
  host
    .querySelector("[data-minor]")
    ?.addEventListener("click", () =>
      cb.select({ kind: "minor", items: minor }),
    );
  const next = new Map();
  for (const rect of rectangles) {
    const el = [...host.querySelectorAll("[data-geometry]")].find(
        (e) => e.dataset.geometry === rect.id,
      ),
      p = priorGeometry.get("atlas:" + rect.id);
    if (el && p && !reduced())
      el.animate(
        [
          {
            transform: `translate(${p.x - rect.x}px,${p.y - rect.y}px) scale(${p.w / rect.w},${p.h / rect.h})`,
          },
          { transform: "none" },
        ],
        { duration: 650, easing: "cubic-bezier(.22,1,.36,1)" },
      );
    next.set("atlas:" + rect.id, rect);
  }
  for (const [id, rect] of next) priorGeometry.set(id, rect);
  bind(host, cb);
}

function river(host, ctx, cb) {
  const { landscape, t } = ctx;
  const days = landscape?.days || [];
  const projects = landscape?.projects || [];
  if (!days.length || !projects.length)
    return blank(
      host,
      t("暂无日期记录", "No dated records"),
      t(
        "此视图需要带原始日期的项目记录。",
        "This view requires project records with source dates.",
      ),
    );
  const totals = new Map(
    projects.map((p) => [
      p.id,
      days.reduce((sum, d) => sum + (d.counts[p.id] || 0), 0),
    ]),
  );
  const ordered = [...projects].sort(
    (a, b) => totals.get(b.id) - totals.get(a.id),
  );
  const top = ordered.slice(0, 8);
  if (ordered.length > 8)
    top.push({ id: "__other__", name: t("其余项目", "Other projects") });
  if (ordered.length > 8)
    totals.set(
      "__other__",
      ordered.slice(8).reduce((sum, p) => sum + totals.get(p.id), 0),
    );
  const mobile = host.clientWidth < 550;
  const w = host.clientWidth,
    left = 10,
    right = mobile ? 10 : 165,
    topY = 32,
    h = Math.max(
      180,
      Math.min(
        330,
        innerHeight -
          (host.getBoundingClientRect().top + scrollY) -
          (mobile ? 300 : 230),
      ),
    ),
    xEnd = w - right,
    plotW = xEnd - left;
  const counts = (d, id) =>
    id === "__other__"
      ? ordered.slice(8).reduce((sum, p) => sum + (d.counts[p.id] || 0), 0)
      : d.counts[id] || 0;
  const columns = days.map((d, idx) => {
    let y = topY;
    return {
      day: d,
      x: left + (idx * plotW) / Math.max(1, days.length - 1),
      bands: top.map((p) => {
        const height = d.total ? (counts(d, p.id) / d.total) * h : 0;
        const b = { id: p.id, y, height };
        y += height;
        return b;
      }),
    };
  });
  let paths = "";
  for (let j = 0; j < top.length; j++) {
    const p = top[j];
    let d = "";
    let upper = [],
      lower = [];
    const flush = () => {
      if (!upper.length) return;
      const edge = (points) =>
        points
          .map((q, i) =>
            i
              ? `C ${points[i - 1].x + (q.x - points[i - 1].x) * 0.5},${points[i - 1].y} ${points[i - 1].x + (q.x - points[i - 1].x) * 0.5},${q.y} ${q.x},${q.y}`
              : `M ${q.x},${q.y}`,
          )
          .join(" ");
      if (upper.length === 1) {
        upper[0].x -= 3;
        upper.push({ x: upper[0].x + 6, y: upper[0].y });
        lower[0].x -= 3;
        lower.push({ x: lower[0].x + 6, y: lower[0].y });
      }
      d +=
        edge(upper) +
        " L " +
        lower.at(-1).x +
        "," +
        lower.at(-1).y +
        " " +
        edge([...lower].reverse()).replace(/^M[^C]+/, "") +
        " Z ";
      upper = [];
      lower = [];
    };
    for (const c of columns) {
      if (!c.day.total) {
        flush();
        continue;
      }
      upper.push({ x: c.x, y: c.bands[j].y });
      lower.push({ x: c.x, y: c.bands[j].y + c.bands[j].height });
    }
    flush();
    paths += `<path class="river-band" d="${d}" fill="${color(p.id)}" tabindex="0" role="button" data-project="${esc(p.id)}" aria-label="${esc(p.name)}"><title>${esc(p.name)} · ${totals.get(p.id) || ""}</title></path>`;
  }
  const labelGap = Math.min(32, (h - 16) / Math.max(1, top.length - 1));
  // A keyed legend remains readable when a trailing date has no observations. Never draw
  // leaders out of an empty column: it would fabricate a latest position for every band.
  const labels = top
    .map((p, j) => {
      const y = topY + 10 + j * labelGap;
      return `<g tabindex="0" role="button" data-project="${esc(p.id)}" aria-label="${esc(p.name)} · ${totals.get(p.id) || 0}"><title>${esc(p.name)} · ${totals.get(p.id) || 0} ${t("条记录", "turns")}</title><rect x="${xEnd + 13}" y="${y - 7}" width="7" height="7" fill="${color(p.id)}"/>${svgText(xEnd + 26, y, short(p.name, 15), 'class="river-name"')}${svgText(w - 2, y, totals.get(p.id) || 0, 'text-anchor="end" class="svg-muted svg-small"')}</g>`;
    })
    .join("");

  const tickStep = Math.ceil((days.length - 1) / (mobile ? 3 : 6));
  const ticks = columns
    .map((c, i) => {
      const show =
        i === 0 ||
        i === days.length - 1 ||
        (i % tickStep === 0 && i < days.length - 1 - tickStep / 2);
      return `${show ? svgText(c.x, topY + h + 24, c.day.date.slice(5), `text-anchor="${i === 0 ? "start" : i === days.length - 1 ? "end" : "middle"}" class="svg-small svg-muted"`) : ""}${!c.day.total ? `<rect x="${c.x - (plotW / (days.length - 1)) * 0.4}" y="${topY}" width="${Math.max(5, (plotW / (days.length - 1)) * 0.8)}" height="${h}" fill="url(#river-gap)"/><title>${esc(c.day.date)} ${t("无匹配记录", "No matching records")}</title>` : ""}`;
    })
    .join("");

  const weekly = [];
  for (let a = 0; a < days.length; a += 7) {
    const chunk = days.slice(a, a + 7),
      total = chunk.reduce((sum, d) => sum + d.total, 0),
      active = projects.filter((p) => chunk.some((d) => d.counts[p.id])).length;
    weekly.push(
      `${chunk[0].date.slice(5)}—${chunk.at(-1).date.slice(5)} · ${active} ${t("个项目", "projects")} · ${total} ${t("条记录", "turns")}`,
    );
  }
  host.innerHTML = `<div class="river-periods">${weekly.map((text) => `<span>${esc(text)}</span>`).join("")}</div><div class="chart-scroll"><svg class="river-chart" viewBox="0 0 ${w} ${h + 68}" style="min-width:${w}px" role="group" aria-label="${t("根据来源原始日期绘制的项目参与河流", "Project involvement by original source date")}"><defs><pattern id="river-gap" width="6" height="6" patternUnits="userSpaceOnUse"><path d="M0 6L6 0" class="gap-stroke"/></pattern></defs>${svgText(left, 20, t("此前的项目投入记录", "Recorded project involvement"), 'class="svg-muted"')}${svgText(xEnd, 20, t("最近记录", "Latest recorded"), 'text-anchor="end" class="svg-muted"')}${mobile ? "" : svgText(w - 2, 20, t("记录数", "Turns"), 'text-anchor="end" class="svg-muted svg-small"')}${paths}${ticks}${mobile ? "" : labels}</svg></div>${mobile ? `<div class="identity-legend">${top.map((p) => `<button data-project="${esc(p.id)}" style="--identity:${color(p.id)}"><i></i>${esc(p.name)} · ${totals.get(p.id) || 0}</button>`).join("")}</div>` : ""}<p class="visual-caption">${t("带宽：当日发言记录占比（非工时） · 斜线：无匹配记录。", "Width: share of recorded Owner turns, not hours worked. Hatching: no matching records.")}</p>${landscape.coverage?.truncated ? `<p class="coverage-warning">${t("此时段记录超过读取上限，当前河流只覆盖部分资料。", "This interval exceeds the read limit; the river has partial coverage.")}</p>` : ""}`;
  bind(host, cb);
}

function drops(host, ctx, cb) {
  const { layer, t } = ctx;
  const w = host.clientWidth,
    h = fieldHeight(430);
  const large = layer.items.filter((i) => i.share >= 3).slice(0, 24),
    small = layer.items.filter((i) => i.share < 3);
  host.innerHTML = `<div class="drop-stage" style="height:${h}px"><canvas aria-hidden="true"></canvas><div class="drop-targets"></div></div><div class="sediment ${small.length ? "" : "is-empty"}"><span>${t("低份额主题", "Smaller shares")} · ${small.length}</span><div>${small.map((i) => `<button class="small-drop" data-item="${esc(i.id)}" style="--identity:${color(i.id)}" aria-label="${esc(i.title)} · ${i.share}/64" title="${esc(i.title)}"></button>`).join("")}</div></div>${budgetCells(layer)}<p class="visual-caption">${t("液滴面积：关注份额 · 点选查看详情", "Drop area: attention share · Select for details")}</p>`;
  const canvas = host.querySelector("canvas"),
    render = createRenderer(canvas);
  render.resize(w, h, Math.min(devicePixelRatio, 2));
  const nodes = large.map((item) => ({
    id: item.id,
    share: item.share,
    r: Math.sqrt(((item.share / 64) * w * h * 0.34) / Math.PI),
    label: { w: 0, h: 0, inside: true },
    prev: priorGeometry.get("drop:" + item.id),
  }));
  const placed = solveLayout(nodes, { w, h }, { gap: 14, margin: 22 });
  const target = nodes.map((n) => ({
    ...n,
    ...placed.positions.get(n.id),
    color: rgb(color(n.id)),
    alpha: 1,
    ring: 0,
  }));
  const from = target.map((n) => ({
    ...n,
    ...(priorGeometry.get("drop:" + n.id) || {
      x: w / 2,
      y: h / 2,
      r: 0,
      alpha: 0,
    }),
  }));
  const overlay = host.querySelector(".drop-targets");
  overlay.innerHTML = target
    .map((n) => {
      const item = large.find((i) => i.id === n.id);
      return `<button class="drop-hit" data-item="${esc(n.id)}" aria-label="${esc(item.title)} · ${n.share}/64" style="width:${n.r * 1.6}px;height:${n.r * 1.6}px"><b>${n.share}</b><span>${esc(short(item.title, n.r > 70 ? 20 : 12))}</span></button>`;
    })
    .join("");
  const buttons = [...overlay.children];
  let animation = 0,
    start = performance.now();
  const paint = (now) => {
    const f = reduced() ? 1 : Math.min(1, (now - start) / 760),
      ease = 1 - (1 - f) ** 4;
    const bodies = target.map((n, i) => {
      const p = from[i];
      return {
        ...n,
        x: p.x + (n.x - p.x) * ease,
        y: p.y + (n.y - p.y) * ease,
        r: p.r + (n.r - p.r) * ease,
        alpha: p.alpha + (1 - p.alpha) * ease,
      };
    });
    render.render(bodies);
    bodies.forEach((b, i) => {
      buttons[i].style.transform =
        `translate(${b.x - target[i].r * 0.8}px,${b.y - target[i].r * 0.8}px)`;
      buttons[i].style.opacity = String(b.alpha);
    });
    if (f < 1) animation = requestAnimationFrame(paint);
  };
  animation = requestAnimationFrame(paint);
  target.forEach((n) =>
    priorGeometry.set("drop:" + n.id, { x: n.x, y: n.y, r: n.r, alpha: 1 }),
  );
  bind(host, cb);
  return () => {
    cancelAnimationFrame(animation);
    render.dispose();
  };
}
function budgetCells(layer) {
  const cells = [];
  for (const i of layer.items)
    for (let n = 0; n < i.share; n++)
      cells.push(
        `<i style="background:${color(i.id)}" title="${esc(i.title)}"></i>`,
      );
  while (cells.length < 64) cells.push('<i class="blank-cell"></i>');
  return `<div class="budget-cells" aria-label="${layer.used}/64">${cells.join("")}</div>`;
}

function mosaic(host, ctx, cb) {
  const { history, t } = ctx;
  if (!history.length)
    return blank(
      host,
      t("暂无历史复盘", "No saved reviews"),
      t("首次复盘后显示。", "Available after the first review."),
    );
  host.innerHTML = `<div class="mosaic-intro"><strong>${history.length} ${t("轮复盘", "reviews")}</strong><span>${t("每格 1 份，空格未分配", "1 share per cell; empty = unallocated")}</span></div><div class="mosaic-wall">${history
    .map((f) => {
      const layer = layerOf(f.state, ctx.path),
        cells = [];
      for (const item of layer.items)
        for (let n = 0; n < item.share; n++)
          cells.push(
            `<i style="background:${color(item.id)}" title="${esc(item.title)}"></i>`,
          );
      while (cells.length < 64) cells.push('<i class="blank-cell"></i>');
      return `<button class="mosaic-frame ${f.id === ctx.selected ? "is-selected" : ""}" data-frame="${f.id}" aria-label="${esc(f.at)}"><span class="mosaic-grid">${cells.join("")}</span><time>${new Date(f.at).toLocaleDateString(t("zh-CN", "en"), { month: "short", day: "numeric" })}</time><small>${new Date(f.at).toLocaleTimeString(t("zh-CN", "en"), { hour: "2-digit", minute: "2-digit" })} · ${layer.used}/64</small></button>`;
    })
    .join(
      "",
    )}</div>${legend(ctx.layer.items, t)}<p class="visual-caption">${t("点选查看该轮复盘。", "Select a saved review.")}</p>`;
  bind(host, cb);
}

function lineage(host, ctx, cb) {
  const { history, t } = ctx;
  if (history.length < 2)
    return blank(
      host,
      t("历史记录不足", "More history needed"),
      t(
        "至少需要两轮已保存的复盘。",
        "At least two saved reviews are required.",
      ),
    );
  const states = history.map((f) => layerOf(f.state, ctx.path));
  const subjects = new Map();
  for (const layer of states)
    for (const item of layer.items) {
      const previous = subjects.get(item.id);
      subjects.set(item.id, {
        ...item,
        total: (previous?.total || 0) + item.share,
      });
    }
  const items = [...subjects.values()]
    .sort((a, b) => b.total - a.total)
    .slice(0, 8);
  const width = Math.max(host.clientWidth, items.length * 135 + 75),
    top = 65,
    rowH = 52,
    height = top + states.length * rowH + 25,
    laneW = (width - 80) / Math.max(1, items.length);
  let body = "";
  for (let r = 0; r < states.length; r++) {
    const y = top + r * rowH;
    body += `<line x1="66" y1="${y}" x2="${width}" y2="${y}" class="chart-guide"/>${svgText(4, y + 4, new Date(history[r].at).toLocaleDateString(t("zh-CN", "en"), { month: "2-digit", day: "2-digit" }), 'class="svg-small svg-muted"')}`;
  }
  for (let c = 0; c < items.length; c++) {
    const subject = items[c],
      x = 85 + c * laneW;
    body += `<g tabindex="0" role="button" data-item="${esc(subject.id)}" aria-label="${esc(subject.title)}">${svgText(x, 20, short(subject.title, 14), `class="thread-title"`)}`;
    let previous = null;
    for (let r = 0; r < states.length; r++) {
      const item = states[r].items.find((i) => i.id === subject.id),
        y = top + r * rowH;
      if (item) {
        if (previous)
          body += `<line x1="${x}" y1="${previous.y}" x2="${x}" y2="${y}" stroke="${color(subject.id)}" stroke-width="${Math.max(2, Math.sqrt(item.share) * 2.4)}" ${r - previous.r > 1 ? 'stroke-dasharray="3 4"' : ""}/>`;
        const changed =
          !previous ||
          previous.item.title !== item.title ||
          previous.item.share !== item.share;
        body += `<circle cx="${x}" cy="${y}" r="${changed ? 4 : 2}" fill="var(--ink)" stroke="var(--paper)"/>`;
        if (changed)
          body += svgText(
            x + 10,
            y + 4,
            `${item.share} / 64`,
            'class="svg-small"',
          );
        if (previous && previous.item.title !== item.title)
          body += svgText(
            x + 10,
            y + 19,
            short(item.title, 12),
            'class="svg-muted svg-small"',
          );
        previous = { y, item, r };
      } else if (previous && previous.r === r - 1) {
        body += `<path d="M${x - 6},${y - 22}h12" stroke="var(--ink)"/>`;
      }
    }
    body += "</g>";
  }
  for (let r = 1; r < history.length; r++) {
    for (const old of history[r].state.not_active || []) {
      if (
        !old.merged_into ||
        history[r - 1].state.not_active?.some((i) => i.id === old.id)
      )
        continue;
      const a = items.findIndex((i) => i.id === old.id),
        b = items.findIndex((i) => i.id === old.merged_into);
      if (a < 0 || b < 0) continue;
      const x1 = 85 + a * laneW,
        x2 = 85 + b * laneW,
        y1 = top + (r - 1) * rowH,
        y2 = top + r * rowH;
      body += `<path d="M${x1},${y1} C${x1},${y1 + rowH / 2} ${x2},${y2 - rowH / 2} ${x2},${y2}" fill="none" stroke="${color(old.id)}" stroke-width="3"><title>${esc(old.title)} → ${esc(items[b].title)}</title></path>`;
    }
  }
  host.innerHTML = `<div class="chart-scroll"><svg viewBox="0 0 ${width} ${height}" style="min-width:${width}px" role="group" aria-label="${t("持续主题的身份与份额变化", "Theme identity and share over reviews")}">${body}</svg></div><p class="visual-caption">${t("线宽：份额 · 节点：变化 · 虚线：期间未在看板上", "Width: share · Nodes: changes · Dashes: absent from the board")}</p>`;
  bind(host, cb);
}

function yieldMap(host, ctx, cb) {
  const { history, t } = ctx;
  if (history.length < 2)
    return blank(
      host,
      t("历史记录不足", "More history needed"),
      t(
        "至少需要两轮已保存的复盘。",
        "At least two saved reviews are required.",
      ),
    );
  const rows = [];
  for (let n = 1; n < history.length; n++) {
    const old = layerOf(history[n - 1].state, ctx.path),
      next = layerOf(history[n].state, ctx.path),
      before = new Map(old.items.map((i) => [i.id, i])),
      after = new Map(next.items.map((i) => [i.id, i]));
    const changes = [...new Set([...before.keys(), ...after.keys()])]
      .map((id) => ({
        id,
        title: (after.get(id) || before.get(id)).title,
        delta: (after.get(id)?.share || 0) - (before.get(id)?.share || 0),
      }))
      .filter((i) => i.delta);
    if (old.used !== next.used)
      changes.push({
        id: freeId,
        title: t("留白", "Unallocated"),
        delta: old.used - next.used,
      });
    rows.push({
      frame: history[n],
      out: changes.filter((i) => i.delta < 0),
      in: changes.filter((i) => i.delta > 0),
      free: 64 - next.used,
    });
  }
  const scale = Math.max(
    1,
    ...rows.map((r) => r.in.reduce((sum, i) => sum + i.delta, 0)),
  );
  const segment = (item) =>
    `<span style="width:${(Math.abs(item.delta) / scale) * 100}%;--identity:${color(item.id)}" class="yield-segment ${item.id === freeId ? "is-free" : ""}" title="${esc(item.title)} ${item.delta > 0 ? "+" : ""}${item.delta}">${Math.abs(item.delta) / scale > 0.22 ? `${esc(short(item.title, 6))} ${item.delta > 0 ? "+" : ""}${item.delta}` : ""}</span>`;
  host.innerHTML = `<p class="yield-scale">${t(`统一尺度 · 每侧最多 ${scale} 份`, `Shared scale · up to ${scale} shares per side`)}</p><div class="yield-labels"><span>${t("每一轮", "Review")}</span><span>← ${t("让出", "Released")}</span><span>${t("留白", "Free")}</span><span>${t("获得", "Gained")} →</span></div><div class="yield-map">${rows.map((r) => `<button class="yield-round ${r.frame.id === ctx.selected ? "is-selected" : ""}" data-frame="${r.frame.id}" aria-label="${esc(r.frame.at)}"><time>${new Date(r.frame.at).toLocaleString(t("zh-CN", "en"), { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</time><span class="yield-wing out">${r.out.map(segment).join("")}</span><b>${r.free}</b><span class="yield-wing">${r.in.map(segment).join("")}</span></button>`).join("")}</div>${legend(ctx.layer.items, t)}<p class="visual-caption">${t("每行比较相邻两轮，包含未分配份额。", "Each row compares adjacent reviews, including unallocated shares.")}</p>`;
  bind(host, cb);
}

export function mountVisual(host, context, callbacks) {
  prepareColors(context);
  const ctx = { ...context, layer: layerOf(context.state, context.path || []) };
  if (context.form === "space") return atlas(host, ctx, callbacks);
  if (context.form === "drops") return drops(host, ctx, callbacks);
  if (context.form === "mosaic") return mosaic(host, ctx, callbacks);
  if (context.form === "lineage") return lineage(host, ctx, callbacks);
  if (context.form === "yield") return yieldMap(host, ctx, callbacks);
  return river(host, ctx, callbacks);
}
