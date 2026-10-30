// Fold C prototype: the drop field. A WebGL2 fragment shader shades up to 24
// bodies on one canvas (drops of 3 shares or more, deferred bodies resting at the
// bottom, and bodies on their way to or from the bead string); drops in the same
// group are joined with a smooth union whose blend radius the caller animates
// (only explicit merges ever get one), every other drop is composited on its own,
// so unrelated drops never fuse. A Canvas2D fallback draws the same drops as shaded
// circles and bridges. The layout solver below places drops once per state change.
export const MAX_DROPS = 24;
const ACCENT = [0.81, 0.29, 0.17];

const VERT = `#version 300 es
in vec2 aPos;
void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }`;

const FRAG = `#version 300 es
precision highp float;
#define MAXD ${MAX_DROPS}
uniform vec2 uSize;
uniform float uDpr;
uniform int uGroups;
uniform vec4 uA[MAXD];   // x, y, r, alpha (css px, y down)
uniform vec4 uB[MAXD];   // rgb, light (selection / hover)
uniform vec4 uC[MAXD];   // ring, dashed, stretch.x, stretch.y
uniform int uGStart[MAXD];
uniform int uGCount[MAXD];
uniform float uGK[MAXD];
uniform vec3 uAccent;
out vec4 frag;

// Circle, optionally stretched along its motion (area preserving).
float sdDrop(vec2 p, vec4 a, vec4 c, out vec2 g) {
  vec2 q = p - a.xy;
  float sp = length(c.zw);
  float f = 1.0;
  if (sp > 1e-3) {
    vec2 dir = c.zw / sp; float s = 1.0 + sp;
    float al = dot(q, dir); vec2 perp = q - dir * al;
    q = dir * (al / s) + perp * sqrt(s);
    float l0 = length(q);
    float along = l0 > 1e-4 ? abs(dot(q / l0, dir)) : 0.0;
    f = mix(1.0 / sqrt(s), s, along);
  }
  float l = length(q);
  g = l > 1e-4 ? q / l : vec2(0.0, -1.0);
  return (l - a.z) * f;
}

void main() {
  vec2 p = vec2(gl_FragCoord.x, uSize.y * uDpr - gl_FragCoord.y) / uDpr;
  vec4 acc = vec4(0.0);
  vec3 L = normalize(vec3(-0.48, -0.72, 0.95));
  vec2 Lxy = normalize(L.xy);
  vec3 H = normalize(L + vec3(0.0, 0.0, 1.0));
  for (int gi = 0; gi < MAXD; gi++) {
    if (gi >= uGroups) break;
    int st = uGStart[gi]; int n = uGCount[gi]; float k = max(uGK[gi], 1e-3);
    float d = 1e5; vec2 gr = vec2(0.0, -1.0); vec3 col = vec3(0.0);
    float light = 0.0, al = 0.0, rad = 0.0;
    for (int j = 0; j < MAXD; j++) {
      if (j >= n) break;
      int i = st + j; vec2 gj;
      float dj = sdDrop(p, uA[i], uC[i], gj);
      if (j == 0) { d = dj; gr = gj; col = uB[i].rgb; light = uB[i].a; al = uA[i].w; rad = uA[i].z; }
      else {
        float h = clamp(0.5 + 0.5 * (dj - d) / k, 0.0, 1.0);
        d = mix(dj, d, h) - k * h * (1.0 - h);
        gr = mix(gj, gr, h); col = mix(uB[i].rgb, col, h);
        light = mix(uB[i].a, light, h); al = mix(uA[i].w, al, h); rad = mix(uA[i].z, rad, h);
      }
    }
    if (d > 46.0 || al < 0.002) continue;
    float lg = length(gr); gr = lg > 1e-4 ? gr / lg : vec2(0.0, -1.0);
    float outside = smoothstep(-1.0, 1.0, d);
    // Contact shadow on the paper, leaning away from the light.
    float sh = exp(-max(d, 0.0) / 9.0) * (0.45 + 0.55 * max(0.0, dot(gr, -Lxy))) * 0.085 * al * outside;
    acc = vec4(0.0, 0.0, 0.0, sh) + acc * (1.0 - sh);
    // Selection: the drop's own light spills a little onto the paper.
    float halo = light * exp(-max(d, 0.0) / 16.0) * 0.42 * al * outside;
    vec3 haloC = clamp(mix(vec3(dot(col, vec3(0.3, 0.59, 0.11))), col, 1.5) * 1.05, 0.0, 1.0);
    acc = vec4(haloC * halo, halo) + acc * (1.0 - halo);
    float cov = smoothstep(0.75, -0.75, d) * al;
    if (cov > 0.001) {
      float t = max(-d, 0.0);
      float w = clamp(rad * 0.42, 6.0, 26.0);
      float u = clamp(t / w, 0.0, 1.0);
      float one = 1.0 - u;
      float slope = min(one / sqrt(max(1.0 - one * one, 0.015)), 6.0);
      vec3 N = normalize(vec3(gr * slope, 1.0));
      float diff = dot(N, L);
      float fres = pow(1.0 - N.z, 1.4);
      vec3 c = col;
      // Thickness: the rim reads deeper and a touch more saturated.
      c = mix(c, c * c * 0.9, 0.5 * fres);
      c *= 0.97 + 0.06 * diff;
      // The body is thick in the middle, light passes through it softly.
      c = mix(c, vec3(1.0), 0.09 * smoothstep(0.0, 1.0, u));
      // Transmitted light gathers on the inner edge away from the light.
      float far = max(0.0, dot(gr, -Lxy));
      float caus = exp(-t / 5.5) * far * smoothstep(0.0, 2.5, t);
      c = mix(c, vec3(1.0), (0.42 + 0.25 * light) * caus);
      // Selected: lit from inside, not outlined. The core glows brighter and
      // a little more saturated, the way light seen through gel does.
      float inner = smoothstep(0.0, 1.0, u);
      float luma = dot(c, vec3(0.3, 0.59, 0.11));
      vec3 lit = clamp(mix(vec3(luma), c, 1.28) * 1.11 + 0.035, 0.0, 1.0);
      c = mix(c, lit, light * (0.3 + 0.7 * inner));
      float nh = max(dot(N, H), 0.0);
      c += pow(nh, 90.0) * 0.42 + pow(nh, 16.0) * 0.035;
      float a = cov * 0.96;
      acc = vec4(c * a, a) + acc * (1.0 - a);
    }
    // Registered-ask rings sit just outside each member drop.
    for (int j = 0; j < MAXD; j++) {
      if (j >= n) break;
      int i = st + j;
      float ring = uC[i].x * uA[i].w;
      if (ring < 0.002) continue;
      vec2 q = p - uA[i].xy; float R = uA[i].z + 6.0;
      float dr = abs(length(q) - R) - 0.8;
      float ra = smoothstep(0.75, -0.75, dr) * ring;
      if (uC[i].y > 0.5) {
        float seg = max(8.0, floor(6.2831853 * R / 7.0));
        float ph = fract((atan(q.y, q.x) / 6.2831853) * seg);
        ra *= smoothstep(0.02, 0.1, ph) * smoothstep(0.62, 0.54, ph);
      }
      acc = vec4(uAccent * ra, ra) + acc * (1.0 - ra);
    }
  }
  frag = acc;
}`;

// ---------- renderer ----------
export function createRenderer(canvas) {
  let gl = null;
  try { gl = canvas.getContext('webgl2', { premultipliedAlpha: true, antialias: false, alpha: true, preserveDrawingBuffer: true }); } catch { gl = null; }
  const size = { w: 1, h: 1, dpr: 1 };
  let lastMs = 0;
  if (gl) {
    const compile = (type, src) => { const sh = gl.createShader(type); gl.shaderSource(sh, src); gl.compileShader(sh); if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh)); return sh; };
    let prog;
    try {
      prog = gl.createProgram();
      gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT)); gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
      gl.linkProgram(prog); if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    } catch (error) { console.warn('C field: WebGL2 shader failed, using Canvas2D', error); gl = null; }
    if (gl) {
      const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
      const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
      const loc = gl.getAttribLocation(prog, 'aPos'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
      const U = name => gl.getUniformLocation(prog, name);
      const u = { size: U('uSize'), dpr: U('uDpr'), groups: U('uGroups'), a: U('uA'), b: U('uB'), c: U('uC'), gs: U('uGStart'), gc: U('uGCount'), gk: U('uGK'), accent: U('uAccent') };
      const A = new Float32Array(MAX_DROPS * 4), B = new Float32Array(MAX_DROPS * 4), C = new Float32Array(MAX_DROPS * 4);
      const GS = new Int32Array(MAX_DROPS), GC = new Int32Array(MAX_DROPS), GK = new Float32Array(MAX_DROPS);
      return {
        kind: 'webgl2',
        resize(w, h, dpr) { Object.assign(size, { w, h, dpr }); canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); },
        render(drops, groupK = {}) {
          const t0 = performance.now();
          const groups = groupDrops(drops, groupK);
          let i = 0; A.fill(0); B.fill(0); C.fill(0);
          groups.forEach((g, gi) => {
            GS[gi] = i; GC[gi] = g.members.length; GK[gi] = g.k;
            for (const d of g.members) {
              A.set([d.x, d.y, Math.max(0, d.r), d.alpha ?? 1], i * 4);
              B.set([d.color[0], d.color[1], d.color[2], d.light || 0], i * 4);
              C.set([d.ring || 0, d.dashed ? 1 : 0, d.sx || 0, d.sy || 0], i * 4);
              i++;
            }
          });
          gl.viewport(0, 0, canvas.width, canvas.height);
          gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
          gl.useProgram(prog); gl.bindVertexArray(vao);
          gl.uniform2f(u.size, size.w, size.h); gl.uniform1f(u.dpr, size.dpr);
          gl.uniform1i(u.groups, groups.length);
          gl.uniform4fv(u.a, A); gl.uniform4fv(u.b, B); gl.uniform4fv(u.c, C);
          gl.uniform1iv(u.gs, GS); gl.uniform1iv(u.gc, GC); gl.uniform1fv(u.gk, GK);
          gl.uniform3fv(u.accent, ACCENT);
          gl.drawArrays(gl.TRIANGLES, 0, 3);
          lastMs = performance.now() - t0;
        },
        // Forces the GPU to finish; only for measuring.
        finish() { const px = new Uint8Array(4); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); },
        get lastMs() { return lastMs; },
        dispose() { gl.getExtension('WEBGL_lose_context')?.loseContext(); },
      };
    }
  }
  // ---------- Canvas2D fallback: same drops, simpler light ----------
  const ctx = canvas.getContext('2d');
  const rgb = (c, a = 1, lift = 0) => `rgba(${c.map(v => Math.round(255 * Math.min(1, v + (1 - v) * lift))).join(',')},${a})`;
  return {
    kind: '2d',
    resize(w, h, dpr) { Object.assign(size, { w, h, dpr }); canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); },
    render(drops, groupK = {}) {
      const t0 = performance.now();
      ctx.setTransform(size.dpr, 0, 0, size.dpr, 0, 0); ctx.clearRect(0, 0, size.w, size.h);
      for (const g of groupDrops(drops, groupK)) {
        const ms = g.members.filter(d => d.r > .3 && (d.alpha ?? 1) > .01);
        // bridge between merging members
        if (ms.length > 1 && g.k > 1) for (let i = 1; i < ms.length; i++) {
          const a = ms[0], b = ms[i], w = Math.min(a.r, b.r) * Math.min(1, g.k / Math.max(1, Math.min(a.r, b.r))) * 1.1;
          const gap = Math.hypot(a.x - b.x, a.y - b.y) - a.r - b.r;
          if (gap < g.k) { ctx.strokeStyle = rgb(a.color, a.alpha ?? 1); ctx.lineWidth = w * (1 - Math.max(0, gap) / g.k); ctx.lineCap = 'round'; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
        }
        for (const d of ms) {
          const a = d.alpha ?? 1;
          ctx.save(); ctx.shadowColor = 'rgba(20,30,30,.12)'; ctx.shadowBlur = 10; ctx.shadowOffsetY = 3;
          const grad = ctx.createRadialGradient(d.x - d.r * .3, d.y - d.r * .35, d.r * .1, d.x, d.y, d.r);
          grad.addColorStop(0, rgb(d.color, a, .25 + (d.light || 0) * .3)); grad.addColorStop(.75, rgb(d.color, a, (d.light || 0) * .2)); grad.addColorStop(1, rgb(d.color.map(v => v * v * .95), a));
          ctx.fillStyle = grad; ctx.beginPath(); ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2); ctx.fill(); ctx.restore();
          if (d.ring > .01) {
            ctx.strokeStyle = rgb(ACCENT, d.ring * a); ctx.lineWidth = 1.6; ctx.setLineDash(d.dashed ? [4, 3] : []);
            ctx.beginPath(); ctx.arc(d.x, d.y, d.r + 6, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
          }
        }
      }
      lastMs = performance.now() - t0;
    },
    finish() {},
    get lastMs() { return lastMs; },
    dispose() {},
  };
}
// Larger bodies are drawn first so a small drop passing over stays visible.
function groupDrops(drops, groupK) {
  const map = new Map();
  for (const d of drops.slice(0, MAX_DROPS)) {
    const key = d.group || d.id;
    if (!map.has(key)) map.set(key, { key, members: [], k: groupK[key] || 0, size: 0 });
    const g = map.get(key); g.members.push(d); g.size = Math.max(g.size, d.r);
  }
  return [...map.values()].sort((a, b) => b.size - a.size);
}

// ---------- layout ----------
// nodes: { id, r, share, label: { w, h, inside }, prev?: {x,y}, seed?: {x,y} }
// Each node's footprint is its circle plus, for small drops, a label box
// beside it. Shares pull drops toward the visual centre (largest nearest),
// previous positions hold every drop near where it was, and footprints are
// pushed apart with a gap. Solved once per transition; returns positions and
// label placement.
export function solveLayout(nodes, bounds, opt = {}) {
  const { w, h } = bounds, gap = opt.gap ?? 16, margin = opt.margin ?? 12, labelGap = opt.labelGap ?? 12;
  const cx = w / 2, cy = h * (opt.centerY ?? .47);
  const maxR = Math.max(1, ...nodes.map(n => n.r));
  const hashAngle = id => ([...String(id)].reduce((n, c) => (n * 33 + c.charCodeAt(0)) >>> 0, 5381) % 360) * Math.PI / 180;
  const ps = nodes.map((n, i) => {
    let p = n.prev || n.seed;
    if (!p) { const a = hashAngle(n.id), d = Math.min(w, h) * (.18 + .05 * i); p = { x: cx + Math.cos(a) * d, y: cy + Math.sin(a) * d * .8 }; }
    return { n, x: p.x, y: p.y, side: n.side || (p.x >= cx ? 'right' : 'left'), mass: n.r * n.r };
  });
  const labelRect = (p, side = p.side) => {
    const L = p.n.label; if (!L || L.inside) return null;
    if (side === 'right') return { x0: p.x + p.n.r + labelGap, y0: p.y - L.h / 2, x1: p.x + p.n.r + labelGap + L.w, y1: p.y + L.h / 2 };
    if (side === 'left') return { x0: p.x - p.n.r - labelGap - L.w, y0: p.y - L.h / 2, x1: p.x - p.n.r - labelGap, y1: p.y + L.h / 2 };
    if (side === 'bottom') return { x0: p.x - L.w / 2, y0: p.y + p.n.r + labelGap * .7, x1: p.x + L.w / 2, y1: p.y + p.n.r + labelGap * .7 + L.h };
    return { x0: p.x - L.w / 2, y0: p.y - p.n.r - labelGap * .7 - L.h, x1: p.x + L.w / 2, y1: p.y - p.n.r - labelGap * .7 };
  };
  const bbox = p => { const r = labelRect(p); const b = { x0: p.x - p.n.r, y0: p.y - p.n.r, x1: p.x + p.n.r, y1: p.y + p.n.r }; if (r) { b.x0 = Math.min(b.x0, r.x0); b.y0 = Math.min(b.y0, r.y0); b.x1 = Math.max(b.x1, r.x1); b.y1 = Math.max(b.y1, r.y1); } return b; };
  // Minimum translation pushing shape B away from shape A, or null.
  const circleCircle = (a, ar, b, br, g) => { const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || .01, o = ar + br + g - d; return o > 0 ? { x: dx / d * o, y: dy / d * o, o } : null; };
  const circleRect = (c, r, R, g, sign = 1) => {
    const qx = Math.max(R.x0, Math.min(c.x, R.x1)), qy = Math.max(R.y0, Math.min(c.y, R.y1));
    let dx = c.x - qx, dy = c.y - qy, d = Math.hypot(dx, dy);
    if (d < .01) { const left = c.x - R.x0, right = R.x1 - c.x, up = c.y - R.y0, down = R.y1 - c.y, m = Math.min(left, right, up, down); const o = m + r + g; const v = m === left ? { x: -o, y: 0 } : m === right ? { x: o, y: 0 } : m === up ? { x: 0, y: -o } : { x: 0, y: o }; return { x: v.x * sign, y: v.y * sign, o }; }
    const o = r + g - d; return o > 0 ? { x: dx / d * o * sign, y: dy / d * o * sign, o } : null;
  };
  const rectRect = (A, B, g) => {
    const ox = Math.min(A.x1, B.x1) - Math.max(A.x0, B.x0) + g, oy = Math.min(A.y1, B.y1) - Math.max(A.y0, B.y0) + g;
    if (ox <= 0 || oy <= 0) return null;
    const bx = (B.x0 + B.x1) / 2 - (A.x0 + A.x1) / 2, by = (B.y0 + B.y1) / 2 - (A.y0 + A.y1) / 2;
    return ox < oy ? { x: Math.sign(bx || 1) * ox, y: 0, o: ox } : { x: 0, y: Math.sign(by || 1) * oy, o: oy };
  };
  const push = (a, b) => {
    const ra = labelRect(a), rb = labelRect(b); let best = null;
    const take = v => { if (v && (!best || v.o > best.o)) best = v; };
    take(circleCircle(a, a.n.r, b, b.n.r, gap));
    if (ra) take(circleRect(b, b.n.r, ra, gap * .6));
    if (rb) take(circleRect(a, a.n.r, rb, gap * .6, -1));
    if (ra && rb) take(rectRect(ra, rb, gap * .5));
    return best;
  };
  const iterations = opt.iterations ?? 260;
  for (let it = 0; it < iterations; it++) {
    const cool = 1 - it / iterations;
    for (const p of ps) {
      // share gravity toward the centre, stronger for larger drops
      const pull = .006 + .03 * (p.n.r / maxR);
      p.x += (cx - p.x) * pull * cool; p.y += (cy - p.y) * pull * cool * 1.15;
      if (p.n.prev) { p.x += (p.n.prev.x - p.x) * .05; p.y += (p.n.prev.y - p.y) * .05; }
      if (!p.n.sideFixed && it % 20 === 0 && it < iterations * .6) p.side = p.x >= cx ? 'right' : 'left';
    }
    for (let pass = 0; pass < 2; pass++) {
      for (let i = 0; i < ps.length; i++) for (let j = i + 1; j < ps.length; j++) {
        const a = ps[i], b = ps[j], v = push(a, b); if (!v) continue;
        const wa = b.mass / (a.mass + b.mass), wb = a.mass / (a.mass + b.mass);
        a.x -= v.x * wa * .5; a.y -= v.y * wa * .5; b.x += v.x * wb * .5; b.y += v.y * wb * .5;
      }
      for (const p of ps) {
        const b = bbox(p);
        if (b.x0 < margin) p.x += margin - b.x0; if (b.x1 > w - margin) p.x -= b.x1 - (w - margin);
        if (b.y0 < margin) p.y += margin - b.y0; if (b.y1 > h - margin) p.y -= b.y1 - (h - margin);
      }
    }
  }
  // Final label pass: choose the side with the least overlap.
  const overlapArea = (R, self) => {
    let o = 0;
    if (R.x0 < margin * .5 || R.x1 > w - margin * .5 || R.y0 < 2 || R.y1 > h - 2) o += 1e6;
    for (const q of ps) {
      if (q === self) continue;
      const qx = Math.max(R.x0, Math.min(q.x, R.x1)), qy = Math.max(R.y0, Math.min(q.y, R.y1));
      const d = Math.hypot(q.x - qx, q.y - qy); if (d < q.n.r + 4) o += (q.n.r + 4 - d) * 40;
      const r2 = q.placed; if (r2) { const ox = Math.min(R.x1, r2.x1) - Math.max(R.x0, r2.x0) + 4, oy = Math.min(R.y1, r2.y1) - Math.max(R.y0, r2.y0) + 4; if (ox > 0 && oy > 0) o += ox * oy; }
    }
    return o;
  };
  const order = [...ps].sort((a, b) => b.n.r - a.n.r);
  for (const p of order) {
    if (!p.n.label || p.n.label.inside) continue;
    let best = null;
    for (const side of [p.side, p.side === 'right' ? 'left' : 'right', 'bottom', 'top']) {
      const R = labelRect(p, side), o = overlapArea(R, p);
      if (!best || o < best.o - .5) best = { side, R, o };
    }
    p.side = best.side; p.placed = best.R;
  }
  const out = new Map();
  let overflow = 0;
  for (const p of ps) { const b = bbox(p); overflow += Math.max(0, margin - b.x0) + Math.max(0, b.x1 - w + margin) + Math.max(0, margin - b.y0) + Math.max(0, b.y1 - h + margin); }
  for (let i = 0; i < ps.length; i++) for (let j = i + 1; j < ps.length; j++) { const v = push(ps[i], ps[j]); if (v) overflow += v.o; }
  for (const p of ps) out.set(p.n.id, { x: p.x, y: p.y, side: p.side, rect: labelRect(p) });
  return { positions: out, overflow };
}
