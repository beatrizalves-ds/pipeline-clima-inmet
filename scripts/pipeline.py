"""
Pipeline de ingestao automatizada de dados de producao de soja (IBGE/SIDRA).

Busca a serie completa da tabela PAM (Producao Agricola Municipal) do IBGE
para soja, por Unidade da Federacao, valida e grava em formato Parquet
versionado.
"""

import json
import os
from datetime import datetime

import requests
import pandas as pd

TABELA = 1612
CATEGORIA_SOJA = 2713
VARIAVEIS = "109,216,214,215"
NIVEL_TERRITORIAL = "n3/all"
ANOS_SEMPRE_REVISADOS = 2

DATA_DIR = "data"
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")
DATASET_PATH = os.path.join(DATA_DIR, "producao_soja.parquet")


def carregar_manifest():
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r") as f:
            return json.load(f)
    return {"anos_ingeridos": [], "ultima_execucao": None}


def salvar_manifest(manifest):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def buscar_dados():
    url = (
        f"https://apisidra.ibge.gov.br/values/t/{TABELA}"
        f"/{NIVEL_TERRITORIAL}/v/{VARIAVEIS}/p/all/c81/{CATEGORIA_SOJA}"
    )
    resposta = requests.get(url, timeout=120)
    resposta.raise_for_status()
    dados = resposta.json()
    if not dados or len(dados) < 2:
        raise ValueError("Resposta da API vazia ou sem dados.")
    registros = dados[1:]
    return pd.DataFrame(registros)


def validar(df):
    erros = []
    colunas_esperadas = ["D1N", "D2N", "D3N", "D4N", "V"]
    for coluna in colunas_esperadas:
        if coluna not in df.columns:
            erros.append(f"Coluna ausente: {coluna}")
    if erros:
        return erros

    validos = df[~df["V"].isin(["..", "...", "-", "X"])]
    numericos = pd.to_numeric(validos["V"], errors="coerce")
    taxa_nulos = numericos.isna().mean() if len(numericos) > 0 else 1

    if taxa_nulos > 0.5:
        erros.append(f"Taxa de valores nao numericos muito alta: {taxa_nulos:.0%}")

    return erros


def transformar(df):
    limpo = df.rename(columns={
        "D1N": "unidade_federacao",
        "D2N": "variavel",
        "D3N": "ano",
        "D4N": "produto",
        "MN": "unidade_medida",
        "V": "valor",
    })[["unidade_federacao", "produto", "ano", "variavel", "unidade_medida", "valor"]]

    limpo["ano"] = pd.to_numeric(limpo["ano"], errors="coerce")
    limpo["valor"] = pd.to_numeric(limpo["valor"], errors="coerce")
    limpo = limpo.dropna(subset=["ano", "valor"])
    limpo["ano"] = limpo["ano"].astype(int)
    return limpo


def atualizar_dataset(novo_df, anos_para_substituir):
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(DATASET_PATH):
        existente = pd.read_parquet(DATASET_PATH)
        existente = existente[~existente["ano"].isin(anos_para_substituir)]
        combinado = pd.concat([existente, novo_df], ignore_index=True)
    else:
        combinado = novo_df
    combinado = combinado.sort_values(["ano", "unidade_federacao", "variavel"]).reset_index(drop=True)
    combinado.to_parquet(DATASET_PATH, index=False)
    return combinado


def main():
    manifest = carregar_manifest()

    print("Buscando dados da API SIDRA...")
    try:
        df_bruto = buscar_dados()
    except Exception as e:
        print(f"Falha ao buscar dados: {e}")
        return

    erros = validar(df_bruto)
    if erros:
        print("Validacao falhou:")
        for erro in erros:
            print(f"  - {erro}")
        return

    df_limpo = transformar(df_bruto)

    anos_disponiveis = sorted(df_limpo["ano"].unique().tolist())
    if not anos_disponiveis:
        print("Nenhum ano com dado valido encontrado.")
        return

    ultimo_ano = anos_disponiveis[-1]
    anos_ja_ingeridos = set(manifest["anos_ingeridos"])

    anos_para_substituir = [a for a in anos_disponiveis if a > ultimo_ano - ANOS_SEMPRE_REVISADOS]
    anos_novos = [a for a in anos_disponiveis if a not in anos_ja_ingeridos]
    anos_para_gravar = set(anos_novos) | set(anos_para_substituir)

    if not anos_para_gravar:
        print("Nenhuma atualizacao necessaria.")
        return

    df_para_gravar = df_limpo[df_limpo["ano"].isin(anos_para_gravar)]
    atualizar_dataset(df_para_gravar, anos_para_substituir)

    manifest["anos_ingeridos"] = sorted(anos_ja_ingeridos | set(anos_disponiveis))
    manifest["ultima_execucao"] = datetime.now().isoformat()
    salvar_manifest(manifest)

    print(f"Pipeline concluido: {len(df_para_gravar)} registros atualizados, anos {sorted(anos_para_gravar)}.")


if __name__ == "__main__":
    main()
