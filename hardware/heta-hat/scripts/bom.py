"""Erzeugt eine gruppierte Stückliste (CSV) aus der KiCad-Netzliste (kicadsexpr)."""

import csv
import re
import sys
from collections import OrderedDict

net_file, out_file = sys.argv[1], sys.argv[2]
text = open(net_file, encoding="utf-8").read()

groups = OrderedDict()
for m in re.finditer(r'\(comp \(ref "([^"]+)"\)(.*?)\(tstamps "[^"]+"\)\)', text, re.S):
    ref, body = m.group(1), m.group(2)
    fp = re.search(r'\(footprint "([^"]*)"\)', body)
    if ref.startswith("#") or not fp or fp.group(1).startswith("MountingHole"):
        continue
    value = re.search(r'\(value "([^"]*)"\)', body).group(1)
    fields = dict(re.findall(r'\(field \(name "([^"]+)"\) "([^"]*)"\)', body))
    key = (value, fp.group(1), fields.get("MPN", ""))
    g = groups.setdefault(key, {"refs": [], "info": []})
    g["refs"].append(ref)
    g["info"].append((ref, "; ".join(fields[k] for k in ("Funktion", "Spezifikation", "Pinbelegung") if fields.get(k))))


def ref_key(r):
    m = re.match(r"([A-Za-z]+)(\d+)", r)
    return (m.group(1), int(m.group(2))) if m else (r, 0)


with open(out_file, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["Pos", "Menge", "Referenzen", "Wert", "Footprint", "MPN / Vorschlag", "Funktion / Spezifikation"])
    rows = sorted(groups.items(), key=lambda kv: ref_key(sorted(kv[1]["refs"], key=ref_key)[0]))
    for i, ((value, fp, mpn), g) in enumerate(rows, 1):
        refs = sorted(g["refs"], key=ref_key)
        texts = {t for _, t in g["info"]}
        if len(texts) == 1:
            info = texts.pop()
        else:  # nur einzelne Bauteile der Gruppe tragen einen Hinweis
            info = " | ".join(f"{r}: {t}" for r, t in sorted(g["info"], key=lambda x: ref_key(x[0])) if t)
        w.writerow([i, len(refs), ", ".join(refs), value, fp.split(":")[1], mpn, info])
print(f"{len(groups)} Positionen -> {out_file}")
