# Dataiku Python recipe: fase0_prepare_catalogs
# Inputs (Flow):  dataset_no_validated_prepared, dataset_validated_prepared
# Outputs (Flow): cat_267k_norm, cat_21k_norm
# Pegar tal cual en el editor de la recipe. Requiere pii_lib/normalize.py en Library Editor.
import dataiku
from pii_lib.normalize import dedup_catalog

d267 = dataiku.Dataset("dataset_no_validated_prepared").get_dataframe()
d21 = dataiku.Dataset("dataset_validated_prepared").get_dataframe()

cat267 = dedup_catalog(d267, col="name", pii_col="pii")
cat21 = dedup_catalog(d21, col="name", pii_col="pii")

dataiku.Dataset("cat_267k_norm").write_with_schema(cat267)
dataiku.Dataset("cat_21k_norm").write_with_schema(cat21)
