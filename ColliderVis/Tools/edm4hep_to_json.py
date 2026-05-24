#!/usr/bin/env python3
"""
edm4hep_to_json.py — Convert EDM4HEP ROOT files to per-event JSON.

Usage:
    python edm4hep_to_json.py <input.root> <output_dir/> [--event N]

Output:
    output_dir/event_NNNN.json  (one file per event, or only event N if --event given)

JSON schema per event:
{
  "event_number": 42,
  "run_number": 1,
  "tracks": [
    { "points": [[x,y,z],...], "charge": 1.0, "momentum_gev": 15.3, "pdg": 211 }
  ],
  "calo_hits": [
    { "collection": "ECalBarrelHits", "position": [x,y,z], "energy_gev": 0.023 }
  ],
  "mc_particles": [
    { "vertex": [x,y,z], "end_vertex": [x,y,z], "momentum_gev": [px,py,pz],
      "pdg": 11, "charge": -1.0, "status": 1 }
  ]
}

All positions in mm.  Momenta in GeV/c.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

try:
    import uproot
    import awkward as ak
    import numpy as np
except ImportError as e:
    print(f"ERROR: Missing dependency — {e}", file=sys.stderr)
    print("Install with:  pip install uproot awkward numpy", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# EDM4HEP collection names to look for (case-insensitive prefix matching)
# ---------------------------------------------------------------------------

TRACK_COLLECTIONS = [
    "Tracks", "SiTracks", "CentralCKFTracks", "TrackCollection"
]
CALO_COLLECTIONS = [
    "ECalBarrelHits", "ECalEndcapHits", "HCalBarrelHits", "HCalEndcapHits",
    "MuonHits", "EcalHits", "HcalHits", "LumiCalHits", "BeamCalHits",
]
MC_COLLECTION = "MCParticles"


def _find_collection(tree_keys: list[str], candidates: list[str]) -> list[str]:
    """Return all tree keys whose name matches any candidate (substring, case-insensitive)."""
    found = []
    for key in tree_keys:
        # uproot keys may include branch-type suffix like "Tracks/Tracks.charge"
        base = key.split("/")[0].split(".")[0]
        for cand in candidates:
            if cand.lower() in base.lower():
                found.append(base)
                break
    return list(dict.fromkeys(found))  # deduplicate, preserve order


def _safe_float(val) -> float:
    try:
        f = float(val)
        return f if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _safe_int(val) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def extract_tracks(tree, collection_name: str, event_idx: int) -> list[dict]:
    """Extract reconstructed tracks from an EDM4HEP TTree branch."""
    tracks = []
    try:
        # EDM4HEP track state branches
        branch_prefix = f"{collection_name}/{collection_name}"
        charge_key  = f"{branch_prefix}.charge"
        state_key   = f"{branch_prefix}.trackStates"  # array of TrackState per track

        # Simpler flat access: read charge + referencePoint
        charges = tree[charge_key].array(entry_start=event_idx, entry_stop=event_idx + 1)[0]
        ref_pts = tree[f"{branch_prefix}.referencePoint.x"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)[0]
        ref_pts_y = tree[f"{branch_prefix}.referencePoint.y"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)[0]
        ref_pts_z = tree[f"{branch_prefix}.referencePoint.z"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)[0]

        # Momentum from track parameters (Omega = qOverPt, etc.)
        omega  = tree[f"{branch_prefix}.omega"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)[0]
        tanL   = tree[f"{branch_prefix}.tanLambda"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)[0]
        phi0   = tree[f"{branch_prefix}.phi"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)[0]

        for i in range(len(charges)):
            charge = _safe_float(charges[i])
            omega_val = _safe_float(omega[i])
            tanl_val  = _safe_float(tanL[i])
            phi_val   = _safe_float(phi0[i])

            # pT from omega: pT [GeV/c] = 0.3 * B [T] / |omega [mm^-1]|  (B ~ 3.5T typical)
            # Use B=3.5T as default; this gives approximate momentum
            B = 3.5  # Tesla
            pt = (0.3 * B / abs(omega_val)) if abs(omega_val) > 1e-10 else 0.0
            pz = pt * tanl_val
            p_total = math.sqrt(pt ** 2 + pz ** 2)

            # Build a 2-point "track" from reference point outward along momentum
            x0, y0, z0 = (
                _safe_float(ref_pts[i]),
                _safe_float(ref_pts_y[i]),
                _safe_float(ref_pts_z[i]),
            )
            # Extrapolate to ~1000mm along direction
            px = pt * math.cos(phi_val)
            py = pt * math.sin(phi_val)
            scale = 1000.0 / (p_total if p_total > 0 else 1.0)
            x1 = x0 + px * scale
            y1 = y0 + py * scale
            z1 = z0 + pz * scale

            tracks.append({
                "points": [[x0, y0, z0], [x1, y1, z1]],
                "charge": charge,
                "momentum_gev": round(p_total, 4),
                "pdg": 0,  # PDG not stored in reco tracks
            })
    except Exception as exc:
        # Collection may not have all branches — silently skip
        pass

    return tracks


def extract_calo_hits(tree, collection_name: str, event_idx: int) -> list[dict]:
    """Extract calorimeter hits from an EDM4HEP SimCalorimeterHit or CalorimeterHit branch."""
    hits = []
    try:
        branch_prefix = f"{collection_name}/{collection_name}"
        xs      = tree[f"{branch_prefix}.position.x"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)[0]
        ys      = tree[f"{branch_prefix}.position.y"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)[0]
        zs      = tree[f"{branch_prefix}.position.z"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)[0]
        energies = tree[f"{branch_prefix}.energy"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)[0]

        for i in range(len(energies)):
            hits.append({
                "collection": collection_name,
                "position": [
                    _safe_float(xs[i]),
                    _safe_float(ys[i]),
                    _safe_float(zs[i]),
                ],
                "energy_gev": round(_safe_float(energies[i]), 6),
            })
    except Exception:
        pass

    return hits


def extract_mc_particles(tree, event_idx: int) -> list[dict]:
    """Extract MCParticles truth collection."""
    particles = []
    try:
        bp = f"{MC_COLLECTION}/{MC_COLLECTION}"
        vx = tree[f"{bp}.vertex.x"].array(entry_start=event_idx, entry_stop=event_idx + 1)[0]
        vy = tree[f"{bp}.vertex.y"].array(entry_start=event_idx, entry_stop=event_idx + 1)[0]
        vz = tree[f"{bp}.vertex.z"].array(entry_start=event_idx, entry_stop=event_idx + 1)[0]
        ex = tree[f"{bp}.endpoint.x"].array(entry_start=event_idx, entry_stop=event_idx + 1)[0]
        ey = tree[f"{bp}.endpoint.y"].array(entry_start=event_idx, entry_stop=event_idx + 1)[0]
        ez = tree[f"{bp}.endpoint.z"].array(entry_start=event_idx, entry_stop=event_idx + 1)[0]
        px = tree[f"{bp}.momentum.x"].array(entry_start=event_idx, entry_stop=event_idx + 1)[0]
        py = tree[f"{bp}.momentum.y"].array(entry_start=event_idx, entry_stop=event_idx + 1)[0]
        pz = tree[f"{bp}.momentum.z"].array(entry_start=event_idx, entry_stop=event_idx + 1)[0]
        pdgs    = tree[f"{bp}.PDG"].array(entry_start=event_idx, entry_stop=event_idx + 1)[0]
        charges = tree[f"{bp}.charge"].array(entry_start=event_idx, entry_stop=event_idx + 1)[0]
        statuses = tree[f"{bp}.generatorStatus"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)[0]

        for i in range(len(pdgs)):
            particles.append({
                "vertex":     [_safe_float(vx[i]), _safe_float(vy[i]), _safe_float(vz[i])],
                "end_vertex": [_safe_float(ex[i]), _safe_float(ey[i]), _safe_float(ez[i])],
                "momentum_gev": [_safe_float(px[i]), _safe_float(py[i]), _safe_float(pz[i])],
                "pdg":    _safe_int(pdgs[i]),
                "charge": _safe_float(charges[i]),
                "status": _safe_int(statuses[i]),
            })
    except Exception:
        pass

    return particles


def convert_event(tree, event_idx: int, track_colls: list[str],
                  calo_colls: list[str]) -> dict:
    tracks = []
    for coll in track_colls:
        tracks.extend(extract_tracks(tree, coll, event_idx))

    calo_hits = []
    for coll in calo_colls:
        calo_hits.extend(extract_calo_hits(tree, coll, event_idx))

    mc_particles = extract_mc_particles(tree, event_idx)

    # Try to read run/event number from EventHeader
    event_number = event_idx
    run_number   = 0
    try:
        evnums = tree["EventHeader/EventHeader.eventNumber"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)
        runnums = tree["EventHeader/EventHeader.runNumber"].array(
            entry_start=event_idx, entry_stop=event_idx + 1)
        if len(evnums) > 0:
            event_number = int(evnums[0])
        if len(runnums) > 0:
            run_number = int(runnums[0])
    except Exception:
        pass

    return {
        "event_number": event_number,
        "run_number":   run_number,
        "tracks":       tracks,
        "calo_hits":    calo_hits,
        "mc_particles": mc_particles,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert EDM4HEP ROOT file to per-event JSON files."
    )
    parser.add_argument("input",      help="Input .root file")
    parser.add_argument("output_dir", help="Directory for output event_NNNN.json files")
    parser.add_argument("--event", type=int, default=None,
                        help="Convert only this event index (0-based)")
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_dir  = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Opening {input_path} ...")
    try:
        root_file = uproot.open(str(input_path))
    except Exception as e:
        print(f"ERROR: Cannot open ROOT file: {e}", file=sys.stderr)
        sys.exit(1)

    # EDM4HEP stores data in a TTree named "events"
    tree_name = "events"
    if tree_name not in root_file:
        # Try alternative names
        for key in root_file.keys():
            if "event" in key.lower() and ";" not in key:
                tree_name = key
                break
        else:
            print(f"ERROR: Could not find 'events' TTree in {input_path}", file=sys.stderr)
            print(f"Available keys: {list(root_file.keys())}", file=sys.stderr)
            sys.exit(1)

    tree = root_file[tree_name]
    n_events = tree.num_entries
    print(f"Found {n_events} events in tree '{tree_name}'")

    # Discover collections
    all_keys = [k for k in tree.keys()]
    track_colls = _find_collection(all_keys, TRACK_COLLECTIONS)
    calo_colls  = _find_collection(all_keys, CALO_COLLECTIONS)
    print(f"Track collections: {track_colls}")
    print(f"Calo  collections: {calo_colls}")

    # Determine which events to convert
    if args.event is not None:
        event_indices = [args.event]
    else:
        event_indices = range(n_events)

    converted = 0
    for idx in event_indices:
        if idx >= n_events:
            print(f"WARNING: Event {idx} out of range ({n_events} events)", file=sys.stderr)
            continue

        event_data = convert_event(tree, idx, track_colls, calo_colls)
        out_path   = output_dir / f"event_{idx:04d}.json"

        with open(out_path, "w") as fp:
            json.dump(event_data, fp, indent=2)

        converted += 1
        if converted % 10 == 0 or n_events <= 20:
            print(f"  Wrote {out_path.name}  "
                  f"({len(event_data['tracks'])} tracks, "
                  f"{len(event_data['calo_hits'])} calo hits, "
                  f"{len(event_data['mc_particles'])} MC particles)")

    print(f"\nDone. {converted} event(s) written to {output_dir}")


if __name__ == "__main__":
    main()
