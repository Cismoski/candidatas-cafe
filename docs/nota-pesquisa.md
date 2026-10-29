# Nota de pesquisa: áreas candidatas a café em Sentinel-2 (Guaxupé, MG)

Gabriel Cismoski, outubro de 2026. Números brutos e medições: `docs/research/`.

## Problema e método escolhido

O kit é um recorte Sentinel-2 L2A de 16/08/2025 com 512 × 512 px a 10 m:
bandas B02, B03, B04 e B08, mais a SCL, sem rótulos. Sem verdade de campo, o
produto honesto é um mapa de **áreas candidatas**, feito com regras
explicáveis, e não uma classificação com acurácia.

Para cada imagem enviada, o método converte para reflectância, usa a SCL só
como máscara de qualidade e calcula NDVI, NDWI e SAVI [2]. Depois exclui água
(NDWI > 0), solo e vegetação rala (NDVI < 0,45), dossel fechado (limiar de
Otsu [3] sobre o NDVI da vegetação) e uma faixa de 10 m em volta dos núcleos de
mata. Por fim aplica abertura morfológica, descarta manchas abaixo de 0,5 ha e
gera polígonos com área em UTM. O limiar de Otsu só é aceito se cair em
[0,65; 0,80] e com η ≥ 0,70; senão, vale 0,72. Com uma segunda data, o pixel precisa continuar vegetado e variar no
máximo 0,25 de NDVI, descontada a variação sazonal da cena. Os limiares ficam em
`backend/config/classification.yaml` e são gravados em cada resultado.

**Justificativa.** Num estudo com Landsat em Aguanil (MG), o período seco foi
a melhor época para mapear café, e o NIR foi a banda que melhor o separou de
pastagem e mata [1]. Na seca, o pasto perde vigor e a mata segue fechada; o
café fica no meio. É uma hipótese de separabilidade, não uma prova: a
literatura registra confusão com mata e usa conferência visual ou em campo
[1][4][5].

## Alternativas consideradas

**A. Classificação supervisionada** (RF ou KNN por objetos). É a abordagem da
Embrapa Café: GEOBIA + KNN com as mesmas 4 bandas do Sentinel-2, amostras de
treino e validação com pontos de campo da Emater-MG [6]. Também foi usada com RF
em Nova Resende [5]. Descartada porque aqui não há amostras de campo: os rótulos
teriam de vir do MapBiomas (30 m, com erros próprios), e a avaliação contra o
mesmo mapa seria circular. Fica para quando houver dados de campo.

**B. Regra multitemporal sem rótulos: perenidade + textura.** Troca o teto de
Otsu por rugosidade: na chuva, o café em linhas é mais rugoso que a mata (desvio
local do NDVI 0,039 × 0,009). Medi com `scripts/sensibilidade_temporal.py`: IoU
0,046 com o MapBiomas, contra 0,044 do app, mas a área triplica (445 ha) e 34%
cai sobre floresta. Ganho dentro do ruído; não adotei. O MapBiomas (classe 46)
[7] também não serve de resposta, porque não processa a imagem enviada: virou
**camada de referência**.

## Origem e condições de uso

- **Sentinel-2 L2A** via Earth Search: a cena do kit e uma de 17/02/2025, mesma
  órbita. A licença Copernicus permite modificar e redistribuir com a atribuição
  "Contains modified Copernicus Sentinel data 2025" [8], que aparece no app.
  `scripts/baixar_cena.py` recorta sem reamostrar e, na cena do kit, reproduz o
  kit pixel a pixel. Classes da SCL pela tabela da ESA [9].
- **MapBiomas Coleção 11**: CC BY 4.0, com citação [7].
- **Gemini** (nível gratuito, opcional): os termos permitem ao Google usar as
  entradas e mostrá-las a revisores humanos [10]. O modelo recebe o resumo
  numérico, a pergunta e as últimas mensagens, sem nome nem e-mail. Uma guarda
  no backend rejeita respostas com números fora do resultado ou que afirmem
  acerto.
- **Mapa base**: OpenFreeMap, com dados OpenStreetMap (ODbL); a atribuição com
  link aparece no mapa [11].

## Como verifiquei

1. **Código.** Testes com cenas sintéticas de resposta conhecida: valor-limite,
   propriedade (Hypothesis) e mutação. Na cena do kit, os 90 polígonos do
   GeoJSON são válidos.
2. **Entre datas.** As candidatas de agosto e as de fevereiro concordam pouco
   (IoU 0,05), e 76% das de agosto viram dossel fechado na chuva. Com uma data
   só, o resultado depende da estação.
3. **Referência independente.** IoU com o café do MapBiomas 2025: 0,038
   (agosto) e 0,044 (+ fevereiro); ao acaso, 0,013 e 0,012. Sinal fraco. Pelo MapBiomas, as candidatas são sobretudo lavoura
   temporária (36,6%) e pastagem (34,4%), e 36,5% do café cai em "dossel
   fechado". O app e o chat mostram essa concordância.

## Erro encontrado

A regra temporal original (|Δ NDVI| ≤ 0,25) rejeitava 65% das candidatas de
agosto contra fevereiro. Tratei como erro: na chuva a vegetação sobe +0,15 em
mediana, e passei a descontar essa mediana. Escolhi a variante porque mantinha
83% das candidatas. **O critério era circular**: medi quanto a regra mantinha,
não se ela acertava. Contra o MapBiomas, a original dá 25,6 ha e precisão 0,096;
a corrigida, 109 ha e 0,059; IoU 0,037 × 0,044, dentro do ruído. O café do
MapBiomas varia como a vegetação da cena e as candidatas sobem +0,14 a mais,
então a rejeição podia estar certa. Ancorar na mata (Δ no p5–p95 da mata) deixa
1,9 ha e IoU 0. Mantive a regra do app, que tem mais revocação (0,15 × 0,06),
porque o produto é triagem para conferência.

## Limitações

- Índice de vegetação sozinho não comprova café. "Vigor intermediário" também
  pega lavoura temporária, pasto bem formado e borda de mata.
- Limiares ajustados numa cena seca do Sul de MG (outubro a março recebem
  aviso); sem SWIR nem red-edge; SCL a 20 m.
- Agosto é colheita e poda no Sul de MG: talhão colhido, recepado ou esqueletado
  perde vigor e pode cair em "solo e vegetação rala". Lavoura de inverno irrigada
  (pivô) tem vigor intermediário em agosto e entra como candidata.
- Não há acurácia: os números do app são áreas e concordâncias.

## Fontes (conferir cada link antes de entregar)

1. Moreira, Adami, Rudorff (2004), *Pesq. Agropec. Bras.* 39(3). doi:10.1590/S0100-204X2004000300004 [VERIFICAR]
2. Índices: Rouse et al. (1974), NDVI, ntrs.nasa.gov/citations/19740022614; McFeeters (1996), NDWI, doi:10.1080/01431169608948714; Huete (1988), SAVI, doi:10.1016/0034-4257(88)90106-X (NDWI e SAVI: só metadados) [VERIFICAR]
3. Otsu (1979), *IEEE TSMC* 9(1). doi:10.1109/TSMC.1979.4310076 (só metadados) [VERIFICAR]
4. Sousa et al., Mapeamento de áreas cafeeiras do Sul de MG: Machado e Três Pontas, EPAMIG/Embrapa. alice.cnptia.embrapa.br/alice/bitstream/doc/880317/1/Mapeamentodeareascafeeiras.pdf [VERIFICAR]
5. Trindade et al. (2024), Anais IFSULDEMINAS. josif.ifsuldeminas.edu.br/ojs/index.php/anais/article/view/2236 [VERIFICAR]
6. Alves, Volpato, Campos (2021), Embrapa Café, Documentos 13. infoteca.cnptia.embrapa.br/infoteca/handle/doc/1134278 [VERIFICAR]
7. Souza Jr. et al. (2020), *Remote Sensing* 12(17), 2735. doi:10.3390/rs12172735. Dados: brasil.mapbiomas.org/downloads/mapas-para-download-geotiff/ [VERIFICAR]
8. Copernicus, Sentinel Data Legal Notice. sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice [VERIFICAR]
9. ESA SentiWiki, S2 Processing. sentiwiki.copernicus.eu/web/s2-processing [VERIFICAR]
10. Google, Gemini API Additional Terms. ai.google.dev/gemini-api/terms [VERIFICAR]
11. openfreemap.org; openstreetmap.org/copyright [VERIFICAR]
