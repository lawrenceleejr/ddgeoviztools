import { MANIFEST, type SubDetector } from '../scene/manifest'
import { useViewer } from '../state/store'

const GROUPS: SubDetector['group'][] = ['Calorimeter', 'Magnet', 'Forward']

export function Hud() {
  const visibility = useViewer((s) => s.visibility)
  const toggleVisibility = useViewer((s) => s.toggleVisibility)
  const setAllVisible = useViewer((s) => s.setAllVisible)

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
        <span><kbd>drag</kbd> orbit</span>
        <span><kbd>scroll</kbd> zoom</span>
        <span className="hud-help-note">third-person controls coming next</span>
      </div>
    </div>
  )
}
