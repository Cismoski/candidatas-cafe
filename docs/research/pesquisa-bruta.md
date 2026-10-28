# Pesquisa bruta — mapeamento de café candidato (Guaxupé/MG, S2 L2A 2025-08-16)

Data de acesso de todas as fontes: **2026-10-28**. Só estão listadas fontes efetivamente abertas nesta sessão (WebFetch/WebSearch/curl/APIs).
Legenda de confiança do link: **Alta** = resolvido nesta sessão (HTTP 200 ou DOI→302 para a editora); **Média** = metadados confirmados via Crossref, mas a página da editora bloqueou (403/5xx).

---

## 1. Fontes primárias

### 1.1 Mapeamento de café (metodologia)

**[P1] Moreira, M. A.; Adami, M.; Rudorff, B. F. T. (2004).** Análise espectral e temporal da cultura do café em imagens Landsat. *Pesquisa Agropecuária Brasileira*, 39(3), 223–231.
DOI: https://doi.org/10.1590/S0100-204X2004000300004 — **texto completo lido** (SciELO). Confiança: Alta.
- Aguanil (centro-sul de MG, 20°58'S 45°25'W), Landsat TM/ETM+ de 1999 e 2001; classes café-formação, café-produção, pastagem e mata.
- Conclusões relevantes: (i) **imagens do período seco são as melhores para mapear café**, apesar de ser cultura perene; (ii) **banda do NIR (TM4)** separa melhor café de pastagem e mata; (iii) café-formação se confunde com pastagem no vermelho (TM3) e no SWIR (TM5), conforme o estádio; (iv) a reflectância do café-produção varia muito entre lavouras (idade, espaçamento, cultivar) e entre anos (imagens de agosto de 1999 vs. 2001); (v) a classificação digital precisa ser corrigida por fotointerpretação. Valores de NDVI por classe não aparecem no resumo/conclusões.

**[P2] Souza, C. G.; Carvalho, L.; Aguiar, P.; Arantes, T. B. (2016).** Algoritmos de aprendizagem de máquina e variáveis de sensoriamento remoto para o mapeamento da cafeicultura. *Boletim de Ciências Geodésicas*, 22(4), 751–773.
DOI: https://doi.org/10.1590/S1982-21702016000400043 — **somente resumo** (via Crossref; SciELO retornou 502/504). Confiança: Média.
- Três áreas de MG (Araguari, Carmo de Minas, Três Pontas); 5 algoritmos × 7 combinações de variáveis (espectrais, texturais, geométricas), 105 classificações.
- SVM foi o melhor (acurácia global de 85,33%, 87% e 88,33%). RF foi o pior em Araguari (76,66%). **Variáveis de textura somadas às espectrais melhoraram a acurácia nas três áreas.** Sem variáveis espectrais o resultado foi ruim. Isso apoia o uso de textura local de NDVI.

**[P3] Parreiras, T. C.; Santos, C. (O. dos); Bolfe, É. L.; Sano, E. E.; Leandro, V. B. S.; Bayma, G. et al. (2025).** Dense Time Series of Harmonized Landsat Sentinel-2 and Ensemble Machine Learning to Map Coffee Production Stages. *Remote Sensing*, 17(18), 3168. Licença CC BY 4.0.
DOI: https://doi.org/10.3390/rs17183168 — **somente resumo** (via Crossref; MDPI retornou 403). Confiança: Média (DOI registrado).
- Série densa HLS (~3 dias) com bandas, índices espectrais e **métricas de textura**, classificação hierárquica com RF + XGBoost. Sensibilidade e especificidade de detecção de café **>95%** (RF). Estágios fenológicos (plantio, produção, esqueletamento, recepa) com acurácia balanceada de 77% (recepa) e de 93–95% (demais). O resumo destaca que práticas de manejo (poda, recepa) aumentam a variabilidade entre lavouras. A região de estudo não está nomeada no resumo ("one of Brazil's most important coffee-producing regions").

**[P4] Trindade, E. S.; Marques, A. A. S.; Avelino, R. A. V.; Marques, A. V.; Gomes, W. J.; Pereira, A. A. (2024).** Inteligência artificial no mapeamento e atualização do cultivo de café. *Anais da 16ª Jornada Científica e Tecnológica do IFSULDEMINAS*, v. 16, n. 1.
URL: https://josif.ifsuldeminas.edu.br/ojs/index.php/anais/article/view/2236 (PDF: …/article/download/2236/1330/16665) — **texto completo lido** (resumo expandido, sem revisão por pares de periódico). Confiança: Alta.
- **Nova Resende/MG (sudoeste de MG, vizinho da região de Guaxupé).** Base oficial Conab/EMATER-MG de 2017 atualizada com Sentinel-2 (bandas + NDVI, EVI, SAVI + diferenças 2017–2021), RF no GEE. Acurácia global de 99,28%, Kappa de 0,991. Área de café de 14.068 ha em 2021 (+5,6%, ou +751 ha).
- O exemplo de erro de comissão citado é **"confusão espectral com floresta nativa"**, minimizada com máscara pós-classificação usando o mapa de 2017.

**[P5] Sousa, R. B.; Vieira, T. G. C.; Alves, H. M. R.; Volpato, M. M. L.; Souza, V. C. O.; Santos, W. J. R.; Silva, E. (VI Simpósio de Pesquisa dos Cafés do Brasil).** Mapeamento de áreas cafeeiras do Sul de Minas Gerais – Machado e Três Pontas. EPAMIG/Embrapa Café.
URL: https://www.alice.cnptia.embrapa.br/alice/bitstream/doc/880317/1/Mapeamentodeareascafeeiras.pdf — **texto completo lido** (repositório Alice/Embrapa). Confiança: Alta. (O ano do evento não consta na primeira página extraída.)
- Metodologia EPAMIG/Embrapa: **interpretação visual** de Landsat 5 TM (bandas 3, 4 e 5) e conferência em campo, depois comparação com classificação supervisionada. Global/Kappa de 97%/95% em Machado e 99%/98% em Três Pontas. Classes: café, café em formação/renovação, mata, área urbana, água, solo exposto e outros. Autores apontam influência da topografia.

Fonte complementar aberta (mesma série EPAMIG): Vieira, T. G. C.; Alves, H. M. R.; Bertoldo, M. A. — Mapeamento de áreas cafeeiras de Minas Gerais por imagem de satélite, Parte I: Patrocínio (III Simpósio de Pesquisa dos Cafés do Brasil). https://www.alice.cnptia.embrapa.br/alice/bitstream/doc/908844/1/Mapeamentodeareas.pdf. Landsat 7 TM, SPRING, classificador Bhattacharya. As classes incluem **"reflorestamento"** separado de "mata" e de três estádios de café. Confiança: Alta.

Encontradas, mas **não abertas** (só metadados Crossref/Semantic Scholar; não usar como evidência de conteúdo):
- Kawakubo, F. S.; Pérez Machado, R. P. (2016). Mapping coffee crops in southeastern Brazil using spectral mixture analysis and data mining classification. *IJRS*, 37(14), 3414–3436. https://doi.org/10.1080/01431161.2016.1201226
- Fiorillo, E.; West, T. P. (2025). Deep Learning for High-Resolution Mapping of Coffee Cultivation in Minas Gerais, Brazil. SSRN preprint. https://doi.org/10.2139/ssrn.5659497
- Moreira, M. A.; Barros, M. A.; Rudorff, B. F. T. (2008). Geotecnologias no mapeamento da cultura do café em escala municipal. *Sociedade & Natureza*, 20(1). https://doi.org/10.1590/S1982-45132008000100007 (SciELO 504)
- Conab: não encontrei documento técnico oficial descrevendo a metodologia atual (Plataforma Parque Cafeeiro, Conab/UFMG). Só notícias, que não foram usadas.

### 1.2 Índices (referências originais; DOIs verificados)

| Índice | Citação | DOI/URL | Verificação |
|---|---|---|---|
| NDVI (origem) | Rouse, J. W. Jr.; Haas, R. H.; Schell, J. A.; Deering, D. W. (1974). Monitoring vegetation systems in the Great Plains with ERTS. *3rd ERTS-1 Symposium*, NASA GSFC, Vol. 1, Sect. A (Paper A20). | https://ntrs.nasa.gov/citations/19740022614 (sem DOI) | Registro NTRS aberto e PDF disponível. O resumo descreve uma razão de bandas MSS 5 (vermelho) e 7 (NIR), corrigida pelo ângulo solar e correlacionada com a biomassa verde. Confiança: Alta |
| NDVI (consolidação) | Tucker, C. J. (1979). Red and photographic infrared linear combinations for monitoring vegetation. *Remote Sensing of Environment*, 8(2), 127–150. | https://doi.org/10.1016/0034-4257(79)90013-0 (versão NASA: https://ntrs.nasa.gov/citations/19780024582) | DOI resolve (302 → Elsevier); resumo lido no NTRS. Avalia combinações vermelho/IR, incluindo IR/red, VI e TVI, contra biomassa, água foliar e clorofila. Confiança: Alta |
| NDWI | McFeeters, S. K. (1996). The use of the Normalized Difference Water Index (NDWI) in the delineation of open water features. *IJRS*, 17(7), 1425–1432. | https://doi.org/10.1080/01431169608948714 | DOI confere com o informado e resolve (302 → T&F). Metadados via Crossref; **texto e resumo não abertos** (fechado). Confiança: Alta (link) |
| SAVI | Huete, A. R. (1988). A soil-adjusted vegetation index (SAVI). *Remote Sensing of Environment*, 25(3), 295–309. | https://doi.org/10.1016/0034-4257(88)90106-X | DOI resolve (302 → Elsevier). Metadados via Crossref; **texto não aberto**. Confiança: Alta (link) |

As fórmulas (NDWI = (G−NIR)/(G+NIR); SAVI com L=0,5) são a definição usual, mas **não as conferi no texto original** nesta sessão.

---

## 2. MapBiomas

- **Coleção atual (30 m, Landsat): Coleção 11**, lançada em agosto de 2026, com mapas anuais de **1985–2025** a 30 m. Acurácia global média de 93,4% no Nível 1 e de 89,5% no Nível 2.
  Fonte: ATBD Coleção 11 v1 (ago/2026). https://brasil.mapbiomas.org/wp-content/uploads/sites/3/2026/08/ATBD-General-Collection-11-versao-1.pdf (PDF lido). A home https://brasil.mapbiomas.org/ cita o evento "MapBiomas lança Coleção 11". Confiança: Alta.
- **Classe café:** **ID 46 – Café / Coffee** (hierarquia 3.2.2.1, dentro de Lavoura Perene 36; cor #d68fe2). Classes de confusão no nosso caso: Formação Florestal (3), Silvicultura (9), Pastagem (15), Outras Lavouras Perenes (48).
  Fonte: Legenda Coleção 10 (PDF), https://brasil.mapbiomas.org/wp-content/uploads/sites/4/2025/08/Legenda-Colecao-10-Legend-Code.pdf. O catálogo GEE também lista 46 = Coffee. O ATBD da Coleção 11 mantém "3.2.2.1. Coffee". Confiança: Alta.
- **Licença:** **CC BY 4.0**. O rodapé de brasil.mapbiomas.org diz "Os dados do MapBiomas são de uso público, aberto e gratuito mediante referência. CC BY 4.0", e o catálogo GEE traz "Terms of Use: CC-BY-4.0". Citação pedida pelo GEE: Souza, C. M. Jr. et al. (2020), *Remote Sensing* 12(17), 2735, https://doi.org/10.3390/rs12172735 (DOI verificado via Crossref).
- **Acesso ao raster:**
  - GEE (catálogo oficial): `ee.ImageCollection("projects/mapbiomas-public/assets/brazil/lulc/v1")`, banda `classification`, 30 m. **Atenção:** a página do catálogo, lida hoje, mostra disponibilidade **1985–2024** e um exemplo rotulado "Collection 10", ou seja, o catálogo GEE ainda aponta para a Coleção 10. Não encontrei o asset GEE da Coleção 11.
  - Página do catálogo: https://developers.google.com/earth-engine/datasets/catalog/projects_mapbiomas-public_assets_brazil_lulc_v1 (Alta).
  - Download direto (GeoTIFF/GCS): **não verificado**. As páginas antigas "colecoes-mapbiomas", "termos-de-uso" e "mapbiomas-cobertura-10m" deram 404 hoje.
- **MapBiomas 10 m (Sentinel-2):** a **Coleção 4 (10 m)** foi lançada em agosto de 2026 e cobre **2017–2025**, com 26 classes e unidade mínima de mapeamento de 0,25 ha. Usa embeddings AlphaEarth/Google como variáveis auxiliares. Histórico: C1 beta (2016–2022, 18 classes), C2 (até 2023, 21 classes), C3 (até 2024, 22 classes). **No esquema de 10 m não existe classe café separada:** o ATBD lista "3.2.2. Perennial Crop (36)" e a palavra "coffee" não aparece no documento.
  Fonte: ATBD MapBiomas 10 m Coleção 4 v1.1 (ago/2026), https://brasil.mapbiomas.org/wp-content/uploads/sites/3/2026/08/ATBD-Collection-4-Sentinel-v1.1.pdf (PDF lido). Plataforma citada no ATBD: https://plataforma.brasil.mapbiomas.org/cobertura_10m (não aberta). **Asset GEE do 10 m não verificado.** A busca web devolveu `projects/mapbiomas-public/assets/brazil/lulc_10m/collection2/...` (C2), mas não abri a página.

---

## 3. Sentinel-2: SCL e licença Copernicus

**SCL (SentiWiki/ESA — S2 Processing, Tabela 3 "Scene classification values"):** https://sentiwiki.copernicus.eu/web/s2-processing (Alta). O SCL é gerado a 20 m (reamostrado para 60 m por moda).

| Valor | Classe |
|---|---|
| 0 | NO_DATA |
| 1 | SATURATED_OR_DEFECTIVE |
| 2 | CAST_SHADOWS |
| 3 | CLOUD_SHADOWS |
| 4 | VEGETATION |
| 5 | NOT_VEGETATED |
| 6 | WATER |
| 7 | UNCLASSIFIED |
| 8 | CLOUD_MEDIUM_PROBABILITY |
| 9 | CLOUD_HIGH_PROBABILITY |
| 10 | THIN_CIRRUS |
| 11 | SNOW or ICE |

Observação para o método: com o SCL a 20 m, a máscara de vegetação a 10 m herda bordas em blocos de 2×2 pixels. Pasto seco em agosto tende a cair em 5 (NOT_VEGETATED). Isso é inferência minha, não está na fonte.

**Legal notice Copernicus Sentinel** (Comissão Europeia, DG DEFIS; PDF de 2 páginas): https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice (Alta, lido via pdftotext).
- Acesso livre, completo e aberto, sem garantia (Reg. UE 377/2014 e Reg. Delegado 1159/2013). São permitidos reprodução, distribuição, comunicação ao público, **adaptação/modificação e combinação com outros dados**.
- Atribuição obrigatória ao distribuir: "Copernicus Sentinel data [Ano]". **Se o dado for modificado: "Contains modified Copernicus Sentinel data [Ano]"**. No nosso caso: "Contains modified Copernicus Sentinel data 2025".
- O usuário renuncia a pedidos de indenização contra a UE e os provedores.

---

## 4. Planos gratuitos (acessados em 2026-10-28)

**Google Gemini API**
- Pricing: https://ai.google.dev/gemini-api/docs/pricing (Alta). Modelos com "Free of charge" no Free Tier (tabela Standard): Gemini 3.8 Flash, 3.6 Flash, 3.5 Flash-Lite, 3.1 Flash-Lite, 3 Flash Preview, 2.5 Pro, 2.5 Flash, 2.5 Flash-Lite, além de TTS/Live/Transcribe e Robotics ER 2 Preview. **Sem free tier:** Gemini 4 Argon, 3.1 Pro Preview, Omni Flash e os modelos de imagem ("Nano Banana").
- Rate limits: https://ai.google.dev/gemini-api/docs/rate-limits (Alta). Os limites são medidos em RPM, TPM e RPD **por projeto** (não por chave) e o RPD zera à meia-noite do Pacífico. Modelos preview/experimentais têm limites mais restritos. **A página não publica mais os números por modelo:** manda ver em AI Studio (https://aistudio.google.com/rate-limit). Não consegui confirmar valores de RPM/RPD do free tier.
- Privacidade: Termos adicionais, https://ai.google.dev/gemini-api/terms (Alta). Na seção "Unpaid Services", que inclui a cota gratuita da API, o Google **usa prompts e respostas para melhorar e desenvolver produtos e modelos de ML**, e **revisores humanos podem ler** as entradas e saídas. Recomendação literal: "Do not submit sensitive, confidential, or personal information". A tabela de pricing mostra "Used to improve our products: Yes" no Free Tier e "No" no Paid.

**Render (free web service)**
- https://render.com/docs/free e https://render.com/pricing (Alta). **512 MB RAM, 0,1 CPU**. **Spin-down após 15 min** sem tráfego, e o spin-up leva **~1 min** (página de loading). **Filesystem efêmero**, perdido em redeploy, restart ou spin-down, e o plano Free não aceita disco persistente. **750 instance-hours/mês por workspace** (serviço dormindo não consome), com suspensão até o mês seguinte se esgotar. Banda de saída e minutos de build entram nas cotas mensais do workspace. Postgres free expira em 30 dias.

**Hugging Face Spaces**
- https://huggingface.co/docs/hub/spaces-overview, …/spaces-gpus, …/spaces-storage (Alta). CPU Basic tem **2 vCPU, 16 GB RAM e 50 GB de disco não persistente**, sem custo por hora. **Mudança importante:** "creating a new Space that runs on compute (**Gradio or Docker**) **requires a paid plan** (PRO)". Só Spaces **estáticos** são grátis para todos. Contas free ainda podem ter até 2 Spaces Gradio em ZeroGPU. Dorme após **48 h** de inatividade no cpu-basic e reinicia com nova visita. Disco efêmero; para persistir é preciso anexar Storage Buckets. **Conclusão: Docker Space grátis não está mais disponível para contas novas/free.**

**Fly.io**
- https://fly.io/docs/about/pricing/ (Alta). **Organizações novas não têm free tier nem franquia mensal.** Há só um trial de **até 2 h de runtime de Machine ou 7 dias** (o que vier primeiro), sem cartão. Planos descontinuados em out/2024 mantêm as franquias antigas. A máquina mais barata, shared-cpu-1x com 256 MB, custa US$ 2,19 por 30 dias.

**Cloudflare Pages (free)**
- https://developers.cloudflare.com/pages/platform/limits/ (Alta; "Last updated Sep 5, 2026"). **500 builds/mês**, 1 build simultâneo, timeout de 20 min. 20.000 arquivos por site, 25 MiB por arquivo, 100 projetos. Requisições a **Pages Functions** contam na cota de Workers: **100.000 req/dia, 10 ms de CPU e 128 MB** no Workers Free (https://developers.cloudflare.com/workers/platform/limits/). **Banda e requisições a assets estáticos: a página de limites não traz número; não verifiquei.**

**Koyeb**
- https://www.koyeb.com/pricing (Alta; o banner diz que a Koyeb está "joining Mistral AI"). Existe uma instância **"Free"** listada como "0.25 vCPU, 1 GB RAM, 1 GB storage, $0" com a menção "5h". Os metadados embutidos na página descrevem a instância `free` como "512MB, 2000MB disk, vcpu_shares 0.1, regiões fra/was, service_types web, volumes_enabled false". **As informações são inconsistentes na própria página**, e o significado de "5h" (limite de horas?) não está claro. Tratar como **não verificado**.

---

## 5. Earth Search STAC — cenas do período úmido (MGRS-23KLS)

Endpoint: `POST https://earth-search.aws.element84.com/v1/search`, `collections=["sentinel-2-c1-l2a"]`, `query={"grid:code":{"eq":"MGRS-23KLS"},"eo:cloud_cover":{"lt":15}}`, `intersects` = bbox da área (lon −46,705..−46,655, lat −21,353..−21,306). Janelas: 2024-11-01/2025-03-31 (20 cenas com cc<30) e 2025-11-01/2026-03-31 (19 cenas com cc<30). Consulta feita em 2026-10-28.

**Verificação sobre a bbox:** para cada candidata li o asset `scl` (COG) recortado na bbox via GDAL `/vsicurl/` e calculei a % de pixels claros (SCL 4/5/6) e de nuvem/sombra (SCL 3/8/9/10). O `eo:cloud_cover` é global ao tile e **não garante** céu limpo na bbox. Por isso a checagem local, mas ela depende da própria precisão do SCL (nuvens finas e sombras podem escapar).

Top 5 (preferindo a mesma órbita relativa da cena de referência, **R038**, `S2B_T23KLS_20250816T132502_L2A`, que tem `s2:nodata_pixel_percentage` = 52,43%):

| # | id | datetime (UTC) | eo:cloud_cover | s2:nodata_pixel_percentage | Órbita | % claro na bbox (SCL 4/5/6) | % nuvem/sombra na bbox |
|---|---|---|---|---|---|---|---|
| 1 | S2B_T23KLS_20250217T132718_L2A | 2025-02-17T13:28:13 | 0,019 | 53,32 | R038 | 99,93 | 0,00 |
| 2 | S2C_T23KLS_20251119T132242_L2A | 2025-11-19T13:28:17 | 1,50 | 52,88 | R038 | 99,97 | 0,00 |
| 3 | S2A_T23KLS_20251121T132249_L2A | 2025-11-21T13:28:25 | 0,88 | 52,20 | R038 | 99,97 | 0,00 |
| 4 | S2B_T23KLS_20260110T131730_L2A | 2026-01-10T13:18:10 | 0,19 | 10,92 | R138 | 99,93 | 0,00 |
| 5 | S2B_T23KLS_20251201T131235_L2A | 2025-12-01T13:18:07 | 0,33 | 10,85 | R138 | 99,93 | 0,00 |

Outras com a bbox limpa: S2C_..._20251126 (R138, cc 1,26), S2B_..._20250306 (R138, cc 4,76), S2B_..._20250227T132756 (R038, cc 2,05). O par S2B_..._20250227T132235 tem nodata de 99,6% no tile, então evitar. Todas as cenas são baseline 05.11, exceto 2026-02-17 (05.12).

Notas:
- **Recomendação:** #1 (2025-02-17, S2B, R038) tem mesmo satélite, mesma órbita relativa e geometria de visada semelhante à referência, e cai no meio da estação chuvosa, o que minimiza diferenças angulares/BRDF na comparação temporal.
- Nodata de ~52% nas cenas R038 significa que o tile está na borda do swath. A bbox está coberta (nodata local de 0%), mas convém checar de novo se a área mudar.
- As cenas R138 (~10% de nodata) têm outro ângulo de visada; servem como alternativa.
- Script de busca e recorte: executado em sandbox (Python + GDAL 3.13), sem arquivo persistido no repositório.
