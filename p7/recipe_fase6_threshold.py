# Dataiku Python recipe: fase6_threshold (ajuste operativo sin re-entrenar)
# Input (Flow):  managed folder fase5_modelo (lee encoders.json)
# Output (Flow): mismo folder (reescribe encoders.json con threshold 0.75)
# Decision piloto: FP confirmados (c, borrar, concatenada, script, max_importe,
# ctologro, oficina, ctacto, n_txn, flag_cliente_duplicado, tef/area/dir/zona)
# quedan bajo 0.75; TP solidos sobre 0.90. prob_pii es score no calibrado.
import json
import os

import dataiku

NEW_THRESHOLD = 0.75

fdir = dataiku.Folder("fase5_modelo").get_path()
path = os.path.join(fdir, "encoders.json")
with open(path, encoding="utf-8") as f:
    enc = json.load(f)

old = float(enc.get("threshold"))
enc["threshold"] = NEW_THRESHOLD
enc["threshold_previo"] = old
enc["threshold_motivo"] = ("piloto 105 columnas: FP max 0.7322 (n_txn), "
                           "TP min 0.9092 (num_ids_clientes)")
with open(path, "w", encoding="utf-8") as f:
    json.dump(enc, f, ensure_ascii=False)

assert abs(json.load(open(path, encoding="utf-8"))["threshold"]
           - NEW_THRESHOLD) < 1e-9, "threshold no persistio"
print(f"threshold {old} -> {NEW_THRESHOLD} "
      f"(variante={enc.get('variante')}, target={enc.get('target')})")
print("Re-correr fase7_piloto para ver el efecto (sin cambios de codigo).")
