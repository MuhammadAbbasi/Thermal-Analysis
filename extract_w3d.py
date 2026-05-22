"""
Parse the W3D binary and content XMLs to extract:
 - Geometry / vertex coordinates (in CAD model space, likely ETRF2000-UTM-F33)
 - Text label positions (ITS zone names, string numbers)
 - Build a plant_layout.json with ITS zones, string catalog, and coordinate data

W3D is Autodesk's Whip!3D streaming format used in DWF eModel sections.
We scan for recognisable opcodes / ASCII text blocks to recover coordinates
and string labels without a full W3D SDK.
"""
import struct, re, os, json, math

BASE      = os.path.dirname(os.path.abspath(__file__))
EXTRACTED = os.path.join(BASE, "dwf_extracted")
W3D_PATH  = os.path.join(EXTRACTED,
    "com.autodesk.dwf.eModel_84DD3338-90B4-4BDF-9A8D-0BB917A43AAF",
    "11DBAE77-850E-41E8-9694-004627674CDF.w3d")
PRESENT_XML = os.path.join(EXTRACTED,
    "com.autodesk.dwf.eModel_84DD3338-90B4-4BDF-9A8D-0BB917A43AAF",
    "11DBAE79-850E-41E8-9694-004627674CDF.xml")
CONTENT_XML = os.path.join(EXTRACTED,
    "74DE711B-0FE7-4CD4-BD01-6F3A749DE249.content.xml")

print(f"W3D size: {os.path.getsize(W3D_PATH):,} bytes")

data = open(W3D_PATH, "rb").read()

# ── 1. Find embedded ASCII text strings (ITS/string labels) ──────────────────
print("\n=== Embedded text strings in W3D ===")
text_re = re.compile(rb'(ITS\s*\d{1,2}[^\x00-\x1f]{0,60})', re.IGNORECASE)
found_texts = text_re.findall(data)
seen_t = set()
for t in found_texts:
    try:
        s = t.decode("ascii", errors="replace").strip()
        if s not in seen_t:
            seen_t.add(s)
            print(" ", s[:80])
    except:
        pass

# ── 2. Scan for W3D opcodes to find coordinate data ──────────────────────────
# W3D uses a tagged streaming format.
# Key opcodes: 0x0C (Segment) 0x08 (Transform/Matrix) 0x04 (Shell/Mesh)
# We look for 4x4 float matrices (64 bytes) as transformation nodes
# that give us the UTM position of each ITS block.
print("\n=== Scanning for 4x4 float matrices (object transforms) ===")
transforms = []
# Scan for patterns of 16 consecutive IEEE-754 floats that look like
# a valid 4x4 homogeneous matrix: last row ≈ [0,0,0,1]
stride = 4  # try every 4 bytes
for i in range(0, len(data) - 64, stride):
    chunk = data[i:i+64]
    try:
        vals = struct.unpack('<16f', chunk)
        # Last row of column-major 4x4 matrix should be [0,0,0,1]
        if abs(vals[12]) < 1e-6 and abs(vals[13]) < 1e-6 and abs(vals[14]) < 1e-6 \
                and abs(vals[15] - 1.0) < 1e-4:
            # Translation vector is at vals[12..14] in row-major or vals[3,7,11] in col-major
            # Try row-major: translation at [12], [13], [14]
            tx, ty, tz = vals[12], vals[13], vals[14]
            # UTM-F33 coords for Sicily are roughly E=250000-600000, N=4000000-4300000
            if 200000 < tx < 700000 and 3900000 < ty < 4400000:
                transforms.append((i, tx, ty, tz, vals))
    except:
        pass

print(f"Found {len(transforms)} UTM-range transforms (row-major)")

# Also try column-major: translation at indices [3],[7],[11]
transforms_col = []
for i in range(0, len(data) - 64, stride):
    chunk = data[i:i+64]
    try:
        vals = struct.unpack('<16f', chunk)
        tx, ty, tz = vals[3], vals[7], vals[11]
        if 200000 < tx < 700000 and 3900000 < ty < 4400000:
            transforms_col.append((i, tx, ty, tz, vals))
    except:
        pass

print(f"Found {len(transforms_col)} UTM-range transforms (column-major)")

# ── 3. Try double-precision (64-bit) matrices ─────────────────────────────────
print("\n=== Scanning for double-precision coordinates ===")
utm_doubles = []
for i in range(0, len(data) - 16, 8):
    chunk = data[i:i+16]
    try:
        x, y = struct.unpack('<2d', chunk)
        if 200000 < x < 700000 and 3900000 < y < 4400000:
            utm_doubles.append((i, x, y))
    except:
        pass

print(f"Found {len(utm_doubles)} double-precision UTM coordinate pairs")
if utm_doubles:
    xs = [v[1] for v in utm_doubles]
    ys = [v[2] for v in utm_doubles]
    print(f"  X range: {min(xs):.1f} – {max(xs):.1f}")
    print(f"  Y range: {min(ys):.1f} – {max(ys):.1f}")
    print(f"  Centroid: {sum(xs)/len(xs):.1f}, {sum(ys)/len(ys):.1f}")
    print(f"  First 20 pairs:")
    for i, x, y in utm_doubles[:20]:
        print(f"    offset={i:8d}  E={x:.2f}  N={y:.2f}")

# ── 4. Try scanning for float coordinate pairs ────────────────────────────────
print("\n=== Scanning for float-precision coordinate pairs ===")
utm_floats = []
for i in range(0, len(data) - 8, 4):
    chunk = data[i:i+8]
    try:
        x, y = struct.unpack('<2f', chunk)
        if 200000 < x < 700000 and 3900000 < y < 4400000:
            utm_floats.append((i, x, y))
    except:
        pass

print(f"Found {len(utm_floats)} float-precision UTM coordinate pairs")
if utm_floats:
    xs = [v[1] for v in utm_floats]
    ys = [v[2] for v in utm_floats]
    print(f"  X range: {min(xs):.1f} – {max(xs):.1f}")
    print(f"  Y range: {min(ys):.1f} – {max(ys):.1f}")

# ── 5. Read Testo entities from content.xml for text values ──────────────────
print("\n=== Testo entities (18) from content.xml ===")
with open(CONTENT_XML, "r", encoding="utf-8", errors="replace") as f:
    ctext = f.read()

# Find Testo entities (not Testom)
testo_blocks = re.findall(
    r'<dwf:Entity id="([^"]+)"(.*?)</dwf:Entity>',
    ctext, re.DOTALL
)
for eid, body in testo_blocks:
    nc = re.search(r'name="Nome classe" value="([^"]+)"', body)
    if nc and nc.group(1) == "Testo":
        props = re.findall(r'name="([^"]+)" value="([^"]+)"', body)
        print(f"\n  Entity {eid}:")
        for k, v in props:
            print(f"    {k}: {v}")

# ── 6. Parse scene graph from presentation XML for ITS node hierarchy ─────────
print("\n=== ITS zone hierarchy from presentation XML ===")
with open(PRESENT_XML, "r", encoding="utf-8", errors="replace") as f:
    ptext = f.read()

# Find ITS top-level nodes and count their children
its_pattern = re.compile(
    r'<ReferenceNode[^>]*label="(ITS \d+)[^"]*"[^>]*>(.*?)</ReferenceNode>',
    re.DOTALL
)
its_zones = {}
for m in its_pattern.finditer(ptext):
    name  = m.group(1)
    inner = m.group(2)
    # Count sub-nodes
    children = re.findall(r'<ReferenceNode', inner)
    child_labels = re.findall(r'label="([^"]+)"', inner)
    tratteggio = sum(1 for l in child_labels if "Tratteggio" in l)
    other = [l for l in child_labels if "Tratteggio" not in l]
    its_zones[name] = {
        "total_children": len(children),
        "hatch_panels": tratteggio,
        "other_labels": other[:10],
    }
    print(f"  {name}: {tratteggio} hatch panels, other={other[:5]}")

# ── 7. Build the plant metadata catalog ──────────────────────────────────────
# Parse structure labels: _Strutture ITSx 2pNN (count)
struct_re = re.compile(r"_Strutture (ITS\d+)\s+(2p\d+)\s+\((\d+)\)")
structs = {}
all_labels_list = re.findall(r'label="([^"]+)"', ptext)
for lbl in all_labels_list:
    m = struct_re.match(lbl)
    if m:
        its, config, cnt = m.group(1), m.group(2), int(m.group(3))
        if its not in structs:
            structs[its] = {}
        structs[its][config] = structs[its].get(config, 0) + cnt

# Panel counts per ITS (modules per table: 2p24=48, 2p36=72, 2p48=96)
MODULES = {"2p24": 48, "2p36": 72, "2p48": 96}
print("\n=== Panel module counts per ITS zone ===")
its_catalog = {}
for its in sorted(structs, key=lambda x: int(re.search(r'\d+', x).group())):
    total_modules = 0
    cfg_detail = {}
    for cfg, cnt in structs[its].items():
        mods = cnt * MODULES.get(cfg, 0)
        total_modules += mods
        cfg_detail[cfg] = {"tables": cnt, "modules": mods}
    its_catalog[its] = {
        "structures": cfg_detail,
        "total_modules": total_modules,
    }
    print(f"  {its}: {total_modules} modules — {structs[its]}")

# Save
out = {
    "plant_name": "24S002_2E400 - Layout stringhe REV03 per thermografia",
    "coordinate_system": "ETRF2000-UTM-F33",
    "inverter_zones": [
        {"name": f"ITS {i}", "id": f"ITS{i}"} for i in range(1, 21)
    ],
    "its_catalog": its_catalog,
    "utm_doubles_found": len(utm_doubles),
    "utm_extent": {
        "x_min": min(v[1] for v in utm_doubles) if utm_doubles else None,
        "x_max": max(v[1] for v in utm_doubles) if utm_doubles else None,
        "y_min": min(v[2] for v in utm_doubles) if utm_doubles else None,
        "y_max": max(v[2] for v in utm_doubles) if utm_doubles else None,
    } if utm_doubles else {},
    "total_strings": 1181,
    "total_string_labels": 6415,
}
out_path = os.path.join(BASE, "data", "plant_catalog.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(f"\nSaved to {out_path}")
