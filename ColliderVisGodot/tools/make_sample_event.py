#!/usr/bin/env python3
"""
make_sample_event.py — generate physically-plausible sample collision events
in the same JSON schema as ColliderVis/Tools/edm4hep_to_json.py, so the
event display works out of the box without a ROOT file.

Charged tracks are helices in a 3.5 T solenoid field (B along Z, the beam
axis); calorimeter hits are sprayed where tracks/jets reach the ECal/HCal
radii; a few neutral MC truth lines go straight out from the IP.

Usage:
    python3 make_sample_event.py [output_dir] [--events N] [--seed S]
"""

import argparse
import json
import math
import random
from pathlib import Path

B_TESLA = 3.5
ECAL_R_MM = (1700.0, 2150.0)    # barrel ECal radial extent
HCAL_R_MM = (2500.0, 4150.0)    # barrel HCal radial extent
TRACKER_MAX_R_MM = 1690.0       # stop tracks at the ECal face
TRACKER_MAX_Z_MM = 2250.0


def helix_points(pt_gev, phi0, eta, charge, step_mm=60.0):
    """March a helix from the IP until it exits the tracker volume."""
    radius_mm = pt_gev / (0.3 * B_TESLA) * 1000.0   # R[m] = pT / (0.3 B)
    tan_lambda = math.sinh(eta)                      # dz/ds_transverse
    x = y = z = 0.0
    theta = phi0
    pts = [[0.0, 0.0, 0.0]]
    for _ in range(2000):
        x += step_mm * math.cos(theta)
        y += step_mm * math.sin(theta)
        z += step_mm * tan_lambda
        theta -= charge * step_mm / radius_mm
        pts.append([round(x, 1), round(y, 1), round(z, 1)])
        if math.hypot(x, y) > TRACKER_MAX_R_MM or abs(z) > TRACKER_MAX_Z_MM:
            break
    return pts


def make_event(rng, event_number):
    tracks, calo_hits, mc_particles = [], [], []

    # Two back-to-back "jets" plus soft underlying-event tracks.
    jet_phi = rng.uniform(0, 2 * math.pi)
    jet_eta = rng.uniform(-0.8, 0.8)
    axes = [(jet_phi, jet_eta), (jet_phi + math.pi, -jet_eta)]

    for axis_phi, axis_eta in axes:
        for _ in range(rng.randint(6, 10)):
            pt = max(0.4, rng.expovariate(1 / 8.0))
            phi = rng.gauss(axis_phi, 0.25)
            eta = rng.gauss(axis_eta, 0.25)
            charge = rng.choice([-1.0, 1.0])
            pdg = rng.choice([211, -211, 321, -321, 2212, 11, -11, 13, -13])
            pts = helix_points(pt, phi, eta, charge)
            p_total = pt * math.cosh(eta)
            tracks.append({
                "points": pts,
                "charge": charge,
                "momentum_gev": round(p_total, 3),
                "pdg": pdg,
            })
            # ECal cluster where the track lands.
            end = pts[-1]
            end_phi = math.atan2(end[1], end[0])
            for _ in range(rng.randint(3, 8)):
                r = rng.uniform(*ECAL_R_MM)
                cp = rng.gauss(end_phi, 0.05)
                cz = rng.gauss(end[2] * (r / max(math.hypot(end[0], end[1]), 1.0)), 80.0)
                calo_hits.append({
                    "collection": "ECalBarrelHits",
                    "position": [round(r * math.cos(cp), 1),
                                 round(r * math.sin(cp), 1),
                                 round(cz, 1)],
                    "energy_gev": round(max(0.002, rng.expovariate(1 / (pt / 6))), 5),
                })
            # Hadrons shower on into the HCal.
            if abs(pdg) in (211, 321, 2212):
                for _ in range(rng.randint(4, 10)):
                    r = rng.uniform(*HCAL_R_MM)
                    cp = rng.gauss(end_phi, 0.09)
                    cz = rng.gauss(end[2] * (r / max(math.hypot(end[0], end[1]), 1.0)), 200.0)
                    calo_hits.append({
                        "collection": "HCalBarrelHits",
                        "position": [round(r * math.cos(cp), 1),
                                     round(r * math.sin(cp), 1),
                                     round(cz, 1)],
                        "energy_gev": round(max(0.002, rng.expovariate(1 / (pt / 4))), 5),
                    })

    # Soft underlying event.
    for _ in range(rng.randint(8, 14)):
        pt = max(0.3, rng.expovariate(1 / 1.2))
        tracks.append({
            "points": helix_points(pt, rng.uniform(0, 2 * math.pi),
                                   rng.uniform(-1.5, 1.5),
                                   rng.choice([-1.0, 1.0])),
            "charge": rng.choice([-1.0, 1.0]),
            "momentum_gev": round(pt * 1.5, 3),
            "pdg": rng.choice([211, -211]),
        })

    # Neutral MC truth lines (photons / neutrons) straight to the ECal.
    for _ in range(rng.randint(4, 8)):
        phi = rng.gauss(rng.choice(axes)[0], 0.4)
        eta = rng.uniform(-1.2, 1.2)
        r = ECAL_R_MM[0]
        end = [r * math.cos(phi), r * math.sin(phi), r * math.sinh(eta)]
        p = max(0.5, rng.expovariate(1 / 5.0))
        mc_particles.append({
            "vertex": [0.0, 0.0, 0.0],
            "end_vertex": [round(v, 1) for v in end],
            "momentum_gev": [round(p * math.cos(phi), 3),
                             round(p * math.sin(phi), 3),
                             round(p * math.sinh(eta), 3)],
            "pdg": rng.choice([22, 22, 2112, 130]),
            "charge": 0.0,
            "status": 1,
        })

    return {
        "event_number": event_number,
        "run_number": 1,
        "tracks": tracks,
        "calo_hits": calo_hits,
        "mc_particles": mc_particles,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output_dir", nargs="?", default=str(Path(__file__).parent.parent / "events"))
    ap.add_argument("--events", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20260611)
    args = ap.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    for i in range(args.events):
        ev = make_event(rng, i)
        path = out / f"event_{i:04d}.json"
        path.write_text(json.dumps(ev) + "\n")
        print(f"wrote {path}  ({len(ev['tracks'])} tracks, "
              f"{len(ev['calo_hits'])} calo hits, {len(ev['mc_particles'])} MC)")


if __name__ == "__main__":
    main()
