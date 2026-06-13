// Canvas2D "Jarvis" ring HUD. Three concentric rotating arc rings, an outer
// tick scale, and a center reactive core. State-driven palette/speed; the core
// + outer ring react to audio level. Glow via shadowBlur + radial gradients.

import type { HudState } from "../voice/machine.ts";

const CYAN = "#22d3ee";
const GOLD = "#ffce54";
const MAGENTA = "#f24bd6";

// Music mode (M3): hotter palette + faster spin; the core reacts to bass and
// the rings to treble (see drawCore/drawRing) instead of the single mic/TTS level.
const MUSIC_PAL: Palette = { primary: MAGENTA, accent: GOLD, speedMul: 2.2, coreScale: 1.1 };

interface RingSpec {
  radius: number; // fraction of base radius
  speed: number; // radians / sec
  arc: number; // arc length (radians)
  gaps: number; // number of arc segments around the ring
  width: number;
}

const RINGS: RingSpec[] = [
  { radius: 1.0, speed: 0.35, arc: 1.1, gaps: 3, width: 3 },
  { radius: 0.78, speed: -0.55, arc: 0.7, gaps: 4, width: 2 },
  { radius: 0.58, speed: 0.9, arc: 0.5, gaps: 5, width: 2 },
];

interface Palette {
  primary: string;
  accent: string;
  speedMul: number;
  coreScale: number; // baseline core radius multiplier
}

function paletteFor(state: HudState): Palette {
  switch (state) {
  case "listening":
    return { primary: CYAN, accent: CYAN, speedMul: 1.6, coreScale: 1.0 };
  case "transcribing":
    return { primary: CYAN, accent: GOLD, speedMul: 2.0, coreScale: 0.8 };
  case "thinking":
    return { primary: CYAN, accent: GOLD, speedMul: 2.8, coreScale: 0.6 };
  case "speaking":
    return { primary: GOLD, accent: CYAN, speedMul: 1.4, coreScale: 1.05 };
  case "idle":
  default:
    return { primary: CYAN, accent: GOLD, speedMul: 1.0, coreScale: 0.9 };
  }
}

export class RingHud {
  private ctx: CanvasRenderingContext2D;
  private raf = 0;
  private t = 0;
  private last = 0;
  private dpr = 1;

  // Smoothed audio level so the core animates without jitter.
  private level = 0;
  // Smoothed bass/mid/treble for music mode.
  private bass = 0;
  private mid = 0;
  private treble = 0;
  private musicActive = false;

  getState: () => HudState = () => "idle";
  getLevel: () => number = () => 0;
  getBands: () => { bass: number; mid: number; treble: number } = () => ({ bass: 0, mid: 0, treble: 0 });
  getMusicActive: () => boolean = () => false;

  constructor(private canvas: HTMLCanvasElement) {
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      throw new Error("canvas 2d context unavailable");
    }
    this.ctx = ctx;
    this.resize();
    window.addEventListener("resize", () => this.resize());
  }

  private resize(): void {
    this.dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.floor(window.innerWidth * this.dpr);
    this.canvas.height = Math.floor(window.innerHeight * this.dpr);
    this.canvas.style.width = `${window.innerWidth}px`;
    this.canvas.style.height = `${window.innerHeight}px`;
  }

  start(): void {
    this.last = performance.now();
    const loop = (now: number): void => {
      const dt = Math.min(0.05, (now - this.last) / 1000);
      this.last = now;
      this.t += dt;
      this.frame(dt);
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop(): void {
    cancelAnimationFrame(this.raf);
  }

  private frame(dt: number): void {
    const ctx = this.ctx;
    const W = this.canvas.width;
    const H = this.canvas.height;
    ctx.clearRect(0, 0, W, H);

    const state = this.getState();
    this.musicActive = this.getMusicActive();
    const pal = this.musicActive ? MUSIC_PAL : paletteFor(state);

    // Smooth the level toward the target.
    const target = this.getLevel();
    this.level += (target - this.level) * Math.min(1, dt * 12);

    // Smooth the bands (fast attack for snappy beat response).
    const b = this.getBands();
    const k = Math.min(1, dt * 18);
    this.bass += (b.bass - this.bass) * k;
    this.mid += (b.mid - this.mid) * k;
    this.treble += (b.treble - this.treble) * k;

    const cx = W / 2;
    const cy = H / 2;
    const base = Math.min(W, H) * 0.28;

    // Gentle idle breathing on global alpha/scale.
    const breath = state === "idle" ? 0.85 + 0.15 * Math.sin(this.t * 1.4) : 1;

    ctx.save();
    ctx.translate(cx, cy);
    ctx.lineCap = "round";

    this.drawTicks(base * 1.18, pal, breath);
    for (let i = 0; i < RINGS.length; i++) {
      this.drawRing(RINGS[i], base, pal, breath, i);
    }
    this.drawScanSweep(base, pal, state);
    this.drawCore(base * 0.42, pal, breath);

    ctx.restore();
  }

  private drawTicks(radius: number, pal: Palette, breath: number): void {
    const ctx = this.ctx;
    const count = 90;
    ctx.save();
    ctx.rotate(this.t * 0.05 * pal.speedMul);
    ctx.strokeStyle = pal.primary;
    ctx.globalAlpha = 0.35 * breath;
    ctx.shadowColor = pal.primary;
    ctx.shadowBlur = 6 * this.dpr;
    for (let i = 0; i < count; i++) {
      const a = (i / count) * Math.PI * 2;
      const major = i % 9 === 0;
      const len = (major ? 14 : 7) * this.dpr;
      ctx.lineWidth = (major ? 2 : 1) * this.dpr;
      const r0 = radius;
      const r1 = radius + len;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * r0, Math.sin(a) * r0);
      ctx.lineTo(Math.cos(a) * r1, Math.sin(a) * r1);
      ctx.stroke();
    }
    ctx.restore();
  }

  private drawRing(
    spec: RingSpec,
    base: number,
    pal: Palette,
    breath: number,
    idx: number,
  ): void {
    const ctx = this.ctx;
    const radius = base * spec.radius;
    const color = idx === 1 ? pal.accent : pal.primary;
    ctx.save();
    ctx.rotate(this.t * spec.speed * pal.speedMul);
    ctx.strokeStyle = color;
    ctx.lineWidth = spec.width * this.dpr;
    // Music mode: treble lifts ring brightness + glow for a snappier feel.
    const reactive = this.musicActive ? this.treble : this.level;
    ctx.globalAlpha = Math.min(1, (0.55 + 0.3 * reactive) * breath);
    ctx.shadowColor = color;
    ctx.shadowBlur = (14 + (this.musicActive ? this.treble * 16 : 0)) * this.dpr;
    const step = (Math.PI * 2) / spec.gaps;
    for (let g = 0; g < spec.gaps; g++) {
      const start = g * step;
      ctx.beginPath();
      ctx.arc(0, 0, radius, start, start + spec.arc);
      ctx.stroke();
    }
    ctx.restore();
  }

  // A bright "loading" sweep, prominent during thinking/transcribing.
  private drawScanSweep(base: number, pal: Palette, state: HudState): void {
    if (state !== "thinking" && state !== "transcribing") {
      return;
    }
    const ctx = this.ctx;
    const radius = base * 0.9;
    const a = this.t * 3.5;
    ctx.save();
    ctx.rotate(a);
    const grad = ctx.createLinearGradient(0, 0, radius, 0);
    grad.addColorStop(0, "rgba(34,211,238,0)");
    grad.addColorStop(1, pal.accent);
    ctx.strokeStyle = grad;
    ctx.lineWidth = 3 * this.dpr;
    ctx.shadowColor = pal.accent;
    ctx.shadowBlur = 18 * this.dpr;
    ctx.beginPath();
    ctx.arc(0, 0, radius, -0.5, 0.0);
    ctx.stroke();
    ctx.restore();
  }

  // Center reactive core: a radial-gradient glow + a circular waveform whose
  // radius scales with audio level.
  private drawCore(maxR: number, pal: Palette, breath: number): void {
    const ctx = this.ctx;
    // Music mode: bass drives the core pulse, mid/treble drive the waveform wobble.
    const lvl = this.musicActive ? this.bass : this.level;
    const wobLo = this.musicActive ? this.mid : this.level;
    const wobHi = this.musicActive ? this.treble : this.level;
    const coreR = maxR * pal.coreScale * (0.55 + 0.45 * lvl) * breath;

    // Glow disk.
    const grad = ctx.createRadialGradient(0, 0, 0, 0, 0, coreR * 1.6);
    grad.addColorStop(0, this.withAlpha(pal.primary, 0.9));
    grad.addColorStop(0.5, this.withAlpha(pal.primary, 0.25));
    grad.addColorStop(1, this.withAlpha(pal.primary, 0));
    ctx.save();
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(0, 0, coreR * 1.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    // Circular waveform ring modulated by level + a few harmonics.
    ctx.save();
    ctx.strokeStyle = pal.accent;
    ctx.lineWidth = 2 * this.dpr;
    ctx.shadowColor = pal.accent;
    ctx.shadowBlur = 12 * this.dpr;
    ctx.beginPath();
    const segs = 120;
    for (let i = 0; i <= segs; i++) {
      const a = (i / segs) * Math.PI * 2;
      const wob =
        1 +
        wobLo * 0.35 * Math.sin(a * 6 + this.t * 4) +
        wobHi * 0.25 * Math.sin(a * 11 - this.t * 3);
      const r = coreR * wob;
      const x = Math.cos(a) * r;
      const y = Math.sin(a) * r;
      if (i === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.closePath();
    ctx.stroke();
    ctx.restore();
  }

  private withAlpha(hex: string, alpha: number): string {
    const n = parseInt(hex.slice(1), 16);
    const r = (n >> 16) & 255;
    const g = (n >> 8) & 255;
    const b = n & 255;
    return `rgba(${r},${g},${b},${alpha})`;
  }
}
