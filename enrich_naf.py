"""
Enrichissement d'un fichier CSV ou Excel avec le code NAF.
- Filtre uniquement les lignes Pays = FRA
- Utilise N°SIREN/SIRET en priorité, TVA Intracom en fallback
- Remplit la colonne Code NAF existante
- Ajoute la colonne Libellé NAF
- Sauvegarde un fichier _enrichi (même format)

Usage :
    python enrich_naf.py mon_fichier.csv
    python enrich_naf.py mon_fichier.xlsx
"""

import sys
import time
import argparse
import requests
import pandas as pd
from pathlib import Path


API_URL = "https://recherche-entreprises.api.gouv.fr/search"
PAUSE = 0.3


# Helpers

def tva_to_siren(tva: str) -> str | None:
    if not isinstance(tva, str):
        return None
    tva = tva.strip().upper().replace(" ", "").replace(".", "")
    if tva.startswith("FR") and len(tva) == 13:
        return tva[4:]
    return None


def clean_siret(val) -> str | None:
    if not isinstance(val, str):
        val = str(val) if pd.notna(val) else ""
    val = val.strip().replace(" ", "").replace("-", "").replace(".", "")
    if "E" in val.upper():
        try:
            val = str(int(float(val)))
        except ValueError:
            pass
    return val if val.isdigit() and len(val) in (9, 14) else None


def call_api(query: str) -> dict | None:
    try:
        r = requests.get(API_URL, params={"q": query, "page": 1, "per_page": 1}, timeout=10)
        r.raise_for_status()
        results = r.json().get("results", [])
        return results[0] if results else None
    except Exception as e:
        print(f"  [ERREUR API] {query} -> {e}")
        return None


def get_naf(identifiant: str) -> tuple[str, str]:
    data = call_api(identifiant)
    if not data:
        return "NON TROUVÉ", ""
    return data.get("activite_principale", "N/A"), data.get("libelle_activite_principale", "")


# Lecture avec détection automatique de l'encodage

def read_file(path: Path):
    if path.suffix.lower() == ".csv":
        encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1", "iso-8859-1"]
        df, detected_enc, sep = None, None, ";"
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc) as f:
                    first_line = f.readline()
                sep = ";" if first_line.count(";") >= first_line.count(",") else ","
                df = pd.read_csv(path, sep=sep, dtype=str, encoding=enc)
                detected_enc = enc
                break
            except (UnicodeDecodeError, Exception):
                continue
        if df is None:
            print("Impossible de lire le fichier : encodage non reconnu.")
            sys.exit(1)
        print(f"Encodage détecté : {detected_enc} | Séparateur : '{sep}'")
        return df, sep
    else:
        return pd.read_excel(path, dtype=str), None


def write_file(df: pd.DataFrame, output_path: Path, sep: str | None):
    if output_path.suffix.lower() == ".csv":
        df.to_csv(output_path, index=False, sep=sep or ";", encoding="utf-8-sig")
    else:
        df.to_excel(output_path, index=False)


# Main

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fichier", help="Fichier CSV ou Excel à enrichir")
    args = parser.parse_args()

    path = Path(args.fichier)
    if not path.exists():
        print(f"Fichier introuvable : {path}")
        sys.exit(1)

    print(f"\nLecture de : {path.name}")
    df, sep = read_file(path)
    print(f"{len(df)} lignes | Colonnes : {list(df.columns)}\n")

    COL_NOM   = "Intitulé"
    COL_PAYS  = "Pays"
    COL_SIRET = "N°SIREN/SIRET"
    COL_TVA   = "TVA Intracom"
    COL_NAF   = "Code NAF"
    COL_LABEL = "Libellé NAF"

    for col in [COL_PAYS, COL_SIRET]:
        if col not in df.columns:
            print(f"Colonne obligatoire introuvable : '{col}'")
            print(f"Colonnes disponibles : {list(df.columns)}")
            sys.exit(1)

    masque_fra = df[COL_PAYS].str.strip().str.upper() == "FRA"
    nb_fra = masque_fra.sum()
    nb_hors = (~masque_fra).sum()
    print(f"Lignes FRA à traiter  : {nb_fra}")
    print(f"Lignes hors FRA (skip): {nb_hors}\n")

    if COL_NAF not in df.columns:
        df[COL_NAF] = ""
    if COL_LABEL not in df.columns:
        df[COL_LABEL] = ""

    for i, row in df[masque_fra].iterrows():
        identifiant = None

        siret = clean_siret(row.get(COL_SIRET, ""))
        if siret:
            identifiant = siret

        if not identifiant and COL_TVA in df.columns:
            siren = tva_to_siren(str(row.get(COL_TVA, "")))
            if siren:
                identifiant = siren

        nom = str(row.get(COL_NOM, f"ligne {i+2}"))

        if identifiant:
            print(f"  [{i+2}] {nom} -> {identifiant}")
            naf, label = get_naf(identifiant)
            print(f"        {naf} | {label}")
            time.sleep(PAUSE)
        else:
            print(f"  [{i+2}] {nom} -> aucun identifiant valide")
            naf, label = "DONNÉES MANQUANTES", ""

        df.at[i, COL_NAF]   = naf
        df.at[i, COL_LABEL] = label

    output_path = path.parent / f"{path.stem}_enrichi{path.suffix}"
    write_file(df, output_path, sep)

    lignes_fra = df[masque_fra]
    trouves = lignes_fra[COL_NAF].apply(
        lambda x: x not in ("NON TROUVÉ", "DONNÉES MANQUANTES", "", None)
    ).sum()

    print(f"\nFichier sauvegardé : {output_path.name}")
    print(f"Résultat : {trouves}/{nb_fra} codes NAF récupérés sur les lignes FRA.")
    print(f"Lignes hors FRA conservées sans modification.\n")


if __name__ == "__main__":
    main()