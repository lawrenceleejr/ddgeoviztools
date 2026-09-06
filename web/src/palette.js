// Palette — mirrors src/gdml_to_blender.py `_DETECTOR_MATERIALS` (linear RGB,
// metallic, roughness) so web, Blender stills and the UE5 app agree.
import { Color, MeshPhysicalMaterial, DoubleSide } from 'three';

export const PALETTE = {
  beampipe: { rgb: [0.78, 0.79, 0.82], metalness: 0.8, roughness: 0.4, label: 'Beam pipe' },
  vertex: { rgb: [0.28, 0.45, 0.72], metalness: 0.7, roughness: 0.45, label: 'Vertex detector' },
  tracker: { rgb: [0.22, 0.38, 0.6], metalness: 0.55, roughness: 0.5, clearcoat: 0.3, label: 'Tracker' },
  solenoid: { rgb: [0.72, 0.42, 0.22], metalness: 0.8, roughness: 0.45, label: 'Solenoid' },
  ecal: { rgb: [0.35, 0.62, 0.52], metalness: 0.1, roughness: 0.35, clearcoat: 0.6, label: 'ECal' },
  hcal: { rgb: [0.52, 0.38, 0.22], metalness: 0.7, roughness: 0.55, label: 'HCal' },
  yoke: { rgb: [0.3, 0.28, 0.26], metalness: 0.75, roughness: 0.6, label: 'Yoke' },
  nozzle: { rgb: [0.42, 0.4, 0.38], metalness: 0.85, roughness: 0.4, label: 'Nozzle' },
  bch: { rgb: [0.92, 0.91, 0.9], metalness: 0.0, roughness: 0.95, label: 'Nozzle cladding' },
  other: { rgb: [0.45, 0.45, 0.48], metalness: 0.0, roughness: 0.85, label: '' },
};

/** Build one MeshPhysicalMaterial per palette entry; parts share by group. */
export function makeMaterials() {
  const mats = {};
  for (const [key, p] of Object.entries(PALETTE)) {
    const m = new MeshPhysicalMaterial({
      color: new Color().setRGB(...p.rgb),
      metalness: p.metalness,
      roughness: p.roughness,
      clearcoat: p.clearcoat ?? 0,
      clearcoatRoughness: 0.25,
      flatShading: true,
      side: DoubleSide,
      transparent: true,
      opacity: 1,
      envMapIntensity: 1.0,
    });
    m.userData.group = key;
    mats[key] = m;
  }
  return mats;
}
