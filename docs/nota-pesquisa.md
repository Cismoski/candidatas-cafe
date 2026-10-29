# Nota de pesquisa: áreas candidatas a café em Sentinel-2 (Guaxupé, MG)

Gabriel Cismoski, outubro de 2026. Números brutos e medições: `docs/research/`.

## Problema e método escolhido

O kit é um recorte Sentinel-2 L2A de 16/08/2025 com 512 × 512 px a 10 m:
bandas B02, B03, B04 e B08, mais a SCL, sem rótulos. Sem verdade de campo, o
produto honesto é um mapa de **áreas candidatas**, feito com regras
explicáveis, e não uma classificação com acurácia.

Para cada imagem enviada, o método:

1. converte para reflectância e usa a SCL só como máscara de qualidade;
2. calcula NDVI, NDWI e SAVI [2];
3. exclui:
    - água (NDWI > 0);
    - solo e vegetação rala (NDVI < 0,45);
    - dossel fechado, com o limiar de Otsu [3] sobre o NDVI da vegetação;
    - uma faixa de 10 m em volta dos núcleos de mata.
4. aplica abertura morfológica, descarta manchas abaixo de 0,5 ha e gera
   polígonos com área calculada em UTM.

O limiar de Otsu só é aceito se cair em [0,65; 0,80] e com η ≥ 0,70; senão,
vale 0,72. Com uma segunda data, o pixel precisa continuar vegetado e variar no
máximo 0,25 de NDVI, descontada a variação sazonal da cena. Os limiares ficam em
`backend/config/classification.yaml` e são gravados em cada resultado.

**Justificativa.** Num estudo com Landsat em Aguanil (MG), o período seco foi
a melhor época para mapear café, e o NIR foi a banda que melhor o separou de
pastagem e mata [1]. Na seca, o pasto perde vigor e a mata segue fechada; o
café fica no meio. É uma hipótese de separabilidade, não uma prova: a
literatura registra confusão com mata e usa conferência visual ou em campo
[1][4][5].

## Alternativas consideradas

**A. Classificação supervisionada** (RF ou KNN por objetos), com rótulos do
MapBiomas fora do recorte. É a abordagem da Embrapa Café: GEOBIA + KNN com as
mesmas 4 bandas do Sentinel-2 [6]. Também foi usada com RF em Nova Resende [5].
Descartada por três motivos:

- os rótulos viriam de um mapa a 30 m, com erros próprios;
- sem amostras independentes, a avaliação seria circular;
- cada polígono fica mais difícil de explicar. Fica para quando houver dados de campo.

**B. Usar o MapBiomas como resposta** (classe 46, Café) [7]. Não processa a
imagem enviada. Além disso, é anual, tem 30 m e não cobre imagens de fora do
Brasil. Virou **camada de referência**: cada análise mede a concordância com
ele, sem chamá-la de acurácia.

## Origem e condições de uso

- **Sentinel-2 L2A** via Earth Search (`sentinel-2-c1-l2a`): a cena do kit e uma
  adicional de 17/02/2025, na mesma órbita. A licença Copernicus permite
  modificar e redistribuir com a atribuição "Contains modified Copernicus
  Sentinel data 2025" [8], que aparece no app. O recorte adicional sai de
  `scripts/baixar_cena.py`, sem reamostragem; aplicado à cena do kit, ele
  reproduz o kit pixel a pixel, com mesmo transform, CRS e data. As classes da
  SCL seguem a tabela da ESA [9].
- **MapBiomas Coleção 11**: CC BY 4.0, com citação [7].
- **Gemini** (nível gratuito, opcional): os termos permitem ao Google usar as
  entradas e mostrá-las a revisores humanos [10]. O modelo recebe o resumo
  numérico, a pergunta e as últimas mensagens, sem nome nem e-mail, e a
  interface pede para não escrever dados pessoais. Uma guarda no backend rejeita
  respostas com percentuais, valores com unidade ou números acima de 12 que não
  estejam no resultado.
- **Mapa base**: OpenFreeMap, com dados OpenStreetMap (ODbL); a atribuição com
  link aparece no mapa [11].

## Como verifiquei

1. **Código.** Testes com cenas sintéticas de resposta conhecida: valor-limite,
   propriedade (Hypothesis) e mutação. Na cena do kit, os 90 polígonos do
   GeoJSON são válidos.
2. **Entre datas.** As candidatas de agosto e as de fevereiro concordam pouco
   (IoU 0,05), e 76% das de agosto viram dossel fechado na chuva. Com uma data
   só, o resultado depende da estação.
3. **Referência independente.** Contra o café do MapBiomas 2025, o IoU é 0,038
   (agosto) e 0,044 (agosto + fevereiro). Pelo MapBiomas, nossas candidatas são
   sobretudo lavoura temporária (36,6%) e pastagem (34,4%), e 36,5% do café do
   MapBiomas cai em "dossel fechado". Essa concordância baixa aparece no app e
   no chat.

## Erro encontrado

A regra temporal original rejeitava 65% das candidatas de agosto quando a
segunda data era fevereiro. Na chuva, a vegetação da cena inteira sobe +0,15
de NDVI em mediana, e as candidatas, +0,29. A regra confundia estação com
mudança de uso. A correção desconta a mediana do Δ da vegetação da cena.
Comparei cinco variantes; com a escolhida, a regra mantém 83% das candidatas.
Há um teste de regressão.

## Limitações

- Índice de vegetação sozinho não comprova café. "Vigor intermediário" também
  pega lavoura temporária, pasto bem formado e borda de mata.
- Os limiares foram ajustados numa cena seca do Sul de MG. Imagens de outubro
  a março recebem aviso.
- Sem SWIR nem red-edge, e a SCL tem 20 m.
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
