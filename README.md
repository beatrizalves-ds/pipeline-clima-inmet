# Pipeline de Ingestão Climática (INMET)

Pipeline automatizado que verifica, valida e ingere dados climáticos históricos oficiais do INMET, rodando sozinho de forma agendada, sem intervenção manual. Projeto de portfólio focado em engenharia de dados: o produto aqui não é um modelo, é o cano por onde o dado passa de forma confiável.

## Por que esse projeto

Os outros dois projetos deste portfólio (previsão de churn e risco de ferrugem asiática da soja) demonstram ciência de dados aplicada: pegar um dataset e extrair valor preditivo dele. Este demonstra a etapa anterior, que normalmente é invisível: como um dataset confiável chega a existir e se mantém atualizado sem alguém baixando arquivo manualmente toda semana.

## Arquitetura

```
GitHub Actions (agendador)
        │
        ▼
scripts/pipeline.py
        │
        ├── verifica quais anos ainda não foram ingeridos
        ├── baixa o(s) ano(s) pendente(s) da fonte oficial do INMET
        ├── valida schema, faixa de valores e taxa de nulos
        ├── transforma e limpa
        └── grava em data/clima_sorriso.parquet (versionado no próprio Git)
```

Zero custo: sem AWS, sem servidor, sem cartão de crédito cadastrado em lugar nenhum. O GitHub Actions é gratuito e ilimitado para repositórios públicos, e é o que assume o papel de agendador (equivalente a um cron na nuvem).

## Decisões técnicas que valem registro

**Idempotência.** Rodar o pipeline duas vezes não duplica dado. Antes de baixar qualquer coisa, o script consulta um arquivo de controle (`data/manifest.json`) com os anos já processados com sucesso, e só busca o que ainda falta.

**O ano corrente recebe tratamento diferente dos anos passados.** Um ano já fechado (ex: 2024) é imutável: uma vez validado, nunca precisa ser buscado de novo. O ano corrente, porém, ainda está sendo preenchido pelo INMET ao longo dos meses, então ele nunca entra na lista de "já ingeridos": toda execução do pipeline rebusca o ano corrente inteiro e substitui a versão antiga dele no dataset. Ignorar essa diferença é um erro comum em pipeline de ingestão incremental, tratar todo período como se fosse igualmente estático.

**Validação antes de aceitar o dado.** O script confere três coisas antes de gravar qualquer coisa: se as colunas esperadas existem (a fonte pode mudar formato sem aviso), se a proporção de valores inválidos está dentro do razoável, e se os valores fazem sentido fisicamente. Se a validação falha, o pipeline registra o motivo no log e simplesmente não grava aquele ano, em vez de quebrar ou aceitar dado ruim silenciosamente.

**Commit condicional.** O workflow só cria um commit se algo realmente mudou (`git diff --cached --quiet ||`). Isso evita poluir o histórico do repositório com commits vazios toda vez que o pipeline roda e não encontra novidade.

## Execução

Agendado para rodar toda segunda-feira às 6h UTC (3h em Brasília), via `.github/workflows/pipeline.yml`. Também pode ser disparado manualmente a qualquer momento pela aba Actions do GitHub (`workflow_dispatch`), útil para testar sem esperar o agendamento.

## Limitações

- A cadência semanal é uma escolha arbitrária. Como o INMET atualiza o arquivo do ano corrente com uma frequência que não é garantida nem documentada publicamente, não há como saber o intervalo ideal real de verificação, semanal é um meio-termo razoável entre não perder atualização e não gerar execuções desnecessárias.
- O pipeline cobre uma única estação meteorológica (A904, Sorriso-MT). Escalar para múltiplas estações exigiria paralelizar a ingestão e cuidar de volume de dado maior.
- Validação de schema e faixa de valores é básica. Um pipeline de produção teria testes de qualidade de dado mais formais (ex: Great Expectations) e alertas ativos (e-mail, Slack) em vez de só log.
- Armazenar o dado como arquivo Parquet dentro do próprio Git funciona bem nesta escala (poucos MB), mas não escala para volumes grandes, um repositório Git não é feito para isso.

## Como isso escalaria em produção

A lógica do pipeline (verificar, baixar, validar, transformar) se mantém a mesma, mas a infraestrutura mudaria:

- O script rodaria como uma função **AWS Lambda**, agendada por **EventBridge** em vez de GitHub Actions.
- O dado gravado iria para um bucket **S3** (bruto e processado em pastas separadas), em vez de dentro do repositório Git.
- O catálogo de schema ficaria no **AWS Glue Data Catalog**, permitindo consulta via **Athena** sem precisar carregar o Parquet inteiro em memória.
- Validações de qualidade rodariam como uma etapa própria (ex: Glue Data Quality ou uma Lambda dedicada), com alertas via **SNS** em caso de falha.

Essa migração não muda a lógica de negócio do pipeline, só troca onde cada etapa roda. É a mesma arquitetura conceitual, adaptada para o volume e a confiabilidade que um ambiente de produção exige.

## Ferramentas

Python, pandas, pyarrow, requests, GitHub Actions, dados históricos oficiais do INMET
