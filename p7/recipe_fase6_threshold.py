# Dataiku Python recipe: fase6_threshold (version operativa sin re-entrenar)
# Input (Flow):  managed folder fase5_modelo (solo lectura)
# Output (Flow): managed folder fase5_modelo_operativo (4 archivos funcionales)
# Copia byte-identica modelo.txt, vec_name.pkl, vec_desc.pkl y reescribe
# encoders.json con threshold 0.75 (decision piloto: FP max 0.7322 = n_txn,
# TP min 0.9092 = num_ids_clientes). metricas.html queda solo en entrenamiento.
import json
import os
import shutil

import dataiku

NEW_THRESHOLD = 0.75
BINARIOS = ["modelo.txt", "vec_name.pkl", "vec_desc.pkl"]

src = dataiku.Folder("fase5_modelo").get_path()
dst = dataiku.Folder("fase5_modelo_operativo").get_path()

for f in BINARIOS:
    shutil.copy(os.path.join(src, f), os.path.join(dst, f))

with open(os.path.join(src, "encoders.json"), encoding="utf-8") as f:
    enc = json.load(f)
old = float(enc.get("threshold"))
enc["threshold"] = NEW_THRESHOLD
enc["threshold_previo"] = old
enc["threshold_motivo"] = ("piloto 105 columnas: FP max 0.7322 (n_txn), "
                           "TP min 0.9092 (num_ids_clientes)")
with open(os.path.join(dst, "encoders.json"), "w", encoding="utf-8") as f:
    json.dump(enc, f, ensure_ascii=False)

# ---- verificacion ----
chk = json.load(open(os.path.join(dst, "encoders.json"), encoding="utf-8"))
assert abs(chk["threshold"] - NEW_THRESHOLD) < 1e-9, "threshold no persistio"
for f in BINARIOS:
    assert (os.path.getsize(os.path.join(src, f))
            == os.path.getsize(os.path.join(dst, f))), f"copia corrupta: {f}"
print(f"operativo listo: threshold {old} -> {NEW_THRESHOLD} "
      f"(variante={chk.get('variante')}, target={chk.get('target')})")
