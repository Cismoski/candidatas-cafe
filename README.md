# Candidatas a café

Assistente geoespacial que recebe uma imagem Sentinel-2 multiespectral, processa
de verdade no servidor (Python) e desenha **áreas candidatas a café**, com área em
hectares, mapa, downloads e um chat que responde só com os números do
processamento.

> **Áreas candidatas, não café confirmado.** O kit não tem gabarito; nenhum número
> aqui é acurácia. A comparação com o MapBiomas mede concordância com outro mapa,
> e ela é baixa (IoU ≈ 0,04). Ver [Limitações](#limitações).

- **Aplicação:** https://candidatas-cafe.gabrielcismoski.workers.dev/ (API: https://cafe-candidatas-api.onrender.com, que dorme após 15 min sem uso; ver [deploy](docs/deploy.md))
- **Nota de pesquisa:** [`docs/nota-pesquisa.md`](docs/nota-pesquisa.md)
- **Uso de IA:** [`docs/uso-de-ia.md`](docs/uso-de-ia.md)
- **Deploy, cotas, sono e retenção:** [`docs/deploy.md`](docs/deploy.md)

Contains modified Copernicus Sentinel data 2025 ([termos](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice)).
Referência de café: MapBiomas Coleção 11, CC BY 4.0 (Souza Jr. et al., 2020, doi:10.3390/rs12172735).

## Como funciona (para quem avalia)

1. Entrar com Google. O backend valida o ID token e emite a própria sessão.
2. Enviar uma imagem (ou clicar numa amostra: 16/08/2025 seca, 17/02/2025 chuva).
   SCL e uma segunda data são opcionais.
3. O servidor processa em até ~1 min (o plano gratuito tem 0,1 CPU). O primeiro
   acesso depois de 15 min parado leva ~1 min a mais: a tela avisa.
4. Mapa com cor verdadeira, classes, polígonos e, se quiser, o café do MapBiomas.
   Legenda com área por classe, data da imagem, popup por polígono.
5. Downloads: PNG com os polígonos, GeoJSON (EPSG:4326), GeoTIFF de classes.
6. Chat: abre com a classificação e responde sobre resultados e limitações.

## Arquitetura

```
frontend/  React 19 + Vite + TypeScript (bun), MapLibre, TanStack Query
   │  HTTPS, Authorization: Bearer <JWT da API>
   ▼
backend/   FastAPI (1 worker) ── SQLite (usuários, análises, cotas, tokens revogados)
   │          │
   │          ├── fila em memória ──> subprocesso por análise (spawn, timeout 300 s)
   │          │                         app/processing: rasterio, numpy, scipy, shapely
   │          │                         └─> MapBiomas COG via /vsicurl/ (prazo de 30 s)
   │          └── chat: respostas automáticas  ┐ guarda numérica: números
   │                     ou Gemini (opcional) ┘ que existem no resultado
   ▼
Render (Docker, free) · Cloudflare Pages (estático, CSP em _headers)
```

| Pasta | Conteúdo |
|---|---|
| `backend/app/processing/` | Pipeline: leitura e validação, radiometria, índices, classificação, vetorização, renderização, referência MapBiomas |
| `backend/app/ports.py` | Contratos (`Protocol`) do que a API usa de fora: identidade, modelo de chat, repositório, arquivos, fila |
| `backend/app/main.py` | Raiz de composição: liga cada port ao adaptador (`db.py` SQLite, `storage.py` disco, `jobs.py` subprocesso, `auth.py` Google, `llm.py` Gemini) e monta os middlewares |
| `backend/app/api/` | Rotas por assunto (sessão, análises, chat), schemas e middlewares. Banco, arquivos, fila, identidade e modelo chegam pelos ports; validação de upload e emissão do JWT são funções da própria app |
| `backend/app/values.py` | Value objects validados na criação: `AnalysisId`, `IdempotencyKey`, `AnalysisTitle`, `AcquisitionDate` |
| `backend/app/chat/` | Assistente: contexto, guarda numérica (com os value objects `Quantity` e `Allowed`), respostas automáticas, orquestração |
| `backend/config/classification.yaml` | Todos os limiares (nada fixo no código) |
| `frontend/src/` | Telas, cliente da API, mapa, chat |
| `scripts/` | `baixar_cena.py` (recorte de outra data nos COGs públicos), `smoke.py` (verificação do deploy) |
| `docs/` | Nota de pesquisa, uso de IA, deploy, pesquisa bruta e medições |

Por que assim:
- **Subprocesso por análise:** isola memória e travamentos do GDAL, e permite
  matar por timeout sem derrubar a API.
- **PNG reprojetado para o mapa:** o servidor gera sobreposições em EPSG:3857 com
  os cantos em 4326 (`rasterio.warp`), e o MapLibre só posiciona. Não precisa
  de servidor de tiles nem de COG público com URL assinada.
- **Ports and adapters, na medida:** as rotas recebem um `Services` com os
  ports, e os testes trocam o Google e o Gemini por falsos passando outro objeto
  para `create_app`. O processamento ficou de fora de propósito: são funções
  puras sobre arrays, já testáveis sem port. `tests/test_ports.py` confere nomes,
  ordem e padrões dos parâmetros de cada adaptador contra o port (não os tipos:
  o projeto não roda checador de tipos).
- **Value objects onde havia validação espalhada:** id malformado, chave de
  idempotência, título e data inválida eram checados nas rotas ou estouravam ao
  formatar (o 500 da data inexistente). Agora são validados uma vez, na criação,
  e testados sem subir a API (`tests/test_values.py`). Índices e bandas continuam
  arrays numpy: encapsulá-los só atrapalharia a vetorização.
- **SQLite:** basta para uma instância só. Em produção, Postgres + S3/R2 + Redis
  (ver [`docs/deploy.md`](docs/deploy.md)).

## Método (resumo; justificativa e fontes na [nota de pesquisa](docs/nota-pesquisa.md))

| Etapa | O que faz | Parâmetro |
|---|---|---|
| Radiometria | DN × 1e-4 − 0,1 (baseline ≥ 04.00), salvo se o GeoTIFF trouxer scale/offset | `radiometry` |
| Qualidade | SCL como máscara: mantém 4–7, exclui nuvem, sombra, saturado, sem dado | `scl.keep_classes` |
| Índices | NDVI, NDWI (McFeeters), SAVI (L = 0,5); desvio local do NDVI só como atributo | `indices` |
| Exclusões | Água NDWI > 0; solo/vegetação rala NDVI < 0,45; dossel fechado por Otsu (aceito só em [0,65; 0,80] e com separabilidade η ≥ 0,70; senão 0,72) e faixa de 10 m em volta dos núcleos de mata | `rules` |
| Segunda data (opcional) | Continua vegetado (NDVI ≥ 0,45) e \|Δ − mediana sazonal da cena\| ≤ 0,25 | `temporal` |
| Forma | Abertura morfológica; manchas ≥ 0,5 ha; polígonos com área em UTM | `morphology` |
| Referência | Concordância com o café do MapBiomas do ano da imagem (IoU, frações) | `MAPBIOMAS_URL` |

Imagens de outubro a março recebem um aviso: na chuva o café passa do limiar de
dossel fechado e a hipótese de "vigor intermediário" deixa de valer.

## Limitações

- O índice de vegetação sozinho não comprova café. No kit, pelo MapBiomas, as
  candidatas são principalmente lavoura temporária (36,6%) e pastagem (34,4%), e
  36,5% do café do MapBiomas cai em "dossel fechado". IoU com o MapBiomas: 0,038
  (agosto) e 0,044 (agosto + fevereiro). Os números estão em
  [`docs/research/fase5-segunda-data.md`](docs/research/fase5-segunda-data.md).
- A mesma área espalhada ao acaso teria IoU 0,013 (agosto) e 0,012 (agosto +
  fevereiro) com o MapBiomas: há sinal, mas fraco.
- Com uma data só, o resultado depende da estação: agosto e fevereiro concordam
  com IoU 0,05.
- A regra temporal do app favorece a revocação. A regra original tinha mais
  precisão (0,096 × 0,059) com IoU equivalente; a comparação, com variantes sem
  rótulos ancoradas na mata, sai de `scripts/sensibilidade_temporal.py`.
- Agosto é colheita e poda: talhão colhido ou recepado pode cair em "solo e
  vegetação rala". Lavoura de inverno irrigada entra como candidata.
- Limiares calibrados numa cena seca do Sul de MG; 4 bandas (sem SWIR nem
  red-edge); SCL a 20 m.
- Aceita só GeoTIFF em UTM, uint16, de 5 a 60 m, até 1500 × 1500 px.
- Infra gratuita: o disco do Render é efêmero, então dados e cotas somem quando o
  serviço dorme (ver [`docs/deploy.md`](docs/deploy.md)).

## Segurança

| Tema | Como |
|---|---|
| Login | O frontend recebe o ID token do Google e o backend o valida (assinatura, `aud`, `iss`, `exp`, `email_verified`) e cria ou atualiza o usuário. |
| Sessão | JWT próprio (HS256, `iss`, `aud`, `jti`, 60 min), algoritmo fixo. Logout revoga o `jti`. **Bearer no header, decisão para este desafio:** front e API em domínios gratuitos diferentes, sem domínio próprio para cookie first-party. Em produção, cookie `httpOnly` + `SameSite` + CSRF. O token fica no `sessionStorage` e a CSP reduz o risco de XSS. |
| Isolamento | Toda consulta filtra por dono; análise de outro usuário responde **404** (não 403, para não revelar existência). Arquivos em diretório por usuário, nomes gerados no servidor, downloads por lista fixa. |
| Upload | Limite de corpo antes do parse (413, inclusive chunked); Bearer conferido **antes** de ler o multipart; GeoTIFF real (driver, bandas uint16, CRS UTM, pixel 5–60 m, dimensão, "bomba" de bandas pelo header); campos inesperados rejeitados; erros sem ecoar a entrada. |
| Limites | Cotas por usuário (análises e chat por dia), rate limit por IP e por usuário, fila máxima (503), timeout por análise, idempotência por `Idempotency-Key`. Tabela completa em [`docs/deploy.md`](docs/deploy.md#cotas-da-aplicação). |
| Chaves | Só em variáveis de ambiente; `.env.example` sem valores (há teste para isso). A chave do Gemini existe só no backend; nada secreto vai no bundle (`VITE_*` são públicas por definição). |
| Navegador | CORS só para a origem do frontend; CSP restritiva gerada no build; headers de segurança na API e no Pages. |
| Chat | O modelo recebe o resumo numérico e de método, a pergunta e as últimas 6 mensagens, sem nome nem e-mail; a interface avisa para não escrever dados pessoais. Uma guarda confere cada número da resposta contra o resultado, por tipo (percentual, área em ha, contagem de polígonos dada como total ou acima dele), recusa frações e números por extenso e afirmações de acerto ou certeza ("o método acerta", "são café") sem negação ou condição nas 3 palavras antes; ressalvas como "precisam ser confirmadas em campo" passam. Inteiros de 0 a 12 soltos na prosa passam; troca de sinal e frase errada com número certo não são detectadas. O circuit breaker cai para as respostas automáticas. |
| Contêiner | Usuário sem root (uid 10001), imagens fixadas por sha256, 1 worker. |

## Executar localmente

Pré-requisitos: [uv](https://docs.astral.sh/uv/), [bun](https://bun.sh) e um
OAuth Client ID do Google (tipo "Aplicativo da Web", com `http://localhost:5173`
em *Authorized JavaScript origins*).

```bash
# backend
cd backend
cp .env.example .env        # preencha GOOGLE_CLIENT_ID e JWT_SECRET (comando no arquivo)
uv sync
uv run uvicorn --factory app.main:create_app --reload --port 8000

# frontend (outro terminal)
cd frontend
cp .env.example .env.local  # VITE_API_URL=http://localhost:8000 e o mesmo client ID
bun install
bun run dev                 # http://localhost:5173
```

Sem `GEMINI_API_KEY`, o chat funciona com as respostas automáticas.

Pipeline sem API: `cd backend && uv run python -m app.processing IMAGEM.tif saida/ --scl SCL.tif [--second OUTRA.tif]`.

Docker: `docker build -t cafe-candidatas-api backend && docker run -p 8000:8000 --env-file backend/.env cafe-candidatas-api`.

Outra data: `uv run scripts/baixar_cena.py --help` (lê só a janela da área nos COGs do Earth Search).

## Testes (evidências)

Medido em 28/10/2026, localmente. A CI roda lint, pytest com cobertura, os testes do frontend (sem cobertura) e o build da imagem; a mutação roda só localmente (~6 min).

| Conjunto | Resultado | Comando |
|---|---|---|
| Backend (pytest) | **549 passaram**; cobertura 97% (linhas + ramos), sendo 93,9% dos ramos; `classify.py`, `pipeline.py` e `reference.py` com 100% | `cd backend && uv run pytest --cov` |
| Frontend (vitest) | **195 passaram**, cobertura de linhas 92,4% e de ramos 86,7% | `cd frontend && bun run test:cov` |
| Mutação (mutmut, processamento) | **85% dos mutantes mortos** (1.377 de 1.618): `vectorize` 96%, `classify` 92%, `radiometry` 92%, `reading` 85%, `indices` 84%, `pipeline` 81%. Numa amostra dos sobreviventes do `pipeline`, a maioria muda textos e formatação do resumo; o contrato do `summary.json` (chaves e valores derivados) foi fixado num teste depois que a primeira rodada deu 69% nesse módulo | `cd backend && uv run mutmut run && uv run mutmut results` |
| Imagem Docker | sobe sem root e responde ao `/health` (CI) | `.github/workflows/ci.yml` |
| Deploy | 13 verificações de fora (401, CORS, CSP, headers) | `uv run scripts/smoke.py --api … --web …` |

O que os testes cobrem, com exemplos:
- **Processamento:** cenas sintéticas de resposta conhecida.
  - Valor-limite (BVA) nos limiares de NDVI/NDWI, na área mínima, no pixel de 5/60 m, nos anos do MapBiomas e no aviso de estação.
  - Propriedade (Hypothesis): NDVI limitado e antissimétrico; radiometria afim com NaN só onde há NoData; área invariante a translação; mudança sazonal uniforme nunca rejeita; guarda do chat aceita qualquer arredondamento de um valor real e rejeita números distantes; breaker abre só após N falhas seguidas.
  - Branch coverage; mutação no pipeline.
  - Geometrias válidas, área em UTM, regra temporal com e sem desconto sazonal.
  - MapBiomas: alinhamento geográfico, cobertura parcial, servidor que não responde.
- **Segurança:** rotas protegidas, enumeradas uma a uma; token adulterado, sem claim ou de outro esquema; logout que revoga; usuário B recebe 404 nas análises e arquivos de A; download só da lista fixa; nome de arquivo que nunca vira caminho.
- **Upload e limites:** corpo grande e chunked; multipart anônimo recusado antes do parse; bomba de bandas; cota atômica sob concorrência; idempotência por usuário; fila cheia.
- **Chat:** guarda numérica (percentuais, unidades coladas, números por extenso), circuit breaker, perguntas sobre acurácia.
- **Frontend:** sessão expirada, troca de usuário sem vazar cache, estados de carregamento, erro e sem resultado, ordem das camadas do mapa, servidor acordando.

## Serviços usados

| Serviço | Uso | Custo |
|---|---|---|
| Google Identity Services | Login | grátis |
| Copernicus Sentinel-2 L2A via Earth Search (AWS) | Imagem do kit e segunda data | grátis, atribuição obrigatória |
| MapBiomas Coleção 11 (GCS público) | Referência de café | grátis, CC BY 4.0 |
| Google Gemini (AI Studio, nível gratuito) | Chat (opcional) | grátis; o Google pode usar os dados do nível gratuito, por isso só o resumo da análise e a conversa vão ao modelo, sem nome nem e-mail |
| OpenFreeMap | Mapa base | grátis, sem chave; dados OpenStreetMap (ODbL), atribuição exibida no mapa |
| Render (free) | API | grátis; dorme após 15 min (ping na janela de avaliação, ver deploy.md) |
| Cloudflare Pages (free) | Frontend | grátis |
| GitHub Actions | CI | grátis em repositório público |
