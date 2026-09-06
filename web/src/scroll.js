// Scroll engine. Reads window.scrollY against chapter section positions and
// yields a smoothed global progress `t` in [0, chapters) where the integer
// part is the chapter index and the fraction is progress within it.
//
// Smoothing is a critically damped spring: no overshoot, but inertia so a
// trackpad flick reads as camera weight rather than a cut.

export class ScrollEngine {
  constructor(sections, { reduced = false } = {}) {
    this.sections = sections;
    this.reduced = reduced;
    this.target = 0;
    this.value = 0;
    this.velocity = 0;
    this.omega = reduced ? 40 : 9; // rad/s; higher = snappier
    this.measure();
    addEventListener('scroll', () => this.read(), { passive: true });
    addEventListener('resize', () => { this.measure(); this.read(); });
    this.read();
    this.value = this.target;
  }

  measure() {
    this.bounds = this.sections.map((el) => {
      const r = el.getBoundingClientRect();
      const top = r.top + scrollY;
      return { top, height: r.height };
    });
  }

  /** Raw scroll → target progress. Chapter i is "in view" while its section
   *  centre travels from viewport bottom to viewport top; progress within a
   *  chapter is measured on the section's own travel through the centre line. */
  read() {
    const mid = scrollY + innerHeight * 0.5;
    const n = this.bounds.length;
    let t = 0;
    for (let i = 0; i < n; i++) {
      const b = this.bounds[i];
      const start = b.top;            // section top hits viewport centre
      const end = b.top + b.height;   // section bottom hits viewport centre
      if (mid < start) break;
      if (mid >= end) { t = i + 1; continue; }
      t = i + (mid - start) / (end - start);
      break;
    }
    this.target = Math.min(Math.max(t, 0), n - 1e-6);
  }

  /** Advance the spring by dt seconds. Returns smoothed progress. */
  step(dt) {
    const w = this.omega;
    const x = this.value - this.target;
    // critically damped: x'' + 2 w x' + w^2 x = 0
    const a = -2 * w * this.velocity - w * w * x;
    this.velocity += a * dt;
    this.value += this.velocity * dt;
    if (Math.abs(this.value - this.target) < 1e-4 && Math.abs(this.velocity) < 1e-4) {
      this.value = this.target;
      this.velocity = 0;
    }
    return this.value;
  }
}

/** Smoothstep-style easing helpers shared by the scene. */
export const ease = {
  inOut: (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x)),
  out: (x) => 1 - Math.pow(1 - Math.min(Math.max(x, 0), 1), 3),
  clamp01: (x) => Math.min(Math.max(x, 0), 1),
  lerp: (a, b, t) => a + (b - a) * t,
};
