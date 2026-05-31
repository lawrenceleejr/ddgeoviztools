import { MANIFEST, type SubDetector } from '../scene/manifest'
import { useViewer } from '../state/store'

const GROUPS: SubDetector['group'][] = ['Calorimeter', 'Magnet', 'Forward']

export function Hud() {
  const visibility = useViewer((s) => s.visibility)
  const toggleVisibility = useViewer((s) => s.toggleVisibility)
  const setAllVisible = useViewer((s) => s.setAllVisible)
  const mode = useViewer((s) => s.mode)
  const toggleMode = useViewer((s) => s.toggleMode)

  return (
    <div className="hud">
      <div className="hud-panel">
        <h1>
          MAIA Detector <span className="hud-sub">3D walkthrough</span>
        </h1>

        <div className="hud-section">
          <div className="hud-row hud-row--between">
            <span className="hud-label">Sub-detectors</span>
            <span className="hud-actions">
              <button onClick={() => setAllVisible(true)}>all</button>
              <button onClick={() => setAllVisible(false)}>none</button>
            </span>
          </div>
          {GROUPS.map((group) => (
            <div className="hud-group" key={group}>
              <div className="hud-group-title">{group}</div>
              {MANIFEST.filter((m) => m.group === group).map((m) => (
                <label className="hud-check" key={m.name}>
                  <input
                    type="checkbox"
                    checked={visibility[m.name] ?? true}
                    onChange={() => toggleVisibility(m.name)}
                  />
                  <span>{m.label}</span>
                </label>
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="hud-help">
        <button className={`mode-chip mode-chip--${mode}`} onClick={toggleMode} title="toggle with F">
          {mode === 'fly' ? '✈ FLY' : '🚶 WALK'}
        </button>
        <span><kbd>WASD</kbd>move</span>
        <span><kbd>Shift</kbd>run</span>
        <span><kbd>Space</kbd>{mode === 'fly' ? 'up' : 'jump'}</span>
        <span><kbd>F</kbd>fly</span>
      </div>
    </div>
  )
}
