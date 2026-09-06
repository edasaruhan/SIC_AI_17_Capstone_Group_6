"""Load and join TÜİK ADNKS mahalle population tables."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TUIK_DIR = ROOT / "data" / "raw" / "tuik"
TEMPLATE_PATH = TUIK_DIR / "cankaya_mahalle_nufus.template.csv"
TABLE_CANDIDATES = [
    TUIK_DIR / "cankaya_mahalle_nufus.csv",
    TUIK_DIR / "cankaya_mahalle_nufus.xlsx",
]

# ADNKS year-end 2025 district total (public bulletin figure). Used only as
# a uniform-density fallback when no mahalle table is present.
CANKAYA_POP_TOTAL = 952_198

COLUMN_ALIASES = {
    "mahalle": "mahalle_name",
    "mahalle_adi": "mahalle_name",
    "mahalle adı": "mahalle_name",
    "mahalle_adı": "mahalle_name",
    "yerlesim": "mahalle_name",
    "yerleşim": "mahalle_name",
    "yerleşim yeri": "mahalle_name",
    "yerlesim yeri": "mahalle_name",
    "nufus": "pop_total",
    "nüfus": "pop_total",
    "toplam": "pop_total",
    "toplam_nufus": "pop_total",
    "toplam nüfus": "pop_total",
    "toplam_nüfus": "pop_total",
    "pop_total": "pop_total",
    "pop_15_34": "pop_15_34",
    "nufus_15_34": "pop_15_34",
    "nüfus_15_34": "pop_15_34",
    "genç_nüfus": "pop_15_34",
    "genc_nufus": "pop_15_34",
    "15-34": "pop_15_34",
    "15_34": "pop_15_34",
}


def normalize_mahalle_name(name: object) -> str:
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    text = str(name).strip().lower()
    text = (
        text.replace("ç", "c")
        .replace("ğ", "g")
        .replace("ı", "i")
        .replace("ö", "o")
        .replace("ş", "s")
        .replace("ü", "u")
        .replace("â", "a")
        .replace("î", "i")
        .replace("û", "u")
    )
    for token in ("mahallesi", "mahallsi", "mahalle", "mah.", "mah"):
        text = text.replace(token, " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in COLUMN_ALIASES:
            mapping[col] = COLUMN_ALIASES[key]
    return df.rename(columns=mapping)


def find_tuik_table() -> Path | None:
    for path in TABLE_CANDIDATES:
        if path.exists():
            return path
    return None


def load_tuik_mahalle_table(path: Path | None = None) -> pd.DataFrame | None:
    path = path or find_tuik_table()
    if path is None:
        return None
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path, encoding="utf-8-sig")
    df = _rename_columns(df)
    if "mahalle_name" not in df.columns:
        raise ValueError(
            f"{path.name} needs a mahalle name column "
            "(mahalle_name / mahalle / mahalle_adi)."
        )
    if "pop_total" not in df.columns:
        raise ValueError(f"{path.name} needs a pop_total / nufus column.")
    out = df.copy()
    out["mahalle_key"] = out["mahalle_name"].map(normalize_mahalle_name)
    out["pop_total"] = pd.to_numeric(out["pop_total"], errors="coerce")
    if "pop_15_34" in out.columns:
        out["pop_15_34"] = pd.to_numeric(out["pop_15_34"], errors="coerce")
    else:
        out["pop_15_34"] = pd.NA
    out = out.loc[out["mahalle_key"].ne("") & out["pop_total"].notna()].copy()
    return out[["mahalle_name", "mahalle_key", "pop_total", "pop_15_34"]]


def write_template(mahalle_names: list[str]) -> Path:
    TUIK_DIR.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "mahalle_name": mahalle_names,
            "pop_total": pd.NA,
            "pop_15_34": pd.NA,
            "year": 2025,
            "source": "TUIK ADNKS",
        }
    )
    frame.to_csv(TEMPLATE_PATH, index=False, encoding="utf-8-sig")
    return TEMPLATE_PATH
