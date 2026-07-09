extends Node3D
## Builds the visual representation of one collision event from the JSON
## produced by ColliderVis/Tools/edm4hep_to_json.py:
##
##   tracks       — emissive tubes swept along the reconstructed track points,
##                  coloured by charge, glow scaled by momentum
##   calo_hits    — energy-coloured emissive cubes (MultiMesh, one draw call)
##   mc_particles — faint straight truth lines from vertex to end vertex
##
## All input coordinates are in mm (EDM4HEP convention) -> scaled to metres.

const MM_TO_M := 0.001

# Preloaded once at parse time and reused across all per-track/hit/line
# materials — avoids a load() lookup per track inside the build loop.
const TRACK_SHADER := preload("res://shaders/track.gdshader")
const CALO_SHADER := preload("res://shaders/calo_hit.gdshader")
const MC_SHADER := preload("res://shaders/mc_line.gdshader")

const POSITIVE_TRACK_COLOR := Color(1.0, 0.4, 0.1)   # red-orange
const NEGATIVE_TRACK_COLOR := Color(0.1, 0.7, 1.0)   # cyan-blue
const NEUTRAL_TRACK_COLOR := Color(1.0, 1.0, 1.0)
const MC_COLOR := Color(0.45, 0.45, 0.95)

const TRACK_RADIUS_M := 0.004
const TUBE_SIDES := 8
const CALO_CUBE_M := 0.06

const CALO_COLD := Color(0.0, 0.1, 0.5)
const CALO_HOT := Color(1.5, 1.2, 0.8)

## Propagation speed of the reveal front (metres of detector per second of
## display time): the whole ~4 m event plays out in about half a second.
const REVEAL_SPEED := 9.0

var _reveal := 1e9          # current front distance (m); huge = fully shown
var _max_extent := 0.0      # furthest arc length / hit distance in the event

const PDG_NAMES := {
	11: "e-", -11: "e+", 13: "mu-", -13: "mu+", 15: "tau-", -15: "tau+",
	22: "gamma", 111: "pi0", 211: "pi+", -211: "pi-", 130: "K0L",
	321: "K+", -321: "K-", 2212: "p", -2212: "pbar", 2112: "n", -2112: "nbar",
	12: "nu_e", -12: "nu_e~", 14: "nu_mu", -14: "nu_mu~",
}

# Parsed metadata exposed to the UI's event-information panel.
var event_number := 0
var run_number := 0
var track_infos: Array = []   # {pdg, charge, p}
var mc_infos: Array = []      # {pdg, p, status}
var n_calo_hits := 0
var calo_energy_sum := 0.0


static func pdg_name(pdg: int) -> String:
	return PDG_NAMES.get(pdg, "pdg %d" % pdg)


func load_event(path: String) -> bool:
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		push_warning("EventDisplay: cannot read '%s'" % path)
		return false
	var data: Variant = JSON.parse_string(text)
	if typeof(data) != TYPE_DICTIONARY:
		push_warning("EventDisplay: '%s' is not a JSON object" % path)
		return false
	event_number = int(data.get("event_number", 0))
	run_number = int(data.get("run_number", 0))
	var n_tracks := _build_tracks(data.get("tracks", []))
	var n_hits := _build_calo_hits(data.get("calo_hits", []))
	var n_mc := _build_mc_particles(data.get("mc_particles", []))
	print("EventDisplay: %s -> %d tracks, %d calo hits, %d MC lines"
		% [path.get_file(), n_tracks, n_hits, n_mc])
	return true


## Propagation animation: every trajectory draws on from the origin along
## its path length at a fixed speed, and each calorimeter hit appears only
## when that fixed-speed front (straight-line from the IP) reaches it.
## Driven through the cv_event_reveal global shader parameter.
func play_emergence() -> void:
	_reveal = 0.0
	RenderingServer.global_shader_parameter_set("cv_event_reveal", 0.0)
	set_process(true)


func _ready() -> void:
	set_process(false)


func _process(delta: float) -> void:
	_reveal += REVEAL_SPEED * delta
	RenderingServer.global_shader_parameter_set("cv_event_reveal", _reveal)
	if _reveal > _max_extent + 0.5:
		RenderingServer.global_shader_parameter_set("cv_event_reveal", 1e9)
		set_process(false)


# ── Tracks ────────────────────────────────────────────────────────────────────

func _build_tracks(tracks: Variant) -> int:
	if typeof(tracks) != TYPE_ARRAY:
		return 0
	var count := 0
	for tr in tracks:
		if typeof(tr) != TYPE_DICTIONARY:
			continue
		var pts := _to_points(tr.get("points", []))
		if pts.size() < 2:
			continue
		var charge := float(tr.get("charge", 0.0))
		var momentum := float(tr.get("momentum_gev", 1.0))
		track_infos.append({"pdg": int(tr.get("pdg", 0)),
			"charge": charge, "p": momentum})
		var color := NEUTRAL_TRACK_COLOR
		if charge > 0.0:
			color = POSITIVE_TRACK_COLOR
		elif charge < 0.0:
			color = NEGATIVE_TRACK_COLOR
		var mesh := _tube_mesh(pts, TRACK_RADIUS_M)
		if mesh == null:
			continue
		var mi := MeshInstance3D.new()
		mi.mesh = mesh
		var mat := ShaderMaterial.new()
		mat.shader = TRACK_SHADER
		mat.set_shader_parameter("albedo", Color(color, 1.0).darkened(0.85))
		mat.set_shader_parameter("emission_color", color)
		# Momentum-scaled glow (UE: EmissiveIntensity = p * scale, clamped).
		mat.set_shader_parameter("emission_energy", clampf(momentum * 0.6, 1.2, 10.0))
		mi.material_override = mat
		# DYNAMIC: events change — they must never bake into the VoxelGI field.
		mi.gi_mode = GeometryInstance3D.GI_MODE_DYNAMIC
		add_child(mi)
		count += 1
	return count


func _to_points(raw: Variant) -> PackedVector3Array:
	var out := PackedVector3Array()
	if typeof(raw) != TYPE_ARRAY:
		return out
	for p in raw:
		if typeof(p) == TYPE_ARRAY and p.size() >= 3:
			out.append(Vector3(float(p[0]), float(p[1]), float(p[2])) * MM_TO_M)
	return out


## Sweeps a circle along a polyline using parallel-transport frames.
## UV.x of every vertex carries its arc length from the first point, which
## the track shader uses for the constant-speed propagation reveal.
func _tube_mesh(pts: PackedVector3Array, radius: float) -> ArrayMesh:
	var n := pts.size()
	# Tangents and cumulative arc lengths per point.
	var tangents := PackedVector3Array()
	tangents.resize(n)
	var arc := PackedFloat32Array()
	arc.resize(n)
	arc[0] = 0.0
	for i in n:
		var t: Vector3
		if i == 0:
			t = pts[1] - pts[0]
		elif i == n - 1:
			t = pts[n - 1] - pts[n - 2]
		else:
			t = pts[i + 1] - pts[i - 1]
		tangents[i] = t.normalized() if t.length() > 1e-9 else Vector3.FORWARD
		if i > 0:
			arc[i] = arc[i - 1] + pts[i].distance_to(pts[i - 1])
	_max_extent = maxf(_max_extent, arc[n - 1])
	# Initial frame.
	var normal := tangents[0].cross(Vector3.UP)
	if normal.length() < 1e-4:
		normal = tangents[0].cross(Vector3.RIGHT)
	normal = normal.normalized()
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var rings := []
	for i in n:
		if i > 0:
			# Parallel-transport the normal onto the new tangent.
			var axis := tangents[i - 1].cross(tangents[i])
			var s := axis.length()
			if s > 1e-6:
				var ang := tangents[i - 1].angle_to(tangents[i])
				normal = normal.rotated(axis / s, ang)
		var binormal := tangents[i].cross(normal).normalized()
		var ring := []
		for j in TUBE_SIDES:
			var a := TAU * float(j) / float(TUBE_SIDES)
			var dir := (normal * cos(a) + binormal * sin(a)).normalized()
			ring.append([pts[i] + dir * radius, dir, arc[i]])
		rings.append(ring)
	for i in n - 1:
		for j in TUBE_SIDES:
			var j2 := (j + 1) % TUBE_SIDES
			var a = rings[i][j]
			var b = rings[i][j2]
			var c = rings[i + 1][j]
			var d = rings[i + 1][j2]
			_emit_tri(st, a, c, b)
			_emit_tri(st, b, c, d)
	# End caps.
	for cap in [[0, -1], [n - 1, 1]]:
		var idx: int = cap[0]
		var sgn: float = cap[1]
		var center := pts[idx]
		var cn := tangents[idx] * sgn
		var cuv := Vector2(arc[idx], 0)
		for j in TUBE_SIDES:
			var j2 := (j + 1) % TUBE_SIDES
			st.set_normal(cn)
			st.set_uv(cuv)
			st.add_vertex(center)
			if sgn > 0.0:
				st.set_normal(cn); st.set_uv(cuv); st.add_vertex(rings[idx][j][0])
				st.set_normal(cn); st.set_uv(cuv); st.add_vertex(rings[idx][j2][0])
			else:
				st.set_normal(cn); st.set_uv(cuv); st.add_vertex(rings[idx][j2][0])
				st.set_normal(cn); st.set_uv(cuv); st.add_vertex(rings[idx][j][0])
	return st.commit()


func _emit_tri(st: SurfaceTool, a: Array, b: Array, c: Array) -> void:
	st.set_normal(a[1]); st.set_uv(Vector2(a[2], 0)); st.add_vertex(a[0])
	st.set_normal(b[1]); st.set_uv(Vector2(b[2], 0)); st.add_vertex(b[0])
	st.set_normal(c[1]); st.set_uv(Vector2(c[2], 0)); st.add_vertex(c[0])


# ── Calorimeter hits ─────────────────────────────────────────────────────────

func _build_calo_hits(hits: Variant) -> int:
	if typeof(hits) != TYPE_ARRAY or (hits as Array).is_empty():
		return 0
	var positions := PackedVector3Array()
	var energies := PackedFloat32Array()
	var e_max := 1e-9
	for h in hits:
		if typeof(h) != TYPE_DICTIONARY:
			continue
		var p: Variant = h.get("position", null)
		if typeof(p) != TYPE_ARRAY or p.size() < 3:
			continue
		positions.append(Vector3(float(p[0]), float(p[1]), float(p[2])) * MM_TO_M)
		var e := float(h.get("energy_gev", 0.0))
		energies.append(e)
		e_max = maxf(e_max, e)
		calo_energy_sum += e
	n_calo_hits = positions.size()
	if positions.is_empty():
		return 0
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	mm.use_custom_data = true
	var cube := BoxMesh.new()
	cube.size = Vector3.ONE * CALO_CUBE_M
	mm.mesh = cube
	mm.instance_count = positions.size()
	for i in positions.size():
		# Log-ish energy normalisation so MIP-scale hits stay visible.
		var t := clampf(pow(energies[i] / e_max, 0.35), 0.0, 1.0)
		var col := CALO_COLD.lerp(CALO_HOT, t)
		var s := 0.6 + 1.8 * t   # hotter hits are bigger
		var xf := Transform3D(Basis.IDENTITY.scaled(Vector3.ONE * s), positions[i])
		mm.set_instance_transform(i, xf)
		# Alpha channel carries the normalised energy for the shader.
		mm.set_instance_color(i, Color(col.r, col.g, col.b, t))
		# CUSTOM.r: straight-line distance from the IP — the hit appears
		# when the fixed-speed reveal front reaches it.
		var d := positions[i].length()
		mm.set_instance_custom_data(i, Color(d, 0, 0, 0))
		_max_extent = maxf(_max_extent, d)
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	var mat := ShaderMaterial.new()
	mat.shader = CALO_SHADER
	mmi.material_override = mat
	add_child(mmi)
	return positions.size()


# ── MC truth lines ───────────────────────────────────────────────────────────

func _build_mc_particles(parts: Variant) -> int:
	if typeof(parts) != TYPE_ARRAY or (parts as Array).is_empty():
		return 0
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_LINES)
	var count := 0
	for mp in parts:
		if typeof(mp) != TYPE_DICTIONARY:
			continue
		var v: Variant = mp.get("vertex", null)
		var e: Variant = mp.get("end_vertex", null)
		if typeof(v) != TYPE_ARRAY or typeof(e) != TYPE_ARRAY:
			continue
		if v.size() < 3 or e.size() < 3:
			continue
		var p_vec: Variant = mp.get("momentum_gev", null)
		var p_mag := 0.0
		if typeof(p_vec) == TYPE_ARRAY and p_vec.size() >= 3:
			p_mag = Vector3(float(p_vec[0]), float(p_vec[1]), float(p_vec[2])).length()
		mc_infos.append({"pdg": int(mp.get("pdg", 0)), "p": p_mag,
			"status": int(mp.get("status", 0))})
		var a := Vector3(float(v[0]), float(v[1]), float(v[2])) * MM_TO_M
		var b := Vector3(float(e[0]), float(e[1]), float(e[2])) * MM_TO_M
		if a.distance_to(b) < 1e-4:
			continue
		# UV.x = distance from the IP, for the propagation reveal.
		st.set_uv(Vector2(a.length(), 0))
		st.add_vertex(a)
		st.set_uv(Vector2(b.length(), 0))
		st.add_vertex(b)
		_max_extent = maxf(_max_extent, b.length())
		count += 1
	if count == 0:
		return 0
	var mi := MeshInstance3D.new()
	mi.mesh = st.commit()
	var mat := ShaderMaterial.new()
	mat.shader = MC_SHADER
	mat.set_shader_parameter("line_color", Color(MC_COLOR, 0.55))
	mat.set_shader_parameter("emission_energy", 1.4)
	mi.material_override = mat
	add_child(mi)
	return count
