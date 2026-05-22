"""
HSF/W3D geometry extraction:
The W3D file is a HOOPS Stream Format file containing zlib-compressed segments.
We decompress each segment and scan for UTM coordinate data.
"""
import struct, re, os, json, zlib, math

BASE   = os.path.dirname(os.path.abspath(__file__))
EMODEL = os.path.join(BASE, "dwf_extracted",
    "com.autodesk.dwf.eModel_84DD3338-90B4-4BDF-9A8D-0BB917A43AAF")
W3D    = os.path.join(EMODEL, "11DBAE77-850E-41E8-9694-004627674CDF.w3d")

data = open(W3D, "rb").read()
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
print(f"W3D raw size: {len(data):,} bytes")
h = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[:40])
print(f"Header (text): {h}")

# ── Find all zlib streams (magic bytes 78 9c / 78 da / 78 01) ─────────────────
ZLIB_MAGICS = [b'\x78\xda', b'\x78\x9c', b'\x78\x01', b'\x78\x5e']
offsets = []
for magic in ZLIB_MAGICS:
    start = 0
    while True:
        pos = data.find(magic, start)
        if pos < 0:
            break
        offsets.append(pos)
        start = pos + 1

offsets = sorted(set(offsets))
print(f"\nFound {len(offsets)} potential zlib blocks at offsets: {offsets[:20]}")

# ── Decompress each zlib block ────────────────────────────────────────────────
decompressed_all = b""
block_info = []

for off in offsets:
    for size in range(len(data) - off, 0, -1024):
        try:
            dec = zlib.decompress(data[off:off+size])
            block_info.append((off, size, len(dec)))
            decompressed_all += dec
            print(f"  Block at {off}: compressed={size:,}  decompressed={len(dec):,}")
            break
        except Exception:
            if size < 1024:
                break
            continue

print(f"\nTotal decompressed: {len(decompressed_all):,} bytes")

if not decompressed_all:
    # Try whole-file decompress from first zlib magic
    for off in offsets:
        try:
            dec = zlib.decompress(data[off:])
            decompressed_all = dec
            print(f"Full decompression from offset {off}: {len(dec):,} bytes")
            break
        except:
            pass

if not decompressed_all:
    print("Could not decompress — trying zlib.decompressobj with wbits=-15 (raw deflate)")
    for off in offsets:
        try:
            dec = zlib.decompress(data[off:], wbits=-15)
            decompressed_all = dec
            print(f"Raw deflate from {off}: {len(dec):,} bytes")
            break
        except:
            pass

# ── Scan decompressed data for UTM coords (Sicily: E=340-520k, N=4070-4200k) ─
def scan_floats(buf, label):
    pairs = []
    for i in range(0, len(buf) - 8, 4):
        try:
            x, y = struct.unpack_from('<2f', buf, i)
            if 300000 < x < 600000 and 4000000 < y < 4300000:
                pairs.append((i, x, y))
        except:
            pass
    print(f"\n[{label}] Float UTM pairs: {len(pairs)}")
    if pairs:
        xs = [p[1] for p in pairs]; ys = [p[2] for p in pairs]
        print(f"  E: {min(xs):.1f} – {max(xs):.1f}")
        print(f"  N: {min(ys):.1f} – {max(ys):.1f}")
        for p in pairs[:10]:
            print(f"    off={p[0]}  E={p[1]:.1f}  N={p[2]:.1f}")
    return pairs

def scan_doubles(buf, label):
    pairs = []
    for i in range(0, len(buf) - 16, 8):
        try:
            x, y = struct.unpack_from('<2d', buf, i)
            if 300000 < x < 600000 and 4000000 < y < 4300000:
                pairs.append((i, x, y))
        except:
            pass
    print(f"\n[{label}] Double UTM pairs: {len(pairs)}")
    if pairs:
        xs = [p[1] for p in pairs]; ys = [p[2] for p in pairs]
        print(f"  E: {min(xs):.4f} – {max(xs):.4f}")
        print(f"  N: {min(ys):.4f} – {max(ys):.4f}")
        for p in pairs[:10]:
            print(f"    off={p[0]}  E={p[1]:.4f}  N={p[2]:.4f}")
    return pairs

raw_f  = scan_floats(data,             "raw W3D")
raw_d  = scan_doubles(data,            "raw W3D")
dec_f  = scan_floats(decompressed_all, "decompressed") if decompressed_all else []
dec_d  = scan_doubles(decompressed_all,"decompressed") if decompressed_all else []

# ── ASCII strings in decompressed data ───────────────────────────────────────
if decompressed_all:
    print("\n=== ASCII strings in decompressed data ===")
    strs = re.findall(b'[ -~]{5,}', decompressed_all)
    seen = set()
    for s in strs:
        t = s.decode("ascii", errors="replace")
        if t not in seen:
            seen.add(t)
            print(" ", repr(t[:120]))
        if len(seen) > 60:
            break

# ── Try HSF text opcode parsing ───────────────────────────────────────────────
# In HSF, text is stored as: opcode 0x28 (Text), followed by length byte,
# then UTF-8 string. Let's look for this in decompressed.
if decompressed_all:
    print("\n=== Searching decompressed for 'ITS' pattern ===")
    idx = 0
    while True:
        pos = decompressed_all.find(b'ITS', idx)
        if pos < 0:
            break
        ctx = decompressed_all[max(0,pos-10):pos+30]
        print(f"  at {pos}: {ctx.hex()} | {ctx.decode('ascii', errors='.')}")
        idx = pos + 1

print("\nDone.")
