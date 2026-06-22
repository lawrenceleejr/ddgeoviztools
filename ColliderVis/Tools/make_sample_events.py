#!/usr/bin/env python3
"""
make_sample_events.py — Generate representative muon-collider sample events.

Produces hand-authored event_NNNN.json files matching the schema emitted by
edm4hep_to_json.py, sized to the MAIA detector geometry that ships in this
project (dimensions read from ue5_meshes/*.glb, all in mm):

    beam axis ........ Y  (nozzles span |Y| up to ~5950 mm)
    transverse plane . X-Z (tracks curve here in the solenoid field)
    Vertex detector .. r ~ 115 mm
    Inner trackers ... r ~ 573 mm,  |Y| < 2306 mm
    Outer trackers ... r ~ 1500 mm
    Solenoid ......... r ~ 1857 mm  (B ~ 5 T along +Y)
    ECal barrel ...... r ~ 2200 mm  (inner face -> ECalBarrelHits)
    HCal barrel ...... r ~ 2600-4200 mm (HCalBarrelHits)
    Yoke / muon ...... r ~ 5650 mm  (MuonHits)

These are *illustrative* events for the event-display animation, not a real
physics simulation: tracks are helices in the X-Z plane with pitch along Y,
calo hits are placed where the extrapolated particle crosses each calorimeter
shell, and muon hits are placed at the yoke radius. Charged tracks curve;
neutrals (photons) go straight and only deposit in the calorimeters.

Usage:
    python make_sample_events.py [output_dir]
Default output_dir: Content/Events/Samples (created if missing).
"""

import json
import math
import os
import random
import sys

# --- MAIA geometry (mm) -----------------------------------------------------
# Values from the official MAIA_v0 compact XML (key4hep/k4geo), cross-checked
# against the project's ue5_meshes/*.glb envelopes. NOTE: the official XML uses
# Z as the beam axis, but the Blender->UE export rotates the detector so the
# beam is along Y in this scene; this generator therefore uses Y as the beam
# axis to match the actual geometry the player sees.
R_INNER_TRACK = 580.0      # inner tracker outer radius
R_OUTER_TRACK = 1500.0     # outer tracker outer radius (tracks stop ~here)
R_ECAL        = 1857.0     # ECal barrel inner radius
R_HCAL_IN     = 2126.0     # HCal barrel inner radius
R_HCAL_OUT    = 4113.0     # HCal barrel outer radius
R_YOKE        = 5000.0     # muon/yoke system (inner 4150, outer 5895)
Y_BARREL_HALF = 2307.0     # barrel half-length along beam (ECal/Solenoid)
Y_ENDCAP      = 2575.0     # ECal endcap |Y|

B_FIELD_T = 5.0            # solenoid field, Tesla (MAIA_v0: 5.0 T inner)

# Track signed-curvature constant: radius_of_curvature[mm] = pT[GeV] / (0.3*B) * 1000
def radius_of_curvature_mm(pt_gev: float) -> float:
    if pt_gev <= 1e-6:
        return 1e12
    return (pt_gev / (0.3 * B_FIELD_T)) * 1000.0


def helix_points(charge, p, theta, phi, r_max_mm, n=40):
    """
    Trace a helix in the X-Z transverse plane with the beam along Y.

    charge : +1 / -1 / 0
    p      : total momentum (GeV)
    theta  : polar angle from +Y beam axis (rad)
    phi    : azimuth in X-Z plane (rad)
    Returns a list of [x,y,z] points (mm) from the origin outward until the
    track reaches transverse radius r_max_mm (or escapes the barrel in Y).
    """
    pt = p * math.sin(theta)          # transverse momentum (curves)
    py = p * math.cos(theta)          # along beam (straight)

    pts = []
    if abs(charge) < 1e-6 or pt < 1e-6:
        # Neutral or no transverse momentum: straight line.
        dirx, diry, dirz = math.sin(theta) * math.cos(phi), math.cos(theta), math.sin(theta) * math.sin(phi)
        for i in range(n + 1):
            s = (r_max_mm / max(math.sin(theta), 1e-3)) * i / n
            x, y, z = dirx * s, diry * s, dirz * s
            pts.append([round(x, 2), round(y, 2), round(z, 2)])
            if math.hypot(x, z) >= r_max_mm or abs(y) >= Y_ENDCAP:
                break
        return pts

    R = radius_of_curvature_mm(pt)        # curvature radius in X-Z
    sgn = 1.0 if charge > 0 else -1.0
    # Center of the circle, perpendicular to initial transverse direction.
    cx = -sgn * R * math.sin(phi)
    cz =  sgn * R * math.cos(phi)
    # Arc length step; advance the turning angle until radius_max reached.
    # vy/vt ratio gives Y advance per transverse arc length.
    vy_over_vt = py / pt if pt > 1e-6 else 0.0
    max_arc = math.pi * R          # at most half a turn before we bail
    for i in range(n + 1):
        arc = max_arc * i / n
        ang = arc / R              # turning angle
        # position on circle starting at origin
        x = cx + (0 - cx) * math.cos(ang) - (0 - cz) * math.sin(ang) * sgn
        z = cz + (0 - cx) * math.sin(ang) * sgn + (0 - cz) * math.cos(ang)
        y = vy_over_vt * arc
        pts.append([round(x, 2), round(y, 2), round(z, 2)])
        if math.hypot(x, z) >= r_max_mm or abs(y) >= Y_ENDCAP:
            break
    return pts


def track_exit_point(points):
    return points[-1] if points else [0.0, 0.0, 0.0]


def calo_shower(center_xyz, energy, collection, spread_mm, n_cells):
    """Scatter n_cells calo hits around a shower center, energy split with depth."""
    hits = []
    cx, cy, cz = center_xyz
    for _ in range(n_cells):
        hx = cx + random.gauss(0, spread_mm)
        hy = cy + random.gauss(0, spread_mm)
        hz = cz + random.gauss(0, spread_mm)
        e = abs(energy / n_cells * random.uniform(0.3, 1.7))
        hits.append({
            "collection": collection,
            "position": [round(hx, 2), round(hy, 2), round(hz, 2)],
            "energy_gev": round(e, 5),
        })
    return hits


def project_to_radius(theta, phi, r):
    """Straight-line point at transverse radius r (for neutral calo deposits)."""
    st = max(math.sin(theta), 1e-3)
    s = r / st
    return [round(math.sin(theta) * math.cos(phi) * s, 2),
            round(math.cos(theta) * s, 2),
            round(math.sin(theta) * math.sin(phi) * s, 2)]


def make_charged_track(charge, p, theta, phi, pdg):
    pts = helix_points(charge, p, theta, phi, R_OUTER_TRACK, n=48)
    return {
        "points": pts,
        "charge": float(charge),
        "momentum_gev": round(p, 3),
        "pdg": pdg,
    }, pts


# --- Event templates --------------------------------------------------------

def event_dijet(evno):
    """Two back-to-back hadronic jets — many curved tracks + calo showers."""
    random.seed(1000 + evno)
    tracks, calo, mc = [], [], []
    for jet in range(2):
        jphi = random.uniform(0, 2 * math.pi) + jet * math.pi
        jtheta = random.uniform(math.radians(50), math.radians(130))
        n_ch = random.randint(6, 11)
        for _ in range(n_ch):
            charge = random.choice([+1, -1])
            p = abs(random.gauss(8, 5)) + 0.5
            th = jtheta + random.gauss(0, 0.12)
            ph = jphi + random.gauss(0, 0.12)
            pdg = 211 * (1 if charge > 0 else -1)
            trk, pts = make_charged_track(charge, p, th, ph, pdg)
            tracks.append(trk)
            # ECal + HCal deposit near the track's outward direction
            ec = project_to_radius(th, ph, R_ECAL)
            calo += calo_shower(ec, p * 0.35, "ECalBarrelHits", 60, 5)
            hc = project_to_radius(th, ph, (R_HCAL_IN + R_HCAL_OUT) / 2)
            calo += calo_shower(hc, p * 0.55, "HCalBarrelHits", 110, 6)
        # a few neutral hadrons / photons -> calo only
        for _ in range(random.randint(3, 6)):
            p = abs(random.gauss(4, 3)) + 0.3
            th = jtheta + random.gauss(0, 0.15)
            ph = jphi + random.gauss(0, 0.15)
            ec = project_to_radius(th, ph, R_ECAL)
            calo += calo_shower(ec, p, "ECalBarrelHits", 70, 6)
    return tracks, calo, mc


def event_dimuon(evno):
    """Z/H -> mu+ mu-: two clean high-pT muons reaching the yoke."""
    random.seed(2000 + evno)
    tracks, calo, mc = [], [], []
    phi = random.uniform(0, 2 * math.pi)
    theta = random.uniform(math.radians(60), math.radians(120))
    p = random.uniform(40, 80)
    for charge, dphi in [(+1, 0.0), (-1, math.pi)]:
        trk, pts = make_charged_track(charge, p, math.pi - theta if dphi else theta,
                                      phi + dphi, 13 * (-1 if charge > 0 else 1))
        tracks.append(trk)
        th = (math.pi - theta) if dphi else theta
        ph = phi + dphi
        # minimum-ionizing deposits: small ECal/HCal + muon-system hit at yoke
        calo += calo_shower(project_to_radius(th, ph, R_ECAL), 0.4, "ECalBarrelHits", 40, 2)
        calo += calo_shower(project_to_radius(th, ph, (R_HCAL_IN + R_HCAL_OUT) / 2),
                            1.0, "HCalBarrelHits", 80, 3)
        calo += calo_shower(project_to_radius(th, ph, R_YOKE), 0.6, "MuonHits", 120, 4)
    return tracks, calo, mc


def event_higgs_bb(evno):
    """H -> b bbar: two displaced-ish jets, dense tracks + heavy calo activity."""
    tracks, calo, mc = event_dijet(evno)
    random.seed(3000 + evno)
    # add extra soft tracks for richness
    for _ in range(random.randint(4, 8)):
        charge = random.choice([+1, -1])
        p = abs(random.gauss(3, 2)) + 0.4
        th = random.uniform(math.radians(40), math.radians(140))
        ph = random.uniform(0, 2 * math.pi)
        trk, _ = make_charged_track(charge, p, th, ph, 211 * (1 if charge > 0 else -1))
        tracks.append(trk)
    return tracks, calo, mc


def event_diphoton(evno):
    """H -> gamma gamma: two straight neutral EM showers, no tracks."""
    random.seed(4000 + evno)
    tracks, calo, mc = [], [], []
    phi = random.uniform(0, 2 * math.pi)
    theta = random.uniform(math.radians(60), math.radians(120))
    for dphi in (0.0, math.pi):
        th = (math.pi - theta) if dphi else theta
        ph = phi + dphi
        e = random.uniform(40, 70)
        calo += calo_shower(project_to_radius(th, ph, R_ECAL + 100), e, "ECalBarrelHits", 90, 14)
    return tracks, calo, mc


def event_busy_bib(evno):
    """Muon-collider beam-induced-background flavour: a busy event with a hard
    core dijet plus lots of low-energy forward hits near the nozzles."""
    tracks, calo, mc = event_dijet(evno)
    random.seed(5000 + evno)
    # forward low-energy junk near the nozzle cones (small theta, high |Y|)
    for _ in range(60):
        fwd = random.choice([+1, -1])
        th = random.uniform(math.radians(8), math.radians(30))
        if fwd < 0:
            th = math.pi - th
        ph = random.uniform(0, 2 * math.pi)
        r = random.uniform(R_ECAL, R_HCAL_OUT)
        calo += calo_shower(project_to_radius(th, ph, r),
                            random.uniform(0.01, 0.2), "ECalEndcapHits", 50, 1)
    return tracks, calo, mc


TEMPLATES = [
    ("dijet",       event_dijet),
    ("dimuon",      event_dimuon),
    ("higgs_bb",    event_higgs_bb),
    ("diphoton",    event_diphoton),
    ("busy_bib",    event_busy_bib),
]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    proj = os.path.dirname(here)
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(proj, "Content", "Events", "Samples")
    os.makedirs(out_dir, exist_ok=True)

    idx = 0
    for name, fn in TEMPLATES:
        tracks, calo, mc = fn(idx)
        event = {
            "event_number": idx,
            "run_number": 1,
            "_label": name,
            "tracks": tracks,
            "calo_hits": calo,
            "mc_particles": mc,
        }
        path = os.path.join(out_dir, f"event_{idx:04d}.json")
        with open(path, "w") as fp:
            json.dump(event, fp, indent=2)
        print(f"  event_{idx:04d}.json  [{name}]  "
              f"{len(tracks)} tracks, {len(calo)} calo hits")
        idx += 1

    print(f"\nWrote {idx} sample events to {out_dir}")


if __name__ == "__main__":
    main()
