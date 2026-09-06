// Callouts — DOM labels projected from model-space anchors each frame, with
// SVG hairline leaders. Tufte: direct labels, no boxes, no arrows.
import { Vector3 } from 'three';

export class Labels {
  constructor(container, svg, camera, root, partsById = new Map()) {
    this.container = container;
    this.svg = svg;
    this.camera = camera;
    this.root = root;
    this.partsById = partsById; // id → part (with .pivot) so anchors ride along
    this.items = [];
    this.v = new Vector3();
  }

  /** Replace the set of labels: [{ at:[mm], text, name }]. */
  /** `bias` = +1 puts labels to the right of their anchor, -1 to the left
   *  (away from the chapter's copy). */
  set(defs, chapterIndex, bias = 1) {
    if (this.chapterIndex === chapterIndex) return;
    this.chapterIndex = chapterIndex;
    for (const it of this.items) { it.el.remove(); it.line.remove(); it.dot.remove(); }
    this.items = defs.map((d, i) => {
      const el = document.createElement('div');
      el.className = 'label';
      el.innerHTML = `${d.name ? `<span class="label-name">${d.name}</span>` : ''}${d.text ? `${d.name ? ' &nbsp;' : ''}<span>${d.text}</span>` : ''}`;
      this.container.appendChild(el);
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('r', '2');
      this.svg.append(line, dot);
      // Alternate label offsets so neighbours do not collide.
      // Fan labels out on the side away from the copy, staggered vertically.
      const dx = bias * (95 + (i % 2) * 40);
      const dy = -40 - i * 26;
      return { def: d, el, line, dot, dx, dy, on: false, x: 0, y: 0, w: 0, h: 0 };
    });
    requestAnimationFrame(() => this.items.forEach((it) => it.el.classList.add('on')));
  }

  update(visible) {
    const w = innerWidth;
    const h = innerHeight;
    for (const it of this.items) {
      // Anchor: model-space point, optionally offset by a part's pivot so the
      // label follows the part as it explodes.
      this.v.set(...it.def.at);
      const part = it.def.part ? this.partsById.get(it.def.part) : null;
      if (part) this.v.add(part.pivot.position);
      this.v.applyMatrix4(this.root.matrixWorld).project(this.camera);
      const behind = this.v.z > 1;
      const x = (this.v.x * 0.5 + 0.5) * w;
      const y = (-this.v.y * 0.5 + 0.5) * h;
      const show = visible && !behind && x > 0 && x < w && y > 0 && y < h;
      it.el.classList.toggle('on', show);
      it.line.style.opacity = show ? 1 : 0;
      it.dot.style.opacity = show ? 1 : 0;
      it.show = show;
      if (!show) continue;
      it.ax = x;
      it.ay = y;
      it.x = x + it.dx;
      it.y = y + it.dy;
      it.w = it.el.offsetWidth || 120;
      it.h = it.el.offsetHeight || 18;
    }
    // Greedy de-overlap: push later labels down until they clear earlier ones.
    const shown = this.items.filter((it) => it.show);
    for (let a = 0; a < shown.length; a++) {
      for (let b = 0; b < a; b++) {
        const A = shown[a];
        const B = shown[b];
        const dx = Math.abs(A.x - B.x) - (A.w + B.w) / 2 - 12;
        const dy = Math.abs(A.y - B.y) - (A.h + B.h) / 2 - 6;
        if (dx < 0 && dy < 0) A.y = B.y + (B.h + A.h) / 2 + 8;
      }
    }
    for (const it of shown) {
      it.el.style.transform = `translate(${it.x}px, ${it.y}px) translate(-50%, -50%)`;
      it.line.setAttribute('x1', it.ax); it.line.setAttribute('y1', it.ay);
      it.line.setAttribute('x2', it.x); it.line.setAttribute('y2', it.y + it.h / 2 - 2);
      it.dot.setAttribute('cx', it.ax); it.dot.setAttribute('cy', it.ay);
    }
  }
}
