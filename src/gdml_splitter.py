"""
GDML splitter: split a monolithic ddsim GDML into per-sub-detector GDML files.

Uses lxml for pure XML manipulation — no pyg4ometry required for this step.
Sub-detectors are identified by traversing N levels below the world volume
(controlled by the --depth flag; default 1 = direct daughters of world).

Memory strategy
---------------
For very large GDML files (100+ MB), the naive approach of deepcopy-ing
elements into a new tree can double peak memory.  Instead, we serialise
needed elements directly from the parsed source tree using
``etree.tostring(el)`` and write them incrementally to the output file,
avoiding a second in-memory tree altogether.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from lxml import etree


def _log(msg: str) -> None:
    """Print a timestamped progress message, flushing immediately."""
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_index(root: etree._Element, xpath: str) -> dict[str, etree._Element]:
    """Return a name→element dict for all elements matched by xpath."""
    return {
        el.get("name"): el
        for el in root.findall(xpath)
        if el.get("name") is not None
    }


def _physvols_at_depth(
    lv_name: str,
    logvols: dict[str, etree._Element],
    depth: int,
) -> list[tuple[str, etree._Element]]:
    """
    Return (child_lv_name, physvol_elem) pairs at `depth` levels below lv_name.

    depth=1 → direct daughters of lv_name.
    depth=2 → grandchildren, etc.
    """
    lv = logvols.get(lv_name)
    if lv is None:
        return []
    children = [
        (pv.find("volumeref").get("ref"), pv)
        for pv in lv.findall("physvol")
        if pv.find("volumeref") is not None
    ]
    if depth == 1:
        return children
    result: list[tuple[str, etree._Element]] = []
    for child_name, _ in children:
        result.extend(_physvols_at_depth(child_name, logvols, depth - 1))
    return result


def _clean_name(name: str) -> str:
    """Strip common volume-name suffixes to produce a readable filename stem."""
    for suffix in ("_envelope", "_assembly", "_volume", "_vol", "_lv"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return name


# ---------------------------------------------------------------------------
# Dependency collector
# ---------------------------------------------------------------------------

class _Collector:
    """
    Walk the geometry tree rooted at a given logical volume and collect the
    complete set of elements (defines, materials, solids, logvols) needed to
    produce a self-contained GDML for that sub-detector.

    Elements are added to *_order lists in topological (children-first) order
    so the output GDML is parseable by strict validators.
    """

    def __init__(
        self,
        defines: dict[str, etree._Element],
        materials: dict[str, etree._Element],
        solids_map: dict[str, etree._Element],
        logvols: dict[str, etree._Element],
    ) -> None:
        self.defines = defines
        self.materials = materials
        self.solids_map = solids_map
        self.logvols = logvols

        self.needed_defines: set[str] = set()
        self.needed_materials: set[str] = set()
        self.needed_solids: set[str] = set()
        self.needed_logvols: set[str] = set()

        # Topological order (dependencies before dependents)
        self.solid_order: list[str] = []
        self.logvol_order: list[str] = []

        self._vis_solids: set[str] = set()
        self._vis_logvols: set[str] = set()

        # Progress counters (updated during traversal)
        self._lv_count: int = 0
        self._last_report: int = 0

    # ---- public entry points ----

    def collect_logvol(self, name: str) -> None:
        if name in self._vis_logvols:
            return
        self._vis_logvols.add(name)

        lv = self.logvols.get(name)
        if lv is None:
            return

        # Solid (absent for <assembly> volumes — DD4hep uses these heavily)
        solidref = lv.find("solidref")
        if solidref is not None:
            self.collect_solid(solidref.get("ref"))

        # Material
        matref = lv.find("materialref")
        if matref is not None:
            self._collect_material(matref.get("ref"))

        # Recurse daughters (post-order so children come before parents)
        for pv in lv.findall("physvol"):
            volref = pv.find("volumeref")
            if volref is not None:
                self.collect_logvol(volref.get("ref"))
            # Collect define refs used in placement
            self._collect_pv_defines(pv)

        self.needed_logvols.add(name)
        self.logvol_order.append(name)

        # Emit a progress dot every 500 unique logical volumes visited
        self._lv_count += 1
        if self._lv_count - self._last_report >= 500:
            self._last_report = self._lv_count
            print(f"    ... {self._lv_count} logical volumes collected so far",
                  flush=True)

    def collect_solid(self, name: str) -> None:
        if name in self._vis_solids:
            return
        self._vis_solids.add(name)

        solid = self.solids_map.get(name)
        if solid is None:
            return

        tag = solid.tag
        if tag in ("subtraction", "union", "intersection"):
            for sub_tag in ("first", "second"):
                r = solid.find(sub_tag)
                if r is not None:
                    self.collect_solid(r.get("ref"))
            for ref_tag in ("positionref", "rotationref"):
                el = solid.find(ref_tag)
                if el is not None:
                    self.needed_defines.add(el.get("ref"))

        elif tag == "multiUnion":
            for node in solid.findall("multiUnionNode"):
                s = node.find("solid")
                if s is not None:
                    self.collect_solid(s.get("ref"))
                for ref_tag in ("positionref", "rotationref"):
                    el = node.find(ref_tag)
                    if el is not None:
                        self.needed_defines.add(el.get("ref"))

        elif tag in ("reflectedSolid", "scaledSolid"):
            ref_el = solid.find("solidref")
            if ref_el is not None:
                self.collect_solid(ref_el.get("ref"))

        # Primitives (box, tube, sphere, trd, polycone, …) need no recursion.

        self.needed_solids.add(name)
        self.solid_order.append(name)

    def collect_placement_defines(self, physvol: etree._Element) -> None:
        """Collect positionref/rotationref/scaleref used by the top physvol."""
        self._collect_pv_defines(physvol)

    # ---- private helpers ----

    def _collect_pv_defines(self, pv: etree._Element) -> None:
        for tag in ("positionref", "rotationref", "scaleref"):
            el = pv.find(tag)
            if el is not None:
                self.needed_defines.add(el.get("ref"))

    def _collect_material(self, name: str) -> None:
        if name in self.needed_materials:
            return
        # NIST built-ins (G4_*) are provided by Geant4 at runtime; not in file
        if name.startswith("G4_"):
            return
        self.needed_materials.add(name)
        mat = self.materials.get(name)
        if mat is None:
            return
        # Recurse into composite fractions / component materials
        for child in mat:
            ref = child.get("ref")
            if ref:
                self._collect_material(ref)


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def split_gdml(
    input_path: str | Path,
    output_dir: str | Path,
    depth: int = 1,
    detectors: list[str] | None = None,
) -> list[tuple[str, Path]]:
    """
    Split a ddsim/DD4hep GDML file into one GDML per sub-detector system.

    Parameters
    ----------
    input_path : path to the source GDML file
    output_dir : directory where split GDMLs are written
    depth      : how many levels below the world volume to split at (default 1)
    detectors  : if given, only write sub-detectors whose LV name is in this list

    Returns
    -------
    List of (lv_name, output_path) tuples for every file written.
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- Step 1: parse ----
    file_size_mb = input_path.stat().st_size / 1_048_576
    _log(f"Parsing {input_path.name} ({file_size_mb:.1f} MB) …")
    t0 = time.monotonic()
    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(str(input_path), parser)
    root = tree.getroot()
    _log(f"Parse complete ({time.monotonic() - t0:.1f}s)")

    # ---- Step 2: build element indexes ----
    _log("Building element indexes …")
    t0 = time.monotonic()
    defines    = _build_index(root, "./define/*")
    materials  = _build_index(root, "./materials/*")
    solids_map = _build_index(root, "./solids/*")
    # Both <volume> and <assembly> elements live in <structure>
    logvols    = _build_index(root, "./structure/*")
    _log(
        f"Indexes built ({time.monotonic() - t0:.1f}s): "
        f"{len(defines)} defines, {len(materials)} materials, "
        f"{len(solids_map)} solids, {len(logvols)} logical volumes"
    )

    # ---- Step 3: locate world volume ----
    world_ref_el = root.find("setup/world")
    if world_ref_el is None:
        raise ValueError("Cannot find <setup><world ref=...> in GDML")
    world_name = world_ref_el.get("ref")
    _log(f"World volume: {world_name!r}")

    world_lv = logvols.get(world_name)
    if world_lv is None:
        raise ValueError(f"World volume '{world_name}' not found in <structure>")

    # World solid (reused as enclosing box in each output GDML)
    world_solidref   = world_lv.find("solidref")
    world_solid_name = world_solidref.get("ref") if world_solidref is not None else None

    # ---- Step 4: find sub-detectors ----
    _log(f"Finding sub-detectors at depth={depth} …")
    subdet_list = _physvols_at_depth(world_name, logvols, depth)
    if not subdet_list:
        raise ValueError(
            f"No sub-detectors found at depth={depth} below world "
            f"volume '{world_name}'. Try a smaller --depth value."
        )
    _log(f"Found {len(subdet_list)} sub-detector(s) at depth={depth}")
    for lv_name, _ in subdet_list:
        print(f"    {lv_name}", flush=True)

    # Optional name filter
    if detectors:
        det_set = set(detectors)
        subdet_list = [(n, pv) for n, pv in subdet_list if n in det_set]
        if not subdet_list:
            raise ValueError(
                f"None of the requested detectors {detectors} were found at "
                f"depth={depth}. Available: "
                + ", ".join(n for n, _ in _physvols_at_depth(world_name, logvols, depth))
            )
        _log(f"After filter: {len(subdet_list)} sub-detector(s) selected")

    results: list[tuple[str, Path]] = []

    for idx, (lv_name, placement_pv) in enumerate(subdet_list, 1):
        _log(
            f"[{idx}/{len(subdet_list)}] Collecting dependencies for {lv_name!r} …"
        )
        t0 = time.monotonic()
        c = _Collector(defines, materials, solids_map, logvols)
        c.collect_logvol(lv_name)
        c.collect_placement_defines(placement_pv)
        # Do NOT collect the real world solid — it is a large bounding box
        # that would render as visible geometry.  A tiny dummy box is written
        # instead (see _write_subdetector_gdml).
        _log(
            f"    Collected in {time.monotonic() - t0:.1f}s: "
            f"{len(c.logvol_order)} logvols, {len(c.solid_order)} solids, "
            f"{len(c.needed_materials)} materials, {len(c.needed_defines)} defines"
        )

        # ---- Write output GDML incrementally ----
        # Instead of building an entire second tree via deepcopy (which doubles
        # peak memory for large GDMLs), we serialise needed elements directly
        # from the source tree into the output file.
        stem     = _clean_name(lv_name)
        out_path = output_dir / f"{stem}.gdml"
        _log(f"    Writing {out_path.name} (streaming) …")

        new_world_name = f"World_{lv_name}_lv"
        _write_subdetector_gdml(
            out_path,
            root=root,
            defines=defines,
            materials=materials,
            solids_map=solids_map,
            logvols=logvols,
            collector=c,
            world_solid_name=world_solid_name,
            new_world_name=new_world_name,
            placement_pv=placement_pv,
        )

        out_size_mb = out_path.stat().st_size / 1_048_576
        _log(f"    Done → {out_path.name} ({out_size_mb:.2f} MB)")
        results.append((lv_name, out_path))

    _log(f"Split complete — {len(results)} file(s) written to {output_dir}/")
    return results


def _write_subdetector_gdml(
    out_path: Path,
    *,
    root: etree._Element,
    defines: dict[str, etree._Element],
    materials: dict[str, etree._Element],
    solids_map: dict[str, etree._Element],
    logvols: dict[str, etree._Element],
    collector: _Collector,
    world_solid_name: str | None,
    new_world_name: str,
    placement_pv: etree._Element,
) -> None:
    """
    Write a self-contained sub-detector GDML file.

    Uses incremental serialisation: each element is serialised from the
    *source* tree via ``etree.tostring()`` and written to disk without
    building a complete second in-memory tree.  For a 200 MB source GDML
    this avoids ~200 MB of deepcopy overhead per sub-detector.
    """
    xsi = "http://www.w3.org/2001/XMLSchema-instance"
    schema_loc = root.get(f"{{{xsi}}}noNamespaceSchemaLocation", "")
    schema_attr = ""
    if schema_loc:
        schema_attr = f' xmlns:xsi="{xsi}" xsi:noNamespaceSchemaLocation="{schema_loc}"'

    with open(out_path, "wb") as fh:
        fh.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write(f'<gdml{schema_attr}>\n'.encode())

        # <define>
        fh.write(b'  <define>\n')
        for name in sorted(collector.needed_defines):
            el = defines.get(name)
            if el is not None:
                fh.write(b'    ')
                fh.write(etree.tostring(el, pretty_print=True))
        fh.write(b'  </define>\n')

        # <materials>
        fh.write(b'  <materials>\n')
        for name in sorted(collector.needed_materials):
            el = materials.get(name)
            if el is not None:
                fh.write(b'    ')
                fh.write(etree.tostring(el, pretty_print=True))
        fh.write(b'  </materials>\n')

        # <solids> — topological order (boolean children before parents)
        # A tiny 1 mm dummy box is added first as the world solid so that
        # pyg4ometry has a valid <volume> world, but it is invisible at
        # detector scales and is excluded from the Air→assembly conversion
        # in the converter's simplifier.
        _WORLD_DUMMY_SOLID = "_DDGeoViz_WorldBox_"
        fh.write(b'  <solids>\n')
        fh.write(
            f'    <box name="{_WORLD_DUMMY_SOLID}" '
            f'x="1.0" y="1.0" z="1.0" lunit="mm"/>\n'.encode()
        )
        for name in collector.solid_order:
            el = solids_map.get(name)
            if el is not None:
                fh.write(b'    ')
                fh.write(etree.tostring(el, pretty_print=True))
        fh.write(b'  </solids>\n')

        # <structure> — children before parents
        fh.write(b'  <structure>\n')
        for name in collector.logvol_order:
            el = logvols.get(name)
            if el is not None:
                fh.write(b'    ')
                fh.write(etree.tostring(el, pretty_print=True))

        # Minimal world volume containing only this sub-detector.
        # References the tiny dummy box so the world envelope does not render.
        fh.write(f'    <volume name="{new_world_name}">\n'.encode())
        fh.write(f'      <solidref ref="{_WORLD_DUMMY_SOLID}"/>\n'.encode())
        fh.write(b'      <materialref ref="G4_AIR"/>\n')
        fh.write(b'      ')
        fh.write(etree.tostring(placement_pv, pretty_print=True))
        fh.write(b'    </volume>\n')
        fh.write(b'  </structure>\n')

        # <setup>
        fh.write(b'  <setup name="Default" version="1.0">\n')
        fh.write(f'    <world ref="{new_world_name}"/>\n'.encode())
        fh.write(b'  </setup>\n')

        fh.write(b'</gdml>\n')
