# Métodos alternativos para café candidato (Guaxupé/MG) e dados de referência

Acesso e medições: **2026-10-28**. Toda fonte está marcada **[VERIFICAR]** e não repete o que já está em `pesquisa-bruta.md` (P1–P5, MapBiomas, SCL), a não ser quando é necessário para comparar.
As medições locais (seção 2) foram feitas com scripts temporários, que não ficaram no repositório. Usam o recorte do kit (512×512, EPSG:32723), a cena de 17/02/2025 e o pipeline atual (`python -m app.processing`).

> **Decisão (28/10/2026):** por causa do prazo, entrou só a comparação com o
> MapBiomas em cada análise (`backend/app/processing/reference.py`). O método
> objetos + random forest da seção 3 fica documentado como próximo passo, sem
> implementação. Os números medidos pela aplicação estão em
> `fase5-segunda-data.md`, seção "Comparação com o MapBiomas".

## 1. O que a literatura usa para café em MG (Sentinel-2/Landsat)

| Família | Fonte (região) | Dados / bandas | Rótulos? | Resultado reportado (condições) |
|---|---|---|---|---|
| **GEOBIA + KNN** | [S1] Embrapa Café Doc. 13 (Três Pontas, S. S. do Paraíso, Carmo de Minas, Oliveira, além de 3 municípios fora do Sul de MG) | **Sentinel-2A 2016, B2, B3, B4, B8 + NDVI (10 m)**, as mesmas 4 bandas que temos. eCognition, *scale* 80–100, *shape* 0,1, *compactness* 0,5 | Sim: amostras para o KNN. Validação com pontos de campo da Emater-MG | Exatidão da classe café de **95 / 81 / 75 / 86 %** nos 4 municípios do Sul de MG. Kappa de 87–98 % |
| **Textura (GLCM) + espectral** | [S2] Marujo et al. 2017 (Sul de MG; Landsat-8 OLI, objetos) | Espectral + textura + iluminação (SRTM) | Sim | Café **57 %** só com espectral e **76 %** com textura. **Nenhum estádio fenológico isolado melhorou** o resultado |
| | [P2] Souza et al. 2016 (Araguari, Carmo de Minas, Três Pontas) | Espectral + textura + geometria | Sim | SVM com 85–88 % de acerto global. A textura melhorou nas 3 áreas (só resumo) |
| **Multitemporal / fenologia + RF** | [P3] Parreiras et al. 2025 | HLS denso (~3 dias), índices e textura. Inclui bandas que não temos (só resumo) | Sim | Sensibilidade e especificidade > 95 % |
| | [P4] Trindade et al. 2024 (Nova Resende, vizinho) | S2 + NDVI/EVI/SAVI + diferenças entre anos, RF no GEE | Sim (base Conab/Emater) | 99 %. Erro típico de **comissão com floresta nativa** |
| **Deep learning** | [S3] Moreno et al. 2026 (Bom Sucesso/MG) | Série temporal S2, TempCNN/L-TAE/ResNet (SITS) | Sim | Compara IoU entre arquiteturas (só resumo; valores não vistos) |
| | [S4] Pisl et al. 2024 (IGARSS) | Série temporal S2, segmentação semântica | Sim | Só metadados Crossref; conteúdo não lido |
| | [S5] Ribeiro et al. 2026 (Muzambinho) | Imagens Google Earth (não S2), FCN/MA-Net | Sim (100 imagens) | Não se aplica às nossas bandas |
| **Referência nacional** | [S6] MapBiomas C11, apêndice de agricultura | Landsat **BLUE, GREEN, RED, NIR, SWIR1, SWIR2** + EVI2, NDWI, com estatísticas do ano inteiro. RF de 100 árvores | Sim | **A acurácia do café não é reportada separadamente**: os pontos LAPIG validam só "Lavoura Perene" agregada |

Leituras para o nosso caso:
- **SWIR** (Landsat TM5/SWIR1–2, S2 B11/B12) aparece no MapBiomas e em P1/P3. Não temos essas bandas. **Red-edge** não aparece nas fontes abertas aqui.
- A única fonte com **exatamente B2/B3/B4/B8 + NDVI** é a [S1], e ela usa **objetos + classificador supervisionado** com amostras.
- **Textura** é o atributo com ganho documentado mais consistente no Sul de MG ([S2], [P2]).
- **Agrupamento não supervisionado puro** não aparece como método principal em nenhuma fonte de MG que abri. Ribeiro et al. citam k-means apenas como prática histórica.

## 2. Evidência medida na cena (descritiva, não é acurácia)

**MapBiomas no recorte.** Coleção 11, ano de 2025, 30 m reamostrado por vizinho mais próximo para a grade de 10 m:
- Café (46): **43 ha**, em 33 manchas, a maior com 9 ha.
- Formação florestal: 944 ha. Pastagem: 694 ha. Outras lavouras temporárias: 345 ha. Mosaico de usos: 296 ha. Urbano: 192 ha.

O recorte tem pouco café pelo MapBiomas. No município inteiro, o MapBiomas C11 mapeia **3.430 ha** de café, contra **3.950 ha** de área colhida no IBGE/PAM 2023 [S8]. A escala municipal bate (87 %), mas isso não diz nada sobre a posição dos pixels.

**Método atual × MapBiomas.**

| Métrica | ago/2025 | fev/2025 |
|---|---|---|
| Área candidata | 155 ha | 192 ha |
| IoU com café MB | **0,04** | 0,02 |
| Candidatas que caem em "outras temporárias" MB | 37 % | — |
| Candidatas que caem em pastagem MB | 34 % | 75 % |
| Candidatas que caem em café MB | **4,7 %** | — |

Para onde vai o café MB nas classes do método atual (ago/2025):
- 37 % em dossel fechado;
- 27 % em vegetação descartada;
- 20 % em solo/rala;
- 17 % em candidata.

**Assinatura por classe MB.** Pixels erodidos 2×, mediana [p25–p75]:

| Classe MB | NDVI ago | NDVI fev | ΔNDVI | DP local NDVI 5×5, fev |
|---|---|---|---|---|
| Café | 0,65 [0,54–0,71] | 0,79 [0,72–0,85] | +0,14 | 0,037 |
| Floresta | 0,79 | 0,92 | +0,12 | **0,008** |
| Pastagem | 0,34 | 0,75 | +0,35 | 0,046 |
| Outras temporárias | 0,42 | 0,91 | +0,46 | 0,023 |
| Cana | 0,39 | 0,89 | +0,47 | 0,012 |

O que a tabela mostra (com rótulos MB ruidosos):
1. O café do MB fica **abaixo** da floresta nas duas datas, e o ΔNDVI dele é parecido com o da floresta (perene).
2. Lavouras temporárias e pasto sobem 0,35–0,47 na chuva.
3. Em fevereiro a **textura separa café de floresta** (DP 0,037 contra 0,008), justamente quando o NDVI já não separa.
4. O limiar de Otsu de agosto (0,665) corta no meio da distribuição do café MB (mediana de 0,648). Isso explica os 37 % que vão para dossel.

**Pilotos rápidos.** Agreement com o MB no recorte, com treino **fora** do recorte. Para isso baixei uma janela de 20×20 km das mesmas cenas, que tem 5.004 ha de café MB, e excluí um buffer de 500 m em volta do recorte.

| Variante | Área prevista | IoU MB | Recall MB | Precisão MB | IoU com o atual | Tempo / memória |
|---|---|---|---|---|---|---|
| RF por pixel, ago, p > 0,7 | 108 ha | 0,13 | 0,42 | 0,16 | 0,13 | 6 s |
| RF por pixel, ago + fev, p > 0,7 | 77 ha | **0,19** | 0,44 | 0,24 | 0,10 | 9 s |
| SLIC (~1 ha) + RF por objeto, ago + fev | 141 ha | 0,16 | 0,59 | 0,18 | 0,14 | 13 s, 1,1 GB (treino em 20 km) |
| Regras 2 datas sem rótulo (Δ ≈ mediana, NDVI_fev < p90 − 0,05, DP > 2× floresta) | 185–274 ha | 0,06 | 0,31–0,41 | 0,06–0,07 | 0,14–0,16 | < 1 s |
| k-means (8 grupos, NDVI + DP nas 2 datas) | nenhum grupo com > 4,3 % de café MB | — | — | — | — | — |
| *Referência: MB 30 m café × MB 10 m "Lavoura perene" (C4)* | — | *0,22* | — | — | — | — |

Leituras dos pilotos:
- Treinar **só dentro** do recorte não funciona: há só 2–11 objetos "puros" de café por bloco.
- Os dois produtos do próprio MapBiomas concordam entre si com IoU de apenas 0,22. Esse é o teto prático de concordância esperável a 10 m.

## 3. Recomendação (no máximo 2 métodos extras)

| # | Método | Solidez para o Sul de MG | Implementável em ~1 dia | Explicável | Nota |
|---|---|---|---|---|---|
| **1** | **Objetos (SLIC) + atributos espectrais, textura e Δ de 2 datas + RF treinado offline com rótulos MapBiomas fora do recorte** | Alta: [S1] usa as mesmas bandas e objetos. [S2]/[P2] mostram ganho com textura | Sim: scikit-image + scikit-learn. Inferência no recorte < 2 s | Média–alta: importâncias e atributos por polígono | **Escolhido** |
| 2 | Regra de "perenidade" em 2 datas, sem rótulos | Média: coerente com P1 e com a tabela da seção 2 | Muito fácil | Alta | Concordância baixa no piloto (IoU 0,06). Usar só como **filtro/explicação** |
| — | k-means / GMM puro | Baixa: não aparece nas fontes; no piloto não isolou café | Fácil | Média | Não recomendado |
| — | Deep learning (U-Net, TempCNN) | Alta na literatura, mas com séries densas e rótulos | Não: sem GPU, sem rótulos de 10 m | Baixa | Fora do escopo |

**Esboço do método 1.**

Treino, feito offline uma vez com um script em `scripts/`:
1. Recortar 20×20 km das mesmas cenas S2 com `baixar_cena.py` e uma grade maior.
2. Recortar o MapBiomas C11, ano igual ao da imagem, para a mesma grade.
3. Rótulos fracos:
   - **positivo** = objeto com ≥ 60 % de pixels café (46);
   - **negativo** = objeto com ≤ 5 % de café;
   - os demais ficam fora do treino;
   - excluir objetos que tocam o recorte de avaliação + 500 m.
4. Salvar o modelo com joblib (kB–MB).

Inferência, no servidor:
1. Fazer a mesma segmentação no recorte: `slic(z, n_segments=área/1 ha, compactness=0.1, channel_axis=-1)` sobre as bandas padronizadas + NDVI das 2 datas.
2. Atributos por objeto:
   - médias de B2–B8 e NDVI por data;
   - ΔNDVI;
   - DP do NDVI dentro do objeto;
   - média do DP local 5×5 (o `texture` que o pipeline já calcula; **não é GLCM**).
3. Aplicar `predict_proba` e cortar em p > 0,5–0,7.
4. Reaplicar a área mínima de 0,5 ha.

Sem verdade de campo, os parâmetros se definem assim:
- tamanho de objeto ≈ unidade mínima do produto (0,5–1 ha);
- limiar de probabilidade escolhido para que a área prevista **na janela de treino** fique próxima da área MB (calibração de prevalência), e não para otimizar IoU no recorte;
- **o recorte avaliado nunca é usado para escolher parâmetros.**

Alternativa à GLCM: `skimage.feature.graycomatrix` por objeto (contraste e homogeneidade do NDVI quantizado em 32 níveis). Fica ~10× mais lento, e o ganho não foi testado aqui.

**Falhas esperadas do método 1:**
- herda os erros do MapBiomas. O MB usa SWIR e mediana anual, e marca como café qualquer pixel classificado como café nos últimos 5 anos [S6];
- café recepado ou em formação confundido com pasto;
- café adensado confundido com mata;
- modelo atrelado ao par de datas e à órbita (R038). Outra estação exige retreino;
- borda de 30 m nos rótulos.

**Método 2, opcional e barato.** Marcar como "perene não florestal" o pixel que satisfaz as três condições:
- |Δ − mediana_veg| < 0,10;
- NDVI_chuva < p90(NDVI_chuva) − 0,05;
- DP local na chuva > 2× o DP mediano do dossel fechado.

Melhor uso: (a) uma camada de explicação ("por que este polígono é perene") e (b) desempate quando o método atual e o RF discordam. Não como mapa principal.

**Comparação justa e o que pode ser afirmado.**
- Reportar uma **matriz de concordância** entre atual, método 1 e MB (IoU, % de A contido em B, área), sempre dentro do recorte e com a mesma máscara de qualidade.
- Para o MB, comparar também **a 30 m**: agregar a fração candidata por pixel MB e usar limiar de 0,5, o que evita penalizar a borda de 10 m. Mostrar a referência MB×MB (0,22).
- **Pode-se afirmar:**
  - concordância/discordância com uma referência pública independente;
  - estabilidade entre datas;
  - em quais classes MB caem os polígonos.
- **Não se pode afirmar:** acurácia, precisão ou recall "verdadeiros". O MB não é verdade de campo, e o próprio MapBiomas não publica a acurácia da classe café.

## 4. Supervisão fraca com MapBiomas: é defensável?

**Sim, como "classificador que imita o MapBiomas a 10 m usando só 4 bandas"**, e não como mapa validado. Armadilhas e mitigação:

| Armadilha | Mitigação |
|---|---|
| **Circularidade** (treinar e avaliar no mesmo MB) | Treinar só fora do recorte com buffer de 500 m (feito no piloto). Na janela de treino, CV espacial em blocos de 1,28 km xadrez. Declarar que o agreement no recorte mede **reprodução do MB**, não acurácia |
| Ruído de rótulo (regra de 5 anos, SWIR, filtro temporal) | Usar só objetos puros (≥ 60 % / ≤ 5 %) e erosão de 1 px. RF com `min_samples_leaf` ≥ 2–5 |
| 30 m × 10 m | Rótulo por objeto, não por pixel. Comparação final também a 30 m |
| Desbalanceamento (café ≈ 12 % na janela de 20 km, 1,6 % no recorte) | `class_weight="balanced"` ou subamostragem. Limiar calibrado pela prevalência na janela de treino |
| Mudança de ano/estação | Ano MB = ano da imagem (C11 2025 para ago/2025). Retreinar se a data mudar de estação |

## Fontes novas (todas [VERIFICAR])

- **[S1]** Alves, H. M. R.; Volpato, M. M. L.; Campos, B. F. D. (2021). *Mapeamento automatizado de áreas de café em Minas Gerais*. Brasília: Embrapa Café (Documentos, 13). https://www.infoteca.cnptia.embrapa.br/infoteca/handle/doc/1134278 — PDF: …/bitstream/doc/1134278/1/Embrapa-Cafe-Serie-Documentos-13.pdf. **Texto completo lido** (métodos e Tabela 8). [VERIFICAR]
- **[S2]** Marujo, R. F. B.; Moreira, M. A.; Volpato, M. M. L.; Alves, H. M. R. (2017). Mapeamento da cultura cafeeira por meio de classificação automática utilizando atributos espectrais, texturais e fator de iluminação. *Coffee Science*, 12(2), 164–175. https://www.alice.cnptia.embrapa.br/alice/bitstream/doc/1089248/1/Mapeamentodaculturacafeeirapormeiodeclassificacao.pdf — **resumo e introdução lidos** (DOI não conferido). [VERIFICAR]
- **[S3]** Moreno, C. L.; Souza, V. C. O.; Paula, M. M. V.; Volpato, M. M. L.; Alves, H. M. R. (2026). Deep Learning e Agricultura Digital: Avaliação de Arquiteturas para Mapeamento Automatizado de Café com Séries… *Anais do XVII WCAMA*, 108–117. https://doi.org/10.5753/wcama.2026.22833 — **só resumo**. [VERIFICAR]
- **[S4]** Pisl, J.; Lenczner, G.; Tuia, D.; de Morsier, F. (2024). Semantic Segmentation of Coffee Plantations from Sentinel-2 Time Series. *IGARSS 2024*, 1526–1530. https://doi.org/10.1109/IGARSS53475.2024.10642247 — **só metadados (Crossref)**. [VERIFICAR]
- **[S5]** Ribeiro, J. M. et al. (2026). Semantic Segmentation of Coffee Regions From Satellite Images Using Deep Learning. *RITA*, 33(2), 202–209. https://doi.org/10.22456/2175-2745.150916 — **resumo e introdução lidos** (CC BY-NC-ND). [VERIFICAR]
- **[S6]** MapBiomas (2026). *Agriculture and Forest Plantation – Appendix, Collection 11* (revisado). https://brasil.mapbiomas.org/wp-content/uploads/sites/3/2026/08/Agriculture-and-Forest-Plantation-Appendix_C11-REVISADO.pdf — **lido** (seções 2.2.4, 2.4, 3.2.5 e 5.1). [VERIFICAR]
- **[S7]** MapBiomas, arquivos GeoTIFF oficiais (listados em https://brasil.mapbiomas.org/downloads/mapas-para-download-geotiff/). Licença CC BY 4.0 (rodapé de brasil.mapbiomas.org/downloads/). Arquivos abertos e recortados com GDAL `/vsicurl/`:
  - 30 m, C11: `https://storage.googleapis.com/mapbiomas-public/initiatives/brasil/collection11/lulc/coverage/brazil_coverage/brazil_coverage-col11_{2023,2024,2025}.tif` (EPSG:4326, LZW).
  - 10 m, C4: `…/initiatives/brasil/lulc_10m/collection4/coverage/brazil_coverage/brazil_coverage-col4_10m_2025.tif`. Não tem classe café, só perene (36).
  - C10: `…/collection_10/lulc/coverage/brazil_coverage_{1985..2024}.tif`.
  - Recorte: `gdalwarp -t_srs EPSG:32723 -te 323200 7637860 328320 7642980 -tr 10 10 -r near /vsicurl/<url> mb.tif`. Lê só os blocos necessários, em segundos.
  - Citação: Souza Jr. et al. 2020, https://doi.org/10.3390/rs12172735.
  - [VERIFICAR] se a página de termos exige um texto de atribuição específico.
- **[S8]** IBGE, SIDRA, tabela 1613 (PAM, lavouras permanentes), Guaxupé (3128709), café total: área colhida de 3.950 ha em 2023 e em 2024. https://apisidra.ibge.gov.br/values/t/1613/n6/3128709/v/216,2313/p/2023,2024/c82/2723 — consultado via API. Limite municipal: https://servicodados.ibge.gov.br/api/v3/malhas/municipios/3128709?formato=application/vnd.geo%2Bjson. [VERIFICAR]
- Algoritmos (só metadados Crossref; texto não lido):
  - Haralick, Shanmugam & Dinstein (1973), Textural Features for Image Classification, *IEEE TSMC*, https://doi.org/10.1109/TSMC.1973.4309314;
  - Achanta et al. (2012), SLIC Superpixels…, *IEEE TPAMI*, https://doi.org/10.1109/TPAMI.2012.120;
  - Felzenszwalb & Huttenlocher (2004), *IJCV*, https://doi.org/10.1023/B:VISI.0000022288.19776.77;
  - Breiman (2001), Random Forests, *Machine Learning*, https://doi.org/10.1023/A:1010933404324.
  - [VERIFICAR]

Não usadas por não terem sido verificadas:
- Estudo "U-Net + Sentinel-1/2 em Machado (92,3 %)": apareceu só em snippet de busca, sem link primário aberto.
- Espelho Source Cooperative do MapBiomas: é de terceiros; prefira os arquivos oficiais.
