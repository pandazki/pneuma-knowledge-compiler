import { mountVisual, forms, color } from "./visuals.js";

const root = document.querySelector("#board"),
  params = new URLSearchParams(location.search);
const zh = (params.get("locale") || navigator.language).startsWith("zh");
const t = (cn, en) => (zh ? cn : en),
  esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
document.documentElement.lang = zh ? "zh-CN" : "en";
if (["light", "dark"].includes(params.get("theme")))
  document.documentElement.dataset.theme = params.get("theme");
const date = (value) =>
  new Date(value).toLocaleString(zh ? "zh-CN" : "en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
const names = {
  summary: t("阶段总结", "Summary"),
  direction: t("方向变化", "Changes"),
  tensions: t("未解问题", "Open questions"),
  next_focus: t("后续考虑", "Outlook"),
};
let live = null,
  history = [],
  selected = null,
  frame = null,
  path = [],
  reader = null,
  settingsOpen = params.get("settings") === "1";
let pending = false,
  message = "",
  playing = null,
  requestVersion = 0,
  disposeVisual = null,
  formDraft = null,
  dirtyRender = false,
  lastPaint = "";
const drafts = new Map(),
  noteRequests = new Map();
const current = () =>
  selected === null
    ? {
        state: live?.state,
        reflection: live?.reflection,
        landscape: live?.landscape,
        at: live?.status.last_run
          ? new Date(live.status.last_run * 1000).toISOString()
          : null,
      }
    : frame;
const form = () =>
  live?.preferences.board === "home"
    ? "space"
    : live?.preferences.board || "space";
async function api(path, options = {}) {
  const response = await fetch("/home/attention" + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    let value;
    try {
      value = await response.json();
    } catch {}
    const error = new Error(
      typeof value?.detail === "string"
        ? value.detail
        : `${t("请求失败", "Request failed")} (${response.status})`,
    );
    error.status = response.status;
    throw error;
  }
  return response.json();
}
function flatten(layer, result = []) {
  for (const item of layer?.items || []) {
    result.push(item);
    flatten(item.children, result);
  }
  return result;
}
function layer() {
  let next = current().state.root;
  for (const id of path) {
    next = next.items.find((item) => item.id === id)?.children || {
      items: [],
      used: 0,
      budget: 64,
    };
  }
  return next;
}
function frameId() {
  return selected ?? Math.max(0, ...history.map((f) => f.id));
}
function cutoffHistory() {
  const end = selected === null ? Infinity : selected;
  return history.filter((f) => f.id <= end).sort((a, b) => a.id - b.id);
}

function refsHTML(refs) {
  return (refs || [])
    .map(
      (ref, i) =>
        `<button class="evidence-ref" data-ref="${esc(ref)}">${t("依据", "Evidence")} ${i + 1} <span>↗</span></button>`,
    )
    .join("");
}
function reflectionHTML() {
  const value = current()?.reflection || {};
  return `<div class="reflection-reading">${
    Object.entries(names)
      .filter(([key]) => value[key])
      .map(
        ([key, name]) =>
          `<section class="reflection-section"><h3>${name}</h3><p>${esc(value[key].text)}</p><div class="evidence-links">${refsHTML(value[key].refs)}</div></section>`,
      )
      .join("") ||
    `<p class="empty-copy">${t("本轮没有复盘正文。", "No written reflection in this review.")}</p>`
  }</div>`;
}
function readerHTML() {
  if (!reader)
    return `<section class="reading"><div class="reading-head"><h2>${t("复盘", "Reflection")}</h2></div>${reflectionHTML()}</section>`;
  if (reader.kind === "evidence")
    return `<section class="reading"><div class="reading-head"><h2>${t("依据", "Evidence")}</h2><button data-close-reader>${t("收起", "Close")}</button></div><p class="source-address">${esc(reader.ref)}</p><pre class="source-text">${esc(reader.text || t("正在读取…", "Loading…"))}</pre></section>`;
  if (reader.kind === "minor")
    return `<section class="reading"><div class="reading-head"><h2>${t("低份额的支线", "Quieter threads")}</h2><button data-close-reader>${t("收起", "Close")}</button></div>${reader.items.map((i) => `<button class="supporting-thread" data-pick="${esc(i.id)}"><i style="background:${color(i.id)}"></i><span>${esc(i.title)}</span><b>${i.share}</b></button>`).join("")}</section>`;
  if (reader.kind === "project") {
    const landscape = current().landscape,
      project = landscape?.projects?.find((p) => p.id === reader.id);
    const days = landscape?.days || [],
      others = (landscape?.projects || []).slice(8).map((p) => p.id),
      count = (d) =>
        reader.id === "__other__"
          ? others.reduce((sum, id) => sum + (d.counts[id] || 0), 0)
          : d.counts[reader.id] || 0,
      active = days.filter((d) => count(d)),
      total = active.reduce((sum, d) => sum + count(d), 0);
    return `<section class="reading"><div class="reading-head"><h2 style="--identity:${color(reader.id)}">${esc(project?.name || t("其余项目", "Other projects"))}</h2><button data-close-reader>${t("收起", "Close")}</button></div><p class="project-observation">${active.length} ${t("个日期留下参与记录", "days with recorded involvement")} · ${total} ${t("条 Owner 发言", "Owner turns")}</p>${reflectionHTML()}</section>`;
  }
  const item =
    flatten(current().state.root).find((i) => i.id === reader.id) ||
    cutoffHistory()
      .flatMap((f) => flatten(f.state.root))
      .reverse()
      .find((i) => i.id === reader.id);
  if (!item) return "";
  const notes = current().state.annotations.filter((n) => n.item === item.id);
  return `<section class="reading"><div class="reading-head"><span class="theme-marker" style="--identity:${color(item.id)}"></span><h2>${esc(item.title)}</h2><button data-close-reader>${t("收起", "Close")}</button></div><p class="theme-summary">${esc(item.summary)}</p><p class="quiet-copy">${esc(item.reason)}</p><div class="evidence-links">${refsHTML((item.sources || []).map((s) => s.ref))}</div>${item.children?.items.length ? `<div class="supporting"><div class="reading-head"><h3>${t("相关主题", "Related themes")}</h3><button data-zoom="${esc(item.id)}">${t("下钻布局", "Zoom in")} ↗</button></div>${item.children.items.map((i) => `<button class="supporting-thread" data-pick="${esc(i.id)}"><i style="background:${color(i.id)}"></i><span>${esc(i.title)}</span><b>${i.share}</b></button>`).join("")}</div>` : ""}${notes.map((n) => `<p class="saved-note">${esc(n.text)} <small>${n.status === "saved" ? t("待下次复盘", "For the next review") : t("已纳入复盘", "Acknowledged")}</small></p>`).join("")}${selected === null ? `<form id="theme-note" data-item="${esc(item.id)}"><label for="note-text">${t("批注", "Note")}</label><textarea id="note-text" maxlength="4000" required>${esc(drafts.get(item.id) || "")}</textarea><button type="submit">${t("保存批注", "Save note")}</button></form>` : `<p class="quiet-copy">${t("历史记录，只读。", "Read-only historical record.")}</p>`}</section>`;
}
function sketch(name) {
  const colors = ["#5a9b8e", "#c88d65", "#a9a05b"];
  if (name === "river")
    return `<svg viewBox="0 0 100 44"><path d="M0 7C30 7 40 20 60 8S80 18 100 4V17C80 24 65 17 60 21S30 18 0 22Z" fill="${colors[0]}"/><path d="M0 25C30 22 45 33 60 24S80 30 100 21V36C80 42 65 32 60 38S30 33 0 40Z" fill="${colors[1]}"/></svg>`;
  if (name === "space")
    return `<svg viewBox="0 0 100 44"><path d="M0 0H49V44H0Z" fill="${colors[0]}"/><path d="M51 0H100V25H51Z" fill="${colors[1]}"/><path d="M51 27H78V44H51Z" fill="${colors[2]}"/><path d="M80 27H100V44H80Z" fill="none" stroke="currentColor" stroke-dasharray="2 2"/></svg>`;
  if (name === "drops")
    return `<svg viewBox="0 0 100 44"><circle cx="36" cy="23" r="19" fill="${colors[0]}"/><circle cx="70" cy="16" r="12" fill="${colors[1]}"/><circle cx="77" cy="36" r="6" fill="${colors[2]}"/></svg>`;
  if (name === "mosaic")
    return `<svg viewBox="0 0 100 44">${Array.from({ length: 32 }, (_, n) => `<rect x="${(n % 8) * 12}" y="${Math.floor(n / 8) * 10}" width="9" height="7" fill="${n > 25 ? "none" : colors[Math.floor(n / 7) % 3]}" stroke="${n > 25 ? "currentColor" : "none"}"/>`).join("")}</svg>`;
  if (name === "lineage")
    return `<svg viewBox="0 0 100 44">${colors.map((c, i) => `<path d="M${20 + i * 30} 2V42" stroke="${c}" stroke-width="${3 + i * 2}"/><circle cx="${20 + i * 30}" cy="${12 + i * 10}" r="4" fill="currentColor"/>`).join("")}</svg>`;
  return `<svg viewBox="0 0 100 44">${colors.map((c, i) => `<path d="M${10 + i * 7} ${8 + i * 14}H45 M55 ${8 + i * 14}H${90 - i * 7}" stroke="${c}" stroke-width="8"/>`).join("")}</svg>`;
}
function settingsHTML() {
  const p = formDraft || live.preferences;
  return `<section class="settings-panel"><div class="reading-head"><h2>${t("视图", "Views")}</h2><button id="settings-close">${t("完成", "Done")}</button></div><div class="form-gallery" role="radiogroup" aria-label="${t("复盘视图", "Review view")}">${forms.map(([id, cn, en, desc, enDesc]) => `<button role="radio" aria-checked="${form() === id}" data-style="${id}">${sketch(id)}<strong>${zh ? cn : en}</strong><span>${zh ? desc : enDesc}</span></button>`).join("")}</div><form id="preferences"><h3>${t("复盘节奏", "Review rhythm")}</h3><label class="setting">${t("自动复盘", "Automatic review")}<input type="checkbox" name="enabled" ${p.enabled ? "checked" : ""}></label><label class="setting">${t("回看范围", "Look back")}<select name="horizon_days">${[7, 14, 30, 60, 90].map((n) => `<option value="${n}" ${n === p.horizon_days ? "selected" : ""}>${n} ${t("天", "days")}</option>`).join("")}</select></label>${[
    [
      "window_seconds",
      t("新知识合并窗口（分钟）", "Batch window (minutes)"),
      30,
      86400,
    ],
    [
      "min_interval_seconds",
      t("最短复盘间隔（分钟）", "Minimum review interval (minutes)"),
      30,
      86400,
    ],
    [
      "idle_seconds",
      t("安静时复盘（小时）", "Quiet review interval (hours)"),
      300,
      604800,
    ],
    ["threshold", t("新版本触发阈值", "Changed-version threshold"), 1, 1000],
  ]
    .map(([key, label, min, max]) => {
      const scale =
        key === "idle_seconds" ? 3600 : key.endsWith("seconds") ? 60 : 1;
      return `<label class="setting">${label}<input name="${key}" type="number" min="${min / scale}" max="${max / scale}" step="any" value="${p[key] / scale}" data-scale="${scale}" required></label>`;
    })
    .join(
      "",
    )}<p class="quiet-copy">${t("没有新材料时，仍按安静间隔复盘。", "Quiet reviews run even when no new material arrives.")}</p><button type="submit">${t("保存复盘设置", "Save review settings")}</button></form></section>`;
}
function controlsHTML() {
  const ordered = [...history].sort((a, b) => a.id - b.id),
    index =
      selected === null
        ? ordered.length
        : ordered.findIndex((f) => f.id === selected);
  return `<footer class="time-machine"><div class="time-caption"><button id="previous" aria-label="${t("上一轮复盘", "Previous review")}" ${index <= 0 ? "disabled" : ""}>←</button><button id="play" ${ordered.length < 2 ? "disabled" : ""}>${playing ? t("暂停", "Pause") : t("回放", "Play")}</button><button id="next" aria-label="${t("下一轮复盘", "Next review")}" ${selected === null ? "disabled" : ""}>→</button><span><b>${t("已保存的复盘", "Saved reviews")}</b> · ${selected === null ? t(`最新 · ${ordered.length} 轮`, `Latest · ${ordered.length} reviews`) : `${Math.max(0, index) + 1}/${ordered.length} · ${date(frame.at)}`}</span><button id="latest" ${selected === null ? "disabled" : ""}>${t("回到现在", "Back to now")}</button><button id="earlier" ${!ordered.length || ordered[0].id === 1 ? "disabled" : ""}>${t("更早", "Earlier")}</button></div><label class="sr-only" for="timeline">${t("实际复盘的时光机", "Time machine of saved reviews")}</label><input id="timeline" type="range" min="0" max="${ordered.length}" value="${index}" aria-valuetext="${selected === null ? t("最新复盘", "Latest review") : date(frame.at)}" ${!ordered.length ? "disabled" : ""}></footer>`;
}
function render() {
  if (!live || !current()?.state) return;
  const focused = document.activeElement?.id;
  disposeVisual?.();
  disposeVisual = null;
  dirtyRender = false;
  const f = form(),
    itemLayer = layer(),
    landscape = current().landscape;
  const period =
    landscape?.since && landscape?.until
      ? `${landscape.since.slice(5)}—${landscape.until.slice(5)}`
      : "";
  root.innerHTML = `<header class="board-header"><div class="brand"><b>fold</b><span>${esc(live.library)}</span></div><div class="header-actions"><span class="review-age">${current().at ? date(current().at) : t("尚无复盘", "No reviews yet")}</span><button id="settings" aria-expanded="${settingsOpen}">${t("设置", "Settings")}</button></div></header>${settingsOpen ? settingsHTML() : ""}
 <div class="view-tools"><label class="view-select"><span class="sr-only">${t("复盘视图", "Review view")}</span><select id="view">${forms.map(([id, cn, en]) => `<option value="${id}" ${id === f ? "selected" : ""}>${zh ? cn : en}</option>`).join("")}</select></label><span class="view-period">${esc(period)}</span>${f === "river" ? `<span class="view-measure">${current().landscape?.days?.length || live.preferences.horizon_days || 14} ${t("天", "days")}</span>` : `<span class="view-measure">${itemLayer.used} / 64 · ${t("留白", "free")} ${64 - itemLayer.used}</span>`}</div>
 ${message ? `<p class="notice" role="status">${esc(message)}</p>` : ""}${live.status.error ? `<p class="notice">${esc(live.status.error)}</p>` : ""}${selected !== null ? `<p class="historical-mark">${t("历史复盘", "Past review")} · ${date(frame.at)}</p>` : ""}
 ${path.length ? `<nav class="zoom-path"><button id="zoom-out">← ${t("上一级", "Back")}</button><span>${path.map((id) => esc(flatten(current().state.root).find((i) => i.id === id)?.title || id)).join(" / ")}</span></nav>` : ""}
 <div id="visual" class="visual-surface" data-form="${f}"></div><div id="reader">${readerHTML()}</div>
 <div class="review-status"><span>${live.status.running ? t("复盘中…", "Reviewing…") : live.worker_alive ? (live.preferences.enabled ? t("自动复盘已开启", "Automatic review on") : t("自动复盘已关闭", "Automatic review off")) : t("复盘进程未连接", "Review worker disconnected")}</span><button id="review" ${pending || live.status.running ? "disabled" : ""}>${t("重新复盘", "Review again")}</button></div>${controlsHTML()}`;
  disposeVisual =
    mountVisual(
      document.querySelector("#visual"),
      {
        form: f,
        tenant: live.tenant,
        state: current().state,
        landscape: current().landscape,
        history: cutoffHistory(),
        path,
        selected: frameId(),
        t,
      },
      {
        select: (value) => {
          reader = value;
          renderReader(true);
        },
        frame: (id) => void choose(id),
      },
    ) || null;
  wire();
  if (focused) document.getElementById(focused)?.focus({ preventScroll: true });
  root.setAttribute("aria-busy", "false");
  lastPaint = paintKey(live);
}
function renderReader(scroll = false) {
  document.querySelector("#reader").innerHTML = readerHTML();
  wireReader();
  if (scroll)
    document.querySelector("#reader").scrollIntoView({
      block: "nearest",
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
}
function wireReader() {
  root.querySelectorAll("[data-close-reader]").forEach(
    (b) =>
      (b.onclick = () => {
        reader = null;
        renderReader();
      }),
  );
  root.querySelectorAll("[data-pick]").forEach(
    (b) =>
      (b.onclick = () => {
        reader = { kind: "item", id: b.dataset.pick };
        renderReader();
      }),
  );
  root.querySelectorAll("[data-zoom]").forEach(
    (b) =>
      (b.onclick = () => {
        path.push(b.dataset.zoom);
        reader = null;
        render();
      }),
  );
  root.querySelectorAll("[data-ref]").forEach(
    (b) =>
      (b.onclick = async () => {
        reader = { kind: "evidence", ref: b.dataset.ref, text: "" };
        renderReader(true);
        try {
          const value = await api(
            "/evidence?ref=" + encodeURIComponent(b.dataset.ref),
          );
          if (reader?.ref === b.dataset.ref) {
            reader.text = value.text;
            renderReader();
          }
        } catch (e) {
          if (reader?.ref === b.dataset.ref) {
            reader.text = String(e);
            renderReader();
          }
        }
      }),
  );
  const note = root.querySelector("#theme-note");
  if (note) {
    note.querySelector("textarea").oninput = (e) =>
      drafts.set(note.dataset.item, e.target.value);
    note.onsubmit = (e) => {
      e.preventDefault();
      const item = note.dataset.item,
        text = note.querySelector("textarea").value.trim();
      if (!text) return;
      let request = noteRequests.get(item);
      if (request?.text !== text) {
        request = {
          item,
          text,
          event_seq: live.state.last_event_seq,
          batch_id: "note-" + crypto.randomUUID(),
        };
        noteRequests.set(item, request);
      }
      void action(async () => {
        await api("/annotations", {
          method: "POST",
          body: JSON.stringify(request),
        });
        drafts.delete(item);
        noteRequests.delete(item);
        message = t("批注已保存。", "Note saved.");
        await refresh(true);
      });
    };
  }
}
function readPreferences(form) {
  const d = new FormData(form),
    value = {
      enabled: d.has("enabled"),
      horizon_days: Number(d.get("horizon_days")),
    };
  for (const input of form.querySelectorAll("input[data-scale]"))
    value[input.name] = Math.round(
      Number(input.value) * Number(input.dataset.scale),
    );
  return value;
}
function wire() {
  const setForm = (value) =>
    action(async () => {
      await api("/preferences", {
        method: "PATCH",
        body: JSON.stringify({ board: value }),
      });
      path = [];
      reader = null;
      await refresh(true);
    });
  document.querySelector("#view").onchange = (e) =>
    void setForm(e.target.value);
  document
    .querySelectorAll("[data-style]")
    .forEach((b) => (b.onclick = () => void setForm(b.dataset.style)));
  document.querySelector("#settings").onclick = () => {
    settingsOpen = !settingsOpen;
    render();
    if (settingsOpen)
      document
        .querySelector(".settings-panel")
        .scrollIntoView({ block: "start" });
  };
  document.querySelector("#settings-close")?.addEventListener("click", () => {
    settingsOpen = false;
    render();
    window.scrollTo(0, 0);
  });
  document.querySelector("#preferences")?.addEventListener("input", (e) => {
    formDraft = { ...live.preferences, ...readPreferences(e.currentTarget) };
  });
  document.querySelector("#preferences")?.addEventListener("submit", (e) => {
    e.preventDefault();
    void action(async () => {
      await api("/preferences", {
        method: "PATCH",
        body: JSON.stringify(readPreferences(e.target)),
      });
      formDraft = null;
      message = t(
        "复盘设置已保存。回看范围在下一轮复盘生效。",
        "Saved. The look-back range applies to the next review.",
      );
      await refresh(true);
    });
  });
  document.querySelector("#zoom-out")?.addEventListener("click", () => {
    path.pop();
    reader = null;
    render();
  });
  document.querySelector("#review").onclick = () =>
    void action(async () => {
      await api("/review", { method: "POST" });
      message = t(
        "已排队，将在下个可用时段复盘。",
        "Queued for the next available review slot.",
      );
    });
  const ordered = [...history].sort((a, b) => a.id - b.id),
    index =
      selected === null
        ? ordered.length
        : ordered.findIndex((f) => f.id === selected);
  document.querySelector("#previous").onclick = () => {
    stop();
    void choose(ordered[Math.max(0, index - 1)]?.id ?? null);
  };
  document.querySelector("#next").onclick = () => {
    stop();
    void choose(ordered[index + 1]?.id ?? null);
  };
  document.querySelector("#latest").onclick = () => {
    stop();
    void choose(null);
  };
  document.querySelector("#timeline").onchange = (e) => {
    stop();
    void choose(ordered[Number(e.target.value)]?.id ?? null);
  };
  document.querySelector("#play").onclick = () => {
    if (playing) {
      stop();
      render();
      return;
    }
    let n = index >= ordered.length - 1 ? 0 : index;
    void choose(ordered[n]?.id ?? null);
    playing = setInterval(() => {
      n++;
      if (n >= ordered.length) {
        stop();
        void choose(null);
      } else void choose(ordered[n].id);
    }, 2200);
  };
  document.querySelector("#earlier").onclick = () =>
    void action(async () => {
      const older = await api(
        "/history?before=" + Math.min(...history.map((f) => f.id)),
      );
      history = [
        ...new Map([...history, ...older].map((f) => [f.id, f])).values(),
      ];
    });
  wireReader();
}
function stop() {
  clearInterval(playing);
  playing = null;
}
async function choose(id) {
  const token = ++requestVersion;
  try {
    const next = id === null ? null : await api("/frames/" + id);
    if (token !== requestVersion) return;
    selected = id;
    frame = next;
    reader = null;
    render();
  } catch (e) {
    message = String(e);
    render();
  }
}
async function action(operation) {
  if (pending) return;
  pending = true;
  try {
    await operation();
  } catch (e) {
    message = String(e);
    if (e.status === 409) {
      noteRequests.clear();
      await refresh(true).catch(() => {});
    }
  } finally {
    pending = false;
    render();
  }
}
function paintKey(data) {
  return JSON.stringify([
    data.state.last_event_seq,
    data.frames[0]?.id,
    data.preferences,
    data.status.running,
    data.status.error,
    data.worker_alive,
  ]);
}
async function refresh(force = false) {
  const next = await api("/state");
  if (!live || next.frames[0]?.id !== live.frames[0]?.id) {
    const rows = await api("/history");
    history = [
      ...new Map([...history, ...rows].map((f) => [f.id, f])).values(),
    ];
  }
  live = next;
  if (force || lastPaint !== paintKey(next) || dirtyRender) {
    if (
      !force &&
      (document.activeElement?.matches("textarea,input,select") || formDraft)
    ) {
      dirtyRender = true;
      return;
    }
    render();
  }
}
let resizing;
window.addEventListener("resize", () => {
  clearTimeout(resizing);
  resizing = setTimeout(() => {
    if (live) render();
  }, 120);
});
root.addEventListener("focusout", () =>
  setTimeout(() => {
    if (dirtyRender) void refresh();
  }, 0),
);
window.addEventListener("keydown", (e) => {
  if (
    e.defaultPrevented ||
    e.target.closest(
      "input,textarea,select,button,[role=button],[role=radio]",
    ) ||
    e.metaKey ||
    e.ctrlKey ||
    e.altKey
  )
    return;
  if (e.key === "ArrowLeft") {
    e.preventDefault();
    document.querySelector("#previous")?.click();
  }
  if (e.key === "ArrowRight") {
    e.preventDefault();
    document.querySelector("#next")?.click();
  }
  if (e.key === " ") {
    e.preventDefault();
    document.querySelector("#play")?.click();
  }
  if (e.key === "Escape" && path.length) {
    path.pop();
    reader = null;
    render();
  }
});
refresh().catch((e) => {
  root.setAttribute("aria-busy", "false");
  root.innerHTML = `<div class="visual-empty"><h1>${t("暂时无法读取复盘", "Review unavailable")}</h1><p>${esc(String(e))}</p><button id="retry">${t("重试", "Retry")}</button></div>`;
  document.querySelector("#retry").onclick = () => location.reload();
});
setInterval(() => {
  if (!document.hidden && !pending)
    void refresh().catch(() => {
      message = t(
        "连接中断，保留当前复盘。",
        "Connection lost; keeping this review.",
      );
    });
}, 10000);
window.addEventListener("pagehide", () => {
  stop();
  disposeVisual?.();
});
