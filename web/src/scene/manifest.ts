// The sub-detector meshes shipped in web/public/models (copied from the repo's
// test/*.gltf, themselves produced by the GDML -> VTK -> GLTF converter).
//
// The viewer uses a soft matte "clay" look: each sub-detector gets a distinct
// soft colour, lit by even image-based lighting and multiplied by baked Cycles
// ambient occlusion (when a bake is present). `clay` is that base colour.

export interface SubDetector {
  /** Stable id; matches the GLTF filename stem and the visibility key. */
  name: string
  /** File under public/models/. */
  file: string
  /** Human-readable label for the HUD. */
  label: string
  /** Logical grouping for the HUD list. */
  group: 'Calorimeter' | 'Magnet' | 'Forward'
  /** Soft matte base colour (hex). */
  clay: string
}

export const MANIFEST: SubDetector[] = [
  { name: 'ECalBarrel', file: 'ECalBarrel.gltf', label: 'ECAL Barrel', group: 'Calorimeter', clay: '#4fb59a' },
  { name: 'ECalEndcap', file: 'ECalEndcap.gltf', label: 'ECAL Endcap', group: 'Calorimeter', clay: '#5cc0a6' },
  { name: 'HCalBarrel', file: 'HCalBarrel.gltf', label: 'HCAL Barrel', group: 'Calorimeter', clay: '#d59a52' },
  { name: 'HCalEndcap', file: 'HCalEndcap.gltf', label: 'HCAL Endcap', group: 'Calorimeter', clay: '#e0a85f' },
  { name: 'Solenoid', file: 'Solenoid.gltf', label: 'Solenoid', group: 'Magnet', clay: '#8aa0c0' },
  { name: 'NozzleBCH_left', file: 'NozzleBCH_left.gltf', label: 'Nozzle BCH (−z)', group: 'Forward', clay: '#c87a4a' },
  { name: 'NozzleBCH_right', file: 'NozzleBCH_right.gltf', label: 'Nozzle BCH (+z)', group: 'Forward', clay: '#c87a4a' },
  { name: 'NozzleWCludding_left', file: 'NozzleWCludding_left.gltf', label: 'Nozzle W-clad (−z)', group: 'Forward', clay: '#aab2bd' },
  { name: 'NozzleWCludding_right', file: 'NozzleWCludding_right.gltf', label: 'Nozzle W-clad (+z)', group: 'Forward', clay: '#aab2bd' },
]

/** Resolve a model URL respecting the Vite base path (works in dev + on Pages). */
export const modelUrl = (file: string) => `${import.meta.env.BASE_URL}models/${file}`

/** Look up the clay colour for a matched sub-detector name. */
export const clayFor = (name: string | undefined) =>
  MANIFEST.find((m) => m.name === name)?.clay ?? '#9aa3ad'
