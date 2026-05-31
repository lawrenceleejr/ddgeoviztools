import { create } from 'zustand'
import { MANIFEST } from '../scene/manifest'

export type MoveMode = 'walk' | 'fly'

interface ViewerState {
  /** Per-subdetector visibility, keyed by manifest name. */
  visibility: Record<string, boolean>
  toggleVisibility: (name: string) => void
  setAllVisible: (visible: boolean) => void

  /** Phi cutaway wedge (degrees). Faces inside [min, max] are hidden. */
  cutawayEnabled: boolean
  phiMin: number
  phiMax: number
  setCutawayEnabled: (v: boolean) => void
  setPhi: (min: number, max: number) => void

  /** Movement mode for the third-person controller. */
  mode: MoveMode
  setMode: (m: MoveMode) => void
  toggleMode: () => void
}

const initialVisibility: Record<string, boolean> = Object.fromEntries(
  MANIFEST.map((m) => [m.name, true] as [string, boolean]),
)

export const useViewer = create<ViewerState>((set) => ({
  visibility: initialVisibility,
  toggleVisibility: (name) =>
    set((s) => ({ visibility: { ...s.visibility, [name]: !s.visibility[name] } })),
  setAllVisible: (visible) =>
    set(() => ({
      visibility: Object.fromEntries(MANIFEST.map((m) => [m.name, visible] as [string, boolean])),
    })),

  cutawayEnabled: true,
  phiMin: 0,
  phiMax: 90,
  setCutawayEnabled: (v) => set(() => ({ cutawayEnabled: v })),
  setPhi: (min, max) => set(() => ({ phiMin: min, phiMax: max })),

  mode: 'walk',
  setMode: (m) => set(() => ({ mode: m })),
  toggleMode: () => set((s) => ({ mode: s.mode === 'walk' ? 'fly' : 'walk' })),
}))
