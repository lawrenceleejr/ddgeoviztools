// Chapters — copy, camera, scene state and callouts in one place.
//
// Units: camera positions/targets in metres; `shift` moves the target off
// centre in screen space (fraction of view width, + = model to the right).
// (scene root is scaled 0.001 from
// the GDML mm). Callout anchors are in mm (model space) so they can be read
// straight off parts.json / the GDML.
//
// `state` is a full description of the scene at the START of the chapter;
// the renderer interpolates between consecutive states. Keys:
//   focus     : palette groups drawn at full opacity (others are ghosted)
//   ghost     : opacity for non-focused groups
//   explode   : { <rule>: amount 0..1 } — see scene.js applyExplode()
// Rules: staves.<group>, endcaps.<group>, layers.<system>, disks.<system>,
//        nozzles, solenoidLift.

const ALL = ['beampipe', 'vertex', 'tracker', 'solenoid', 'ecal', 'hcal', 'yoke', 'nozzle', 'bch'];

export const chapters = [
  {
    id: 'hero',
    side: 'left',
    cls: 'hero',
    eyebrow: 'MAIA · muon collider detector concept',
    headline: 'Taken apart.',
    lede: 'Eleven metres of silicon, tungsten and steel, built around a point where muons collide. Scroll to open it, one system at a time.',
    facts: [['Diameter', '11.8 m'], ['Length', '11.9 m'], ['Geometry', 'DD4hep · MAIA_260530']],
    hint: 'Scroll',
    camera: { pos: [23.0, 9.5, 19.5], target: [0, 0.2, 0], fov: 32, shift: 0.24 },
    state: { focus: ALL, ghost: 1, explode: {} },
    labels: [],
  },
  {
    id: 'vertex',
    side: 'right',
    eyebrow: 'Beam pipe & vertex detector',
    headline: 'Three centimetres from the collision.',
    lede: 'A beryllium pipe one millimetre thick, then five barrel layers and four pairs of disks of 50 µm silicon, close enough to see where each particle was born.',
    facts: [['Beam pipe', 'Ø 48 mm · Be'], ['Barrel layers', 'r 30 · 32 · 51 · 74 · 102 mm'], ['Disks', '4 pairs · |z| 80–284 mm']],
    camera: { pos: [0.9, 0.48, 1.5], target: [0, 0, 0.03], fov: 30, shift: -0.26 },
    state: { focus: ['beampipe', 'vertex'], ghost: 0.035, explode: { 'layers.Vertex': 1, 'disks.Vertex': 1 } },
    labels: [
      { part: 'Vertex/layer4', at: [0, 102, 0], text: 'r = 102 mm', name: 'Layer 5' },
      { at: [0, 24, 0], text: 'Ø 48 mm', name: 'Beam pipe' },
    ],
  },
  {
    id: 'inner',
    side: 'left',
    eyebrow: 'Inner tracker',
    headline: 'Three shells, fourteen disks.',
    lede: 'Silicon modules on carbon-fibre shells measure the curve of every charged track in the 5 T field. The disks carry that coverage forward toward the beam.',
    facts: [['Barrel layers', 'r 127 · 340 · 554 mm'], ['Disks', '7 pairs · |z| 0.52–2.19 m'], ['Length', '4.6 m']],
    camera: { pos: [5.0, 2.4, 7.4], target: [0, 0, 0.3], fov: 30, shift: 0.2 },
    state: { focus: ['tracker', 'vertex', 'beampipe'], ghost: 0.035, explode: { 'layers.InnerTrackers': 1, 'disks.InnerTrackers': 1 } },
    labels: [
      { part: 'InnerTrackers/layer2', at: [0, 554, 0], text: 'r = 554 mm', name: 'Layer 3' },
      { part: 'InnerTrackers/layer0', at: [0, 127, 0], text: 'r = 127 mm', name: 'Layer 1' },
      { part: 'InnerTrackers/disks_pz', at: [0, 400, 2187], text: '|z| = 2.19 m', name: 'Disk 7' },
    ],
  },
  {
    id: 'outer',
    side: 'right',
    eyebrow: 'Outer tracker',
    headline: 'The last measurement before the magnet.',
    lede: 'Three cylinders of silicon strips, a metre and a half across, and four pairs of disks. Together with the inner tracker they fix each track to a few tens of microns.',
    facts: [['Barrel layers', 'r 819 · 1 153 · 1 486 mm'], ['Barrel length', '2.5 m'], ['Disks', '4 pairs · |z| 1.31–2.19 m']],
    camera: { pos: [9.5, 3.8, 9.0], target: [0, 0, 0], fov: 32, shift: -0.2 },
    state: { focus: ['tracker'], ghost: 0.035, explode: { 'layers.OuterTrackers': 1, 'disks.OuterTrackers': 1 } },
    labels: [
      { part: 'OuterTrackers/layer2', at: [0, 1486, 0], text: 'r = 1 486 mm', name: 'Layer 3' },
      { part: 'OuterTrackers/layer1', at: [0, 1153, 0], text: 'r = 1 153 mm', name: 'Layer 2' },
      { part: 'OuterTrackers/layer0', at: [0, 819, 0], text: 'r = 819 mm', name: 'Layer 1' },
    ],
  },
  {
    id: 'solenoid',
    side: 'left',
    eyebrow: 'Solenoid',
    headline: 'Five tesla.',
    lede: 'A superconducting coil three metres across bends every charged particle inside it. Everything so far sits in its bore; everything after it sits in the return field.',
    facts: [['Field', '5 T'], ['Bore', 'Ø 3.0 m'], ['Conductor', 'r 1.53–1.83 m'], ['Length', '4.6 m']],
    camera: { pos: [-9.0, 3.8, 12.5], target: [0, 0, 0], fov: 34, shift: 0.22 },
    state: { focus: ['solenoid'], ghost: 0.045, explode: {} },
    labels: [
      { at: [0, 1857, 0], text: 'r = 1 857 mm', name: 'Cryostat' },
      { at: [0, 1500, 2307], text: '|z| = 2.31 m', name: 'End' },
    ],
  },
  {
    id: 'ecal',
    side: 'right',
    eyebrow: 'Electromagnetic calorimeter',
    headline: 'Fifty layers of tungsten and silicon.',
    lede: 'Twelve staves close around the solenoid. Each is a sandwich of 2.2 mm tungsten plates and silicon pads that stops electrons and photons and measures their energy.',
    facts: [['Barrel', 'r 1.86–2.12 m · 12 staves'], ['Layers', '50 × 2.2 mm W + Si'], ['Endcaps', '|z| 2.31–2.57 m']],
    camera: { pos: [13.0, 8.5, 15.0], target: [0, 0.4, 0], fov: 34, shift: -0.26 },
    state: { focus: ['ecal'], ghost: 0.045, explode: { 'staves.ecal': 1, 'endcaps.ecal': 1 } },
    labels: [
      { part: 'ECalBarrel/stave03', at: [0, 2125, 0], text: 'r = 2 125 mm', name: 'Stave' },
      { part: 'ECalEndcap/pz', at: [1200, 1200, 2575], text: '|z| = 2.57 m', name: 'Endcap' },
    ],
  },
  {
    id: 'hcal',
    side: 'left',
    eyebrow: 'Hadronic calorimeter',
    headline: 'Seventy-five layers of steel.',
    lede: 'Two metres of steel absorber interleaved with gas detectors. Hadrons that pass the ECal shower here, and their energy is summed layer by layer.',
    facts: [['Barrel', 'r 2.13–4.11 m · 12 staves'], ['Layers', '75 × 19 mm steel + RPC'], ['Endcaps', '|z| 2.58–4.54 m']],
    camera: { pos: [-17.0, 10.0, 18.5], target: [0, 0.6, 0], fov: 34, shift: 0.24 },
    state: { focus: ['hcal'], ghost: 0.045, explode: { 'staves.hcal': 1, 'endcaps.hcal': 1 } },
    labels: [
      { part: 'HCalBarrel/stave03', at: [0, 4114, 0], text: 'r = 4 114 mm', name: 'Stave' },
      { part: 'HCalEndcap/nz', at: [-2000, 2000, -4537], text: '|z| = 4.54 m', name: 'Endcap' },
    ],
  },
  {
    id: 'yoke',
    side: 'right',
    eyebrow: 'Return yoke',
    headline: 'The iron that closes the field.',
    lede: 'Four layers of 436 mm steel return the solenoid flux and shield the outside world. Detectors between the plates catch the muons, the one particle that gets this far.',
    facts: [['Barrel', 'r 4.15–5.90 m · 12 sides'], ['Layers', '4 × 436 mm steel'], ['Endcaps', '|z| 4.83–5.96 m']],
    camera: { pos: [24.0, 13.5, 28.5], target: [0, 0.8, 0], fov: 34, shift: -0.24 },
    state: { focus: ['yoke'], ghost: 0.045, explode: { 'staves.yoke': 1, 'endcaps.yoke': 1 } },
    labels: [
      { part: 'YokeBarrel/stave03', at: [0, 5896, 0], text: 'r = 5 896 mm', name: 'Stave' },
      { part: 'YokeEndcap/pz', at: [3000, 3000, 5962], text: '|z| = 5.96 m', name: 'Endcap' },
    ],
  },
  {
    id: 'nozzles',
    side: 'left',
    eyebrow: 'Forward shielding',
    headline: 'Two tungsten cones against the noise.',
    lede: 'Muons decay in flight, and their electrons flood the forward region. Tungsten nozzles clad in borated polyethylene absorb that background before it reaches the silicon.',
    facts: [['Material', 'W alloy · BCH2 cladding'], ['Extent', '|z| 0.06–5.95 m'], ['Outer radius', '0.55 m at |z| = 5.95 m']],
    camera: { pos: [16.0, 5.0, -5.6], target: [0, 0, -5.6], fov: 30, shift: 0.12 },
    state: { focus: ['nozzle', 'bch', 'beampipe'], ghost: 0.045, explode: { nozzles: 1 } },
    labels: [
      { part: 'NozzleWCludding_left/body', at: [0, 550, -5950], text: 'r = 550 mm', name: 'Cladding' },
      { part: 'NozzleW_left/body', at: [0, -430, -5950], text: 'r = 430 mm', name: 'Tungsten' },
    ],
  },
  {
    id: 'exploded',
    side: 'left',
    eyebrow: 'MAIA',
    headline: 'Every system, in its place.',
    lede: '',
    facts: [['Systems', '9'], ['Parts', '90'], ['Triangles', '1.9 M']],
    camera: { pos: [24.0, 14.0, 30.0], target: [0, 0.5, 0], fov: 36, shift: 0.22 },
    state: {
      focus: ALL,
      ghost: 1,
      explode: { 'staves.ecal': 1, 'staves.hcal': 1, 'staves.yoke': 1, 'endcaps.ecal': 1, 'endcaps.hcal': 1, 'endcaps.yoke': 1, nozzles: 1 },
    },
    labels: [
      { part: 'YokeBarrel/stave03', at: [0, 5896, 0], text: '', name: 'Yoke' },
      { part: 'HCalBarrel/stave09', at: [0, -4114, 0], text: '', name: 'HCal' },
      { part: 'ECalBarrel/stave00', at: [2125, 0, 0], text: '', name: 'ECal' },
      { at: [0, 1857, -1500], text: '', name: 'Solenoid' },
      { at: [0, 1486, 0], text: '', name: 'Tracker' },
      { part: 'NozzleW_left/body', at: [0, 400, -5950], text: '', name: 'Nozzle' },
    ],
  },
  {
    id: 'colophon',
    side: 'center',
    eyebrow: '',
    headline: '',
    lede: '',
    facts: [],
    colophon: true,
    camera: { pos: [23.0, 9.5, 19.5], target: [0, -1.5, 0], fov: 32, shift: 0 },
    state: { focus: ALL, ghost: 1, explode: {} },
    labels: [],
  },
];

/** Every explode rule key used anywhere, so state vectors are dense. */
export const RULES = [...new Set(chapters.flatMap((c) => Object.keys(c.state.explode)))];
export const GROUPS = ALL;
