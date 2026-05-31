// The sub-detector meshes shipped in web/public/models (copied from the repo's
// test/*.gltf, themselves produced by the GDML -> VTK -> GLTF converter).
//
// `accent` tweaks how each part reads under image-based lighting; the GLTF files
// already carry baseColor/metallic/roughness from the Blender palette
// (src/gdml_to_blender.py), so we only nudge envMap response and grouping here.

export interface SubDetector {
  /** Stable id; matches the GLTF filename stem and the visibility key. */
  name: string
  /** File under public/models/. */
  file: string
  /** Human-readable label for the HUD. */
  label: string
  /** Logical grouping for the HUD list. */
  group: 'Calorimeter' | 'Magnet' | 'Forward'
  /** Reflectivity multiplier under IBL (1 = as authored). */
  envMapIntensity: number
}

export const MANIFEST: SubDetector[] = [
  { name: 'ECalBarrel', file: 'ECalBarrel.gltf', label: 'ECAL Barrel', group: 'Calorimeter', envMapIntensity: 1.0 },
  { name: 'ECalEndcap', file: 'ECalEndcap.gltf', label: 'ECAL Endcap', group: 'Calorimeter', envMapIntensity: 1.0 },
  { name: 'HCalBarrel', file: 'HCalBarrel.gltf', label: 'HCAL Barrel', group: 'Calorimeter', envMapIntensity: 0.9 },
  { name: 'HCalEndcap', file: 'HCalEndcap.gltf', label: 'HCAL Endcap', group: 'Calorimeter', envMapIntensity: 0.9 },
  { name: 'Solenoid', file: 'Solenoid.gltf', label: 'Solenoid', group: 'Magnet', envMapIntensity: 1.3 },
  { name: 'NozzleBCH_left', file: 'NozzleBCH_left.gltf', label: 'Nozzle BCH (−z)', group: 'Forward', envMapIntensity: 1.1 },
  { name: 'NozzleBCH_right', file: 'NozzleBCH_right.gltf', label: 'Nozzle BCH (+z)', group: 'Forward', envMapIntensity: 1.1 },
  { name: 'NozzleWCludding_left', file: 'NozzleWCludding_left.gltf', label: 'Nozzle W-clad (−z)', group: 'Forward', envMapIntensity: 1.2 },
  { name: 'NozzleWCludding_right', file: 'NozzleWCludding_right.gltf', label: 'Nozzle W-clad (+z)', group: 'Forward', envMapIntensity: 1.2 },
]

/** Resolve a model URL respecting the Vite base path (works in dev + on Pages). */
export const modelUrl = (file: string) => `${import.meta.env.BASE_URL}models/${file}`
