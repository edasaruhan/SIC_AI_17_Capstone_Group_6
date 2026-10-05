# Café similarity validation

Run date: 2026-10-05. Data: committed `data/processed/cankaya_grid_features.parquet`, 5,361 cells; no OSM refresh performed.

Dataset SHA-256: `09cedbb3347ebf1f27298199c796ae154ba631060a3dd7fb46ef51cc2a0af354`.

Environment: Python 3.12.14, GeoPandas 1.2.0, scikit-learn 1.8.0, NumPy 2.3.5, pandas 2.2.3. RF: 300 trees, max_depth=8, min_samples_leaf=5, class_weight=balanced, random_state=42. StratifiedGroupKFold: 5 folds, shuffle=True, random_state=42, grouped by mahalle_name.

| Fold | Train cells | Test cells | Positive rate | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| 1 | 4262 | 1099 | .141 | .990 |
| 2 | 4318 | 1043 | .171 | .900 |
| 3 | 4306 | 1055 | .159 | .953 |
| 4 | 4275 | 1086 | .142 | .972 |
| 5 | 4283 | 1078 | .150 | .985 |

Mean fold ROC-AUC: **0.960** (mean of the reported three-decimal fold values). The previous README result must not be used as validation of the corrected model.

Corrections: café-free POI diversity is recomputed from source count columns; median imputation uses training-fold data only; displayed scores are out-of-fold probabilities × 100, with no full-data prediction blend. Existing stored similarity columns are legacy outputs; the app recomputes them at runtime. The committed dataset is unchanged.

Full-data Gini importances: café-free POI diversity 23.9%, restaurants 16.9%, shops 16.3%, metro distance 11.6%, parks 9.3%, population density 7.1%, schools 4.8%, population 4.1%, intersections 1.9%, bus stops 1.6%, universities 1.5%, hospitals 0.9% (rounding may affect the sum).

To reproduce without writing the dataset:

```python
import geopandas as gpd
from src.cafe_similarity import train_and_score, feature_importance_table

grid = gpd.read_parquet("data/processed/cankaya_grid_features.parquet")
scored, report = train_and_score(grid)
print(report.to_string(index=False))
print(report.roc_auc.mean())
print(feature_importance_table(train_and_score.feature_importances_))
```

Limitations: OSM completeness and generic-school legacy counts remain relevant. Whole-neighborhood holdouts do not remove shared buffers or spatial dependence across neighborhood borders. ROC-AUC is discrimination against mapped café presence, not calibrated profitability or commercial success. Refreshing data or changing dependency versions requires a new validation run.
