# Deploy

Frontend estático no **Cloudflare Pages**, API em Docker no **Render (plano free)**.
Os dois são gratuitos, e o avaliador não paga nem fornece chave: sem `GEMINI_API_KEY`,
o chat usa só as respostas automáticas (determinísticas, a partir do `summary.json`).

```
navegador ──HTTPS──> Cloudflare Pages (React + MapLibre, _headers com CSP)
    │
    └──HTTPS + Bearer──> Render free (FastAPI, 1 worker) ──> subprocesso por análise
                              │                                 └─> MapBiomas COG (leitura com prazo de 30 s)
                              └─> Gemini (opcional, só no backend)
```

## Limites dos planos gratuitos (conferidos nas docs em 28/10/2026)

| | Render free (web service) | Cloudflare Pages free |
|---|---|---|
| Recursos | 0,1 CPU, 512 MB | estático, CDN |
| Sono | dorme após 15 min sem tráfego; acordar leva ~1 min | não dorme |
| Disco | **efêmero**: perdido em redeploy, restart **e ao dormir**; o plano free não aceita disco persistente | — |
| Cota mensal | 750 h de instância por workspace; esgotou, o serviço fica suspenso até o mês seguinte | 500 builds/mês, 1 build por vez |
| Outros | — | 25 MiB por arquivo (a maior amostra tem ~0,5 MB) |

Fontes: https://render.com/docs/free, https://render.com/docs/blueprint-spec (tabela de planos),
https://developers.cloudflare.com/pages/platform/limits/.

## Medições da imagem Docker (local, limitada como o Render)

`docker run --memory 512m --memory-swap 512m --cpus 0.1`, pico lido em
`/sys/fs/cgroup/memory.peak` (inclui a API e o subprocesso da análise):

| Caso | Tempo (0,1 CPU) | Tempo (0,5 CPU) | Pico de memória |
|---|---|---|---|
| Subida da API até o `/health` | 13 s | — | 68 MiB ocioso |
| Amostra do kit, 512 × 512, com SCL e MapBiomas | 47 s | 11 s | ~200 MiB |
| Amostra + segunda data (fev/2025) | 45 s | 11 s | ~200 MiB |
| Pior caso aceito: 1500 × 1500 px, 4 bandas, com MapBiomas | 63 s | 13 s | **370 MiB** |

Folga de ~140 MiB no pior caso. Como a fila roda **uma análise por vez**, o pico não
se soma. O timeout do job (300 s) cobre o pior caso com 0,1 CPU com folga de ~4×.
No Render, o tempo real depende da CPU compartilhada; os números acima são a
referência, não uma garantia.

## O que o disco efêmero muda (sem esconder)

O banco é SQLite em `DATA_DIR`. No Render free, **cada vez que o serviço dorme ou
reinicia, tudo é apagado**: usuários, análises, arquivos, contadores de cota e lista
de tokens revogados. Consequências:

- **Retenção real** = o menor entre 24 h e "até o próximo sono". A interface diz
  isso ("apagados em até 24 h, ou antes se o servidor gratuito reiniciar").
- **Sessões**: um JWT emitido antes do reinício deixa de valer (o usuário não
  existe mais no banco novo), e a tela pede login de novo. Não há brecha: o JWT só
  é aceito se o usuário existir e o `jti` não estiver revogado.
- **Cotas diárias** (uploads e chat por usuário) **zeram a cada reinício**. O limite
  de frequência por IP também, porque vive na memória do processo. Num abuso
  contínuo o serviço não dorme (há tráfego), então os contadores valem durante o
  ataque; o que se perde é só a contagem entre períodos ociosos.
- Em produção: Postgres (ou disco persistente) para usuários, análises e cotas;
  Redis para o rate limit; objeto (S3/R2) para os rasters, com URL assinada.

## Hibernação e primeira visita

O Render mostra uma página de "acordando" para navegação direta, mas a chamada
`fetch` do frontend (outra origem) recebe essa resposta sem CORS e vê erro de
rede. Por isso a tela de login chama `/health` ao abrir:

- até 4 s sem resposta: nada aparece;
- depois disso, ou se der erro de rede/502: aviso "o servidor gratuito estava
  dormindo e está acordando (até 1 minuto)", com nova tentativa a cada 3 s;
- 90 s sem resposta: erro, mas segue tentando a cada 15 s e some quando a API voltar;
- clique em "entrar" com a API dormindo: o login falha por rede, a credencial do
  Google (válida por ~1 h) fica guardada na memória da página e o login é refeito
  sozinho quando o `/health` responder.

Testes: `frontend/src/lib/useServerWarmup.test.ts` (BVA em 3,999 s / 4 s, retry,
timeout por tentativa, desistência, cancelamento ao desmontar).

**Ping só na janela de avaliação.** Fora dela o serviço dorme, como o plano
gratuito prevê. Durante a avaliação, um avaliador que encontra a API dormindo
espera ~1 min, e o disco efêmero apaga a conta e as análises de quem voltar depois
de 15 min. Por isso `.github/workflows/keepalive.yml` chama o `/health` a cada
10 min até a data em `KEEPALIVE_UNTIL`:

- **Custo:** um serviço acordado o mês todo usa ~744 h, dentro das 750 h do
  workspace. Com um segundo serviço free no mesmo workspace, a conta não fecha.
- **Sem segredo:** `/health` é público e não toca no banco; o workflow não tem
  permissões (`permissions: {}`) nem actions de terceiros.
- **Limite:** o agendamento do GitHub é "melhor esforço" e pode atrasar ou pular
  execuções. A tela de "acordando" continua sendo a garantia.
- **Desligar:** apagar a variável `KEEPALIVE_URL` ou passar da data. O GitHub
  também desativa crons de repositórios sem atividade por 60 dias.

Configurar em Settings > Secrets and variables > Actions > Variables:
`KEEPALIVE_URL=https://<servico>.onrender.com/health` e
`KEEPALIVE_UNTIL=AAAA-MM-DD` (último dia, UTC).

## Cotas da aplicação

| Limite | Valor | Onde |
|---|---|---|
| Upload | 40 MB por envio, até 1500 × 1500 px, pixel de 5 a 60 m | `MAX_UPLOAD_MB`, `MAX_RASTER_DIM`, `uploads.py` |
| Análises | 10 por usuário/dia; 3/min por usuário; 30/dia por IP | `UPLOADS_PER_DAY`, `api/routes_analyses.py` |
| Fila | 4 análises esperando (todas as contas); acima disso, 503 | `MAX_QUEUED_JOBS` |
| Tempo por análise | 300 s; estourou, a análise falha (a cota não volta: o processamento foi gasto). A cota só é devolvida se o envio falhar antes de entrar na fila | `JOB_TIMEOUT_SECONDS` |
| Chat | 30 mensagens por usuário/dia; 10/min; 4 chamadas simultâneas ao Gemini | `CHAT_*` |
| Login | 10/min por IP | `api/routes_auth.py` |
| Geral | 120 req/min por IP | `main.py` (limiter) |
| Sessão | JWT de 60 min | `JWT_TTL_MINUTES` |
| Retenção | análises 24 h; contas sem uso 30 dias (varredura a cada 15 min) | `RETENTION_*`, `USER_RETENTION_DAYS` |

Gemini: o modelo padrão é `gemini-3.5-flash-lite` (o `gemini-2.5-flash-lite` saiu
para projetos novos e responde 404). A chave precisa ser de um projeto **no nível
gratuito**: um projeto com faturamento pré-pago e sem crédito responde 402. O log
mostra o código com uma dica fixa. O nível gratuito do Google AI Studio que tem limites próprios por minuto e por dia [VERIFICAR os valores atuais
em https://ai.google.dev/gemini-api/docs/rate-limits antes de citar números]. Ao
estourar, o circuit breaker abre e o chat volta às respostas automáticas.

## Passo a passo

Pré-requisitos (feitos por você, com suas contas): GitHub, Render, Cloudflare e o
OAuth Client do Google já usado em desenvolvimento.

1. **Repositório**: `gh auth login`, criar o repositório e fazer push de `main`.
   A CI (`.github/workflows/ci.yml`) roda lint, testes e sobe a imagem sem root.
2. **Backend (Render)**: *New → Blueprint*, apontar para o repositório (lê o
   `render.yaml`). Preencher no painel:
   - `GOOGLE_CLIENT_ID`: o mesmo do frontend;
   - `CORS_ORIGINS`: a URL do Pages (passo 3), sem barra final;
   - `GEMINI_API_KEY`: opcional.
   `JWT_SECRET` é gerado pelo Render (256 bits). `TRUSTED_PROXY_HOPS=1` já vem
   no blueprint.
3. **Frontend (Cloudflare Pages)**: *Workers & Pages → Create → Pages → Connect to
   Git*:
   - root directory: `frontend`;
   - build command: `bun install --frozen-lockfile && bun run build`;
   - output directory: `dist`;
   - variáveis: `VITE_API_URL` (URL do Render), `VITE_GOOGLE_CLIENT_ID`,
     `BUN_VERSION=1.4.3`.
   O build gera `dist/_headers` com a CSP apontando para a API, e falha se
   `VITE_API_URL` estiver vazia ou não for https.
4. **Google OAuth**: no Google Cloud Console, adicionar a URL do Pages em
   *Authorized JavaScript origins*.
5. **CORS**: se a URL do Pages mudar, atualizar `CORS_ORIGINS` no Render (o
   serviço reinicia sozinho).
6. **Verificação**:
   ```bash
   uv run scripts/smoke.py --api https://<api>.onrender.com --web https://<app>.pages.dev
   ```
   Confere `/health` (esperando o serviço acordar), 401 sem token, CORS só para a
   origem do Pages, headers de segurança da API e do Pages, CSP com a API e
   amostras servidas. Validado localmente contra o container e o `wrangler pages
   dev`.

## Pontos a conferir no deploy real

- **`TRUSTED_PROXY_HOPS=1`** [VERIFICAR NO DEPLOY]: assumimos que o proxy do Render
  acrescenta exatamente uma entrada ao `X-Forwarded-For`. Se forem mais, o rate
  limit por IP passa a contar o IP do proxy (todos os usuários dividem a cota);
  se forem menos, o IP pode ser forjado pelo cliente. Conferir no log de acesso
  do Render, com uma requisição que mande um `X-Forwarded-For` forjado.
- Primeira análise logo após acordar: confirmar que termina dentro de 300 s.
- Persistência do aviso "acordando" com a API no ar: quase sempre é `CORS_ORIGINS`
  diferente da URL do Pages (para o navegador, recusa de CORS e servidor dormindo
  são o mesmo erro de rede). Conferir com o `smoke.py`.
- O uvicorn roda sem `--proxy-headers`, então `request.url.scheme` é `http` atrás
  do proxy do Render. Hoje nenhuma resposta monta URL absoluta; se um dia montar
  (ex.: redirect de barra final), habilitar `--proxy-headers` com
  `--forwarded-allow-ips` restrito. O IP do cliente não depende disso
  (`client_ip` lê o `X-Forwarded-For` pela direita).
- Saída para o MapBiomas (`storage.googleapis.com`) a partir do Render: se
  bloquear, a análise segue com a referência "indisponível".

## Imagem Docker

- Bases fixadas por digest: `python:3.13-slim@sha256:2d44…86bb` e
  `ghcr.io/astral-sh/uv:0.13.4@sha256:9f13…262b` (o comando para atualizar está no
  Dockerfile).
- Multi-stage: o `uv sync --frozen --no-dev` roda no estágio de build; o runtime
  não tem o uv nem compiladores.
- Usuário `app` (uid 10001), sem shell de login, dono apenas de `/data`. Roda
  também com `--read-only` e `/tmp` em tmpfs (testado localmente; o Render não
  oferece sistema de arquivos somente leitura).
- Única dependência do sistema: `libexpat1` (a wheel do rasterio linka com a do
  sistema, e a imagem slim não a traz). Conferido com `ldd` em todos os `.so` do
  venv.
- `uvicorn --workers 1`: a fila de jobs, o circuit breaker, o semáforo do chat e o
  rate limit vivem na memória do processo. Mais workers dividiriam esse estado.
- `.dockerignore` em lista de permissão: entram só `app/`, `config/`,
  `pyproject.toml` e `uv.lock`. Nenhum `.env` ou `data/` vai para a imagem.
