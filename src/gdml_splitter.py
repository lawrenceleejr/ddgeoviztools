"""
GDML splitter: split a monolithic ddsim GDML into per-sub-detector GDML files.

Uses lxml for pure XML manipulation — no pyg4ometry required for this step.
Sub-detectors are identified by traversing N levels below the world volume
(controlled by the --depth flag; default 1 = direct daughters of world).
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from lxml import etree


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

    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(str(input_path), parser)
    root = tree.getroot()

    # Build element indexes
    defines    = _build_index(root, "./define/*")
    materials  = _build_index(root, "./materials/*")
    solids_map = _build_index(root, "./solids/*")
    # Both <volume> and <assembly> elements live in <structure>
    logvols    = _build_index(root, "./structure/*")

    # Locate the world volume from <setup><world ref="..."/>
    world_ref_el = root.find("setup/world")
    if world_ref_el is None:
        raise ValueError("Cannot find <setup><world ref=...> in GDML")
    world_name = world_ref_el.get("ref")

    world_lv = logvols.get(world_name)
    if world_lv is None:
        raise ValueError(f"World volume '{world_name}' not found in <structure>")

    # World solid (reused as enclosing box in each output GDML)
    world_solidref = world_lv.find("solidref")
    world_solid_name = world_solidref.get("ref") if world_solidref is not None else None

    # Find sub-detectors at the requested depth
    subdet_list = _physvols_at_depth(world_name, logvols, depth)
    if not subdet_list:
        raise ValueError(
            f"No sub-detectors found at depth={depth} below world "
            f"volume '{world_name}'. Try a smaller --depth value."
        )

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

    results: list[tuple[str, Path]] = []

    for lv_name, placement_pv in subdet_list:
        c = _Collector(defines, materials, solids_map, logvols)
        c.collect_logvol(lv_name)
        c.collect_placement_defines(placement_pv)
        if world_solid_name:
            c.collect_solid(world_solid_name)

        # ---- Assemble output GDML tree ----
        nsmap = root.nsmap
        new_root = etree.Element("gdml", nsmap=nsmap)
        xsi = "http://www.w3.org/2001/XMLSchema-instance"
        schema_loc = root.get(f"{{{xsi}}}noNamespaceSchemaLocation")
        if schema_loc:
            new_root.set(f"{{{xsi}}}noNamespaceSchemaLocation", schema_loc)

        # <define>
        new_define = etree.SubElement(new_root, "define")
        for name, el in defines.items():
            if name in c.needed_defines:
                new_define.append(deepcopy(el))

        # <materials>
        new_mats = etree.SubElement(new_root, "materials")
        for name, el in materials.items():
            if name in c.needed_materials:
                new_mats.append(deepcopy(el))

        # <solids> — topological order (boolean children before parents)
        new_solids = etree.SubElement(new_root, "solids")
        for name in c.solid_order:
            el = solids_map.get(name)
            if el is not None:
                new_solids.append(deepcopy(el))

        # <structure> — children before parents
        new_struct = etree.SubElement(new_root, "structure")
        for name in c.logvol_order:
            el = logvols.get(name)
            if el is not None:
                new_struct.append(deepcopy(el))

        # Minimal world volume containing only this sub-detector
        new_world_name = f"World_{lv_name}_lv"
        new_world = etree.SubElement(new_struct, "volume", name=new_world_name)
        if world_solid_name:
            etree.SubElement(new_world, "solidref", ref=world_solid_name)
        etree.SubElement(new_world, "materialref", ref="G4_AIR")
        new_world.append(deepcopy(placement_pv))

        # <setup>
        new_setup = etree.SubElement(new_root, "setup", name="Default", version="1.0")
        etree.SubElement(new_setup, "world", ref=new_world_name)

        # Write file
        stem = _clean_name(lv_name)
        out_path = output_dir / f"{stem}.gdml"
        etree.ElementTree(new_root).write(
            str(out_path),
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
        )
        print(f"  Wrote {out_path.name}")
        results.append((lv_name, out_path))

    return results
