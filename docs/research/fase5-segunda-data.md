# Fase 5: imagem adicional e regra temporal (evidências medidas)

Medido em 28/10/2026 com a API local (uploads reais, processamento no servidor),
recorte de Guaxupé (MG) do kit, 512 × 512 px a 10 m, EPSG:32723.

## Origem dos dados

| Uso | Cena (Earth Search, sentinel-2-c1-l2a) | Nuvem no recorte (SCL) |
|---|---|---|
| Kit (principal) | S2B_T23KLS_20250816T132502_L2A | 0,05% área escura; 0% nuvem |
| Adicional (no repositório) | S2B_T23KLS_20250217T132718_L2A | 0% nuvem, 0% sem dado |
| Só para esta comparação (fora do repositório) | S2A_T23KLS_20240816T132233_L2A | 0,06% área escura; 0% nuvem |

Escolha da cena de fevereiro:
- Mesmo satélite e mesma órbita relativa (R038) da cena do kit.
- 0,02% de nuvem no tile.
- Meio da estação chuvosa, seis meses depois da cena do kit, que é da seca.

Recorte feito com `scripts/baixar_cena.py`, que lê só a janela nos COGs públicos
e não reamostra. Procedência e SHA-256: `frontend/public/amostra/s2b_20250217_ATRIBUICAO.txt`.

**Verificação do recorte.** Rodei o script na cena do próprio kit. A saída ficou
idêntica ao `imagem_multiespectral.tif` e ao `qualidade_scl.tif` do kit
(`np.array_equal` nas 4 bandas e na SCL), com o mesmo transform, CRS e data.

## Resultados (pela API)

| Análise | Polígonos | Área candidata | Rejeitada pela regra temporal | Desconto sazonal |
|---|---|---|---|---|
| 16/08/2025 sozinha | 90 | 155,31 ha | — | — |
| 17/02/2025 sozinha | 91 | 192,49 ha | — | — |
| ago/2025 + fev/2025, regra antiga (Δ bruto) | 18 | 25,58 ha | 223,58 ha | — |
| ago/2025 + fev/2025, regra com desconto | 73 | 109,41 ha | 56,45 ha | +0,1457 (159.571 px) |
| ago/2025 + ago/2024, regra com desconto | 39 | 43,94 ha | 187,11 ha | −0,0336 (159.524 px) |

## Erro concreto encontrado: a regra temporal confundia sazonalidade com mudança

A regra original mantinha um pixel candidato se a outra data tivesse NDVI ≥ 0,45
e |ΔNDVI| ≤ 0,25. O comentário no código supunha que o café "sobe ~0,20 na chuva".

Medido nos pixels candidatos de ago/2025 contra fev/2025:
- ΔNDVI p5/p50/p95: +0,038 / +0,288 / +0,443.
- A regra mantinha só 34,6%.
- A vegetação da cena inteira também sobe: a mediana do Δ é +0,146 (+0,125 no
  dossel fechado).

A subida das candidatas era quase toda sazonal. A regra passou a comparar o Δ de
cada pixel com o Δ mediano da vegetação da cena (`seasonal_normalization`).

Alternativas medidas antes da escolha:

| Variante | Candidatas mantidas (fev/2025) | Candidatas mantidas (ago/2024) |
|---|---|---|
| Δ bruto (original) | 34,6% | 41,4% |
| Assimétrica (rejeita só queda > 0,25) | 98,6% | 43,3% |
| Δ − mediana da vegetação (escolhida) | 83,0% | 40,2% |
| Δ − mediana do dossel fechado | 77,6% | 40,2% |
| Δ − mediana de toda a terra | 91,7% | 40,2% |

Por que a mediana da vegetação:
- Mede exatamente o que se quer descontar, a variação sazonal da vegetação.
- A mediana é robusta às próprias candidatas, que são uma fração pequena dessa população.
- Usar toda a terra incluiria o solo exposto, que reverdece muito mais na chuva.

## Limitação medida: uma data só depende da estação

Comparando as análises de uma data só:
- Concordância espacial entre ago/2025 e fev/2025: IoU 0,05.
- Dos pixels candidatos em ago/2025, em fev/2025 76% viraram dossel fechado, 12%
  vegetação descartada e 11% continuaram candidatos.

Na chuva o café atinge NDVI de mata (limiar de Otsu em fev/2025: 0,77; η 0,744).
A hipótese "café = vigor intermediário" só vale na seca. A análise agora avisa
quando a imagem principal é de outubro a março.

## O que não dá para concluir

- **Ano anterior.** Entre ago/2024 e ago/2025 a vegetação da cena quase não muda
  (−0,034), mas as candidatas de 2025 estavam bem menos verdes em 2024 (mediana
  do Δ −0,13 depois do desconto). Pode ser poda (recepa, esqueletamento), plantio
  novo, efeito localizado da seca de 2024 ou outra cultura. Sem verdade de campo
  não há como separar essas causas. Os 43,94 ha não são "mais corretos" que os
  109,41 ha: cada segunda data testa uma hipótese diferente.
- **Acurácia.** Nenhum desses números é acurácia. Sem amostras de referência,
  só medem consistência entre datas.

## Reprodução

```bash
# recorte (da raiz do repositório)
uv run scripts/baixar_cena.py S2B_T23KLS_20250217T132718_L2A \
  --grade frontend/public/amostra/imagem_multiespectral.tif \
  --saida frontend/public/amostra --prefixo s2b_20250217 --acessado 2026-10-28
```

Na interface: "Cenas de exemplo", em seguida "16 ago 2025 (seca)", "17 fev 2025
(chuva)" ou "Duas datas".
