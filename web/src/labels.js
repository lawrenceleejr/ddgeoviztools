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
  set(defs, chapterIndex) {
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
      const side = i % 2 ? -1 : 1;
      return { def: d, el, line, dot, dx: side * 90, dy: -46 - (i % 3) * 22, on: false };
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
      if (!show) continue;
      const lx = x + it.dx;
      const ly = y + it.dy;
      it.el.style.transform = `translate(${lx}px, ${ly}px) translate(-50%, -50%)`;
      it.line.setAttribute('x1', x); it.line.setAttribute('y1', y);
      it.line.setAttribute('x2', lx); it.line.setAttribute('y2', ly + 10);
      it.dot.setAttribute('cx', x); it.dot.setAttribute('cy', y);
    }
  }
}
