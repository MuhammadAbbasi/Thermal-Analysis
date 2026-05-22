"""
Parse the DWF plant layout file and extract:
- String/inverter names from presentation node labels
- Text entities (Testom) from content.xml
- Try to read geometry coordinates from W3D if possible
Save results to data/plant_layout.json
"""
import re, json, os, struct

BASE = os.path.dirname(os.path.abspath(__file__))
EXTRACTED = os.path.join(BASE, "dwf_extracted")

CONTENT_XML  = os.path.join(EXTRACTED, "74DE711B-0FE7-4CD4-BD01-6F3A749DE249.content.xml")
PRESENT_XML  = os.path.join(EXTRACTED,
    "com.autodesk.dwf.eModel_84DD3338-90B4-4BDF-9A8D-0BB917A43AAF",
    "11DBAE79-850E-41E8-9694-004627674CDF.xml")
CONTENT_DEF  = os.path.join(EXTRACTED,
    "com.autodesk.dwf.eModel_84DD3338-90B4-4BDF-9A8D-0BB917A43AAF",
    "11DBAE78-850E-41E8-9694-004627674CDF.xml")

# ── 1. Presentation XML → all node labels ─────────────────────────────────────
with open(PRESENT_XML, "r", encoding="utf-8", errors="replace") as f:
    ptext = f.read()

all_labels = re.findall(r'label="([^"]+)"', ptext)
print(f"Total node labels in presentation: {len(all_labels)}")

# Filter out hatch/tratteggio and raw ID labels
string_labels = [l for l in all_labels
                 if not l.startswith("Tratteggio")
                 and "[" not in l
                 and l.strip()]

seen = {}
for l in string_labels:
    seen[l] = seen.get(l, 0) + 1

print(f"\nUnique non-hatch labels ({len(seen)}):")
for l, cnt in sorted(seen.items(), key=lambda x: x[0]):
    print(f"  {cnt:3d}x  {l!r}")

# ── 2. Content XML → entities with their class names and properties ────────────
with open(CONTENT_XML, "r", encoding="utf-8", errors="replace") as f:
    ctext = f.read()

# Find all Entity blocks
entity_blocks = re.findall(r'<dwf:Entity id="([^"]+)"(.*?)</dwf:Entity>', ctext, re.DOTALL)
print(f"\nTotal entities: {len(entity_blocks)}")

class_counts = {}
text_entities = []

for eid, body in entity_blocks:
    nome_classe = re.search(r'name="Nome classe" value="([^"]+)"', body)
    obj_id      = re.search(r'name="ObjectId" value="([^"]+)"', body)
    content_val = re.search(r'name="Contenuto" value="([^"]+)"', body)
    text_val    = re.search(r'name="Testo" value="([^"]+)"', body)
    handle_val  = re.search(r'name="Handle" value="([^"]+)"', body)

    cls = nome_classe.group(1) if nome_classe else "?"
    class_counts[cls] = class_counts.get(cls, 0) + 1

    if cls in ("Testom", "Testo", "Annotazione", "Etichetta"):
        txt = (content_val or text_val)
        text_entities.append({
            "id":       eid,
            "class":    cls,
            "object_id": obj_id.group(1) if obj_id else None,
            "handle":   handle_val.group(1) if handle_val else None,
            "text":     txt.group(1) if txt else None,
            "raw_props": body[:400],
        })

print("\nEntity class counts:")
for cls, cnt in sorted(class_counts.items(), key=lambda x: -x[1]):
    print(f"  {cnt:5d}  {cls}")

print(f"\nText entities (Testom etc): {len(text_entities)}")
for te in text_entities[:30]:
    print(f"  {te['class']:12s}  obj={te['object_id']}  text={te['text']!r}")
    # show all props
    props = re.findall(r'name="([^"]+)" value="([^"]+)"', te['raw_props'])
    for p in props:
        print(f"             {p[0]}: {p[1]}")

# ── 3. Content definition XML → check for coordinate data ────────────────────
with open(CONTENT_DEF, "r", encoding="utf-8", errors="replace") as f:
    dtext = f.read()
print(f"\nContent definition XML length: {len(dtext)}")
# Show first 2000 chars
print(dtext[:2000])

# ── 4. Build string catalog ──────────────────────────────────────────────────
# From presentation labels, find patterns like "STR XX", "ITS XX", "INV XX" etc.
string_pattern = re.compile(
    r'((?:STR|ITS|INV|String|Stringa|S)\s*[\d]+(?:\s*[-_/]\s*[\d]+)*)',
    re.IGNORECASE
)

strings_found = {}
for l in seen:
    m = string_pattern.findall(l)
    for match in m:
        strings_found[match] = l

print("\n=== STRING NAMES FOUND ===")
for s, label in sorted(strings_found.items()):
    print(f"  {s!r}  (from label: {label!r})")

out_path = os.path.join(BASE, "data", "plant_strings_raw.json")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
result = {
    "source_file": "24S002_2E400 - Layout stringhe REV03 per thermografia.dwf",
    "all_node_labels": list(seen.keys()),
    "string_names_detected": list(strings_found.keys()),
    "text_entities": text_entities,
    "entity_class_counts": class_counts,
}
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
print(f"\nSaved raw metadata to {out_path}")
