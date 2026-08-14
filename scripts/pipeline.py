"""
Pipeline de ingestão automatizada de dados climáticos do INMET.

Verifica se há anos novos disponíveis na fonte oficial, baixa,
valida e adiciona ao dataset acumulado em formato Parquet.
"""

import json
import os
import zipfile
import io
from datetime import datetime

import requests
import pandas as pd

ESTACAO = "A904"  # Sorriso, MT
ANO_INICIO = 2021
DATA_DIR = "data"
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")
DATASET_PATH = os.path.join(DATA_DIR, "clima_sorriso.parquet")


def carregar_manifest():
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r") as f:
            return json.load(f)
    return {"anos_ingeridos": [], "ultima_execucao": None}


def salvar_manifest(manifest):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def anos_disponiveis():
    ano_atual = datetime.now().year
    return list(range(ANO_INICIO, ano_atual + 1))


def baixar_ano(ano):
    url = f"https://portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip"
    resposta = requests.get(url, timeout=120)
    resposta.raise_for_status()
    zip_arquivo = zipfile.ZipFile(io.BytesIO(resposta.content))
    candidatos = [n for n in zip_arquivo.namelist() if ESTACAO in n]
    if not candidatos:
        return None
    with zip_arquivo.open(candidatos[0]) as f:
        df = pd.read_csv(f, sep=";", encoding="latin1", skiprows=8, decimal=",")
    df["ano_arquivo"] = ano
    return df


def validar(df, ano):
    erros = []
    colunas_esperadas = [
        "Data", "Hora UTC",
        "TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)",
        "UMIDADE RELATIVA DO AR, HORARIA (%)",
    ]
    for coluna in colunas_esperadas:
        if coluna not in df.columns:
            erros.append(f"Coluna ausente em {ano}: {coluna}")

    if erros:
        return erros

    temp = pd.to_numeric(df["TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)"], errors="coerce")
    temp_valida = temp[(temp > -10) & (temp < 50)]
    taxa_nulos = 1 - (len(temp_valida) / len(temp)) if len(temp) > 0 else 1

    if taxa_nulos > 0.8:
        erros.append(f"Taxa de nulos/inválidos muito alta em {ano}: {taxa_nulos:.0%}")

    return erros


def transformar(df):
    limpo = df[[
        "Data", "Hora UTC",
        "TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)",
        "UMIDADE RELATIVA DO AR, HORARIA (%)",
        "ano_arquivo",
    ]].copy()
    limpo.columns = ["data", "hora", "temperatura", "umidade", "ano_arquivo"]
    limpo["temperatura"] = pd.to_numeric(limpo["temperatura"], errors="coerce")
    limpo["umidade"] = pd.to_numeric(limpo["umidade"], errors="coerce")
    limpo = limpo.replace(-9999, pd.NA).dropna()
    limpo["data"] = pd.to_datetime(limpo["data"])
    return limpo


def atualizar_dataset(novo_df, substituir_ano=None):
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(DATASET_PATH):
        existente = pd.read_parquet(DATASET_PATH)
        if substituir_ano is not None:
            existente = existente[existente["ano_arquivo"] != substituir_ano]
        combinado = pd.concat([existente, novo_df], ignore_index=True)
        combinado = combinado.drop_duplicates(subset=["data", "hora"], keep="last")
    else:
        combinado = novo_df
    combinado = combinado.sort_values(["data", "hora"]).reset_index(drop=True)
    combinado.to_parquet(DATASET_PATH, index=False)
    return combinado


def main():
    manifest = carregar_manifest()
    anos_ja_ingeridos = set(manifest["anos_ingeridos"])
    ano_atual = datetime.now().year

    todos_os_anos = anos_disponiveis()
    anos_completos_pendentes = [a for a in todos_os_anos if a < ano_atual and a not in anos_ja_ingeridos]
    anos_para_processar = anos_completos_pendentes + [ano_atual]

    if not anos_para_processar:
        print("Nenhum ano para processar. Pipeline encerrado sem mudancas.")
        return

    for ano in anos_para_processar:
        print(f"Buscando ano {ano}...")
        try:
            df_bruto = baixar_ano(ano)
        except Exception as e:
            print(f"Falha ao baixar {ano}: {e}")
            continue

        if df_bruto is None:
            print(f"Estacao {ESTACAO} nao encontrada no arquivo de {ano}.")
            continue

        erros = validar(df_bruto, ano)
        if erros:
            print(f"Validacao falhou para {ano}:")
            for erro in erros:
                print(f"  - {erro}")
            continue

        df_limpo = transformar(df_bruto)
        eh_ano_corrente = (ano == ano_atual)
        atualizar_dataset(df_limpo, substituir_ano=(ano if eh_ano_corrente else None))

        if not eh_ano_corrente and ano not in anos_ja_ingeridos:
            manifest["anos_ingeridos"].append(ano)

        print(f"Ano {ano} processado: {len(df_limpo)} registros validos.")

    manifest["ultima_execucao"] = datetime.now().isoformat()
    salvar_manifest(manifest)


if __name__ == "__main__":
    main()
