import os, re, struct, json, math

BASE    = os.path.dirname(os.path.abspath(__file__))
EMODEL  = os.path.join(BASE, "dwf_extracted",
    "com.autodesk.dwf.eModel_84DD3338-90B4-4BDF-9A8D-0BB917A43AAF")

# ── descriptor.xml ────────────────────────────────────────────────────────────
desc_path = os.path.join(EMODEL, "descriptor.xml")
desc = open(desc_path, "r", encoding="utf-8", errors="replace").read()
print("=== descriptor.xml ===")
print(desc)

# ── Scan W3D for any readable coordinate-like data ────────────────────────────
w3d_path = os.path.join(EMODEL, "11DBAE77-850E-41E8-9694-004627674CDF.w3d")
data = open(w3d_path, "rb").read()

# Check W3D header/magic
print("\n=== W3D header (first 64 bytes hex) ===")
print(data[:64].hex())
print("ASCII:", data[:64].decode("ascii", errors="."))

# Look for any ASCII text blobs with length > 4 chars
print("\n=== ASCII text strings in W3D (len>=5) ===")
matches = re.findall(b'[ -~]{5,}', data)
seen = set()
for m in matches:
    s = m.decode("ascii", errors="replace")
    if s not in seen:
        seen.add(s)
        print(" ", repr(s[:100]))

# Check for any numbers that could be UTM coordinates
# UTM-F33 for Sicily: E ~ 340000-520000, N ~ 4070000-4200000
print("\n=== Float pairs in UTM range for Sicily ===")
found_pairs = []
for i in range(0, len(data) - 8, 4):
    try:
        x, y = struct.unpack_from('<2f', data, i)
        if 300000 < x < 600000 and 4000000 < y < 4300000:
            found_pairs.append((i, x, y))
    except:
        pass
print(f"Float pairs found: {len(found_pairs)}")
if found_pairs:
    for off, x, y in found_pairs[:20]:
        print(f"  offset={off}  E={x:.1f}  N={y:.1f}")

# Also try double
print("\n=== Double pairs in UTM range ===")
found_d = []
for i in range(0, len(data) - 16, 8):
    try:
        x, y = struct.unpack_from('<2d', data, i)
        if 300000 < x < 600000 and 4000000 < y < 4300000:
            found_d.append((i, x, y))
    except:
        pass
print(f"Double pairs found: {len(found_d)}")
if found_d:
    for off, x, y in found_d[:20]:
        print(f"  offset={off}  E={x:.4f}  N={y:.4f}")
