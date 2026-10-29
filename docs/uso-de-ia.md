# Uso de IA no desenvolvimento

## Ferramentas

| Ferramenta | Para quê |
|---|---|
| **Claude Code** (Claude Opus 5.5, no terminal) | Código do backend, do frontend e dos testes; scripts; documentação; medições com dados reais |
| Subagentes do Claude Code | Pesquisa de fontes, planos gratuitos e métodos alternativos; um revisor independente no papel de "staff engineer" ao fim de cada fase |
| Plugin `frontend-design` | Direção visual da interface (paleta, tipografia, layout) |
| Claude in Chrome | Conferir telas no navegador real (desktop e celular) |
| **Google Gemini** (no produto, opcional) | Respostas do chat em tempo de execução. Não foi usado para desenvolver |

Nenhum modelo de visão ou classificação pré-treinado foi usado no processamento:
o método é por regras, escrito e testado aqui.

## Divisão de trabalho

**Eu decidi:**
- os requisitos e a ordem das fases:
  1. pipeline;
  2. API e segurança;
  3. frontend;
  4. chat;
  5. segunda data;
  6. deploy;
  7. documentação;
- as escolhas de arquitetura:
  - Cloudflare Pages no frontend;
  - JWT Bearer como decisão específica do desafio (cookie httpOnly em produção);
  - bun no lugar de pnpm;
  - imagem Docker sem root e fixada por sha256;
  - circuit breaker no chat;
  - **desconto sazonal pela mediana da cena** na regra temporal, entre opções medidas
    (depois revisto: ver o erro "critério circular" abaixo);
  - **MapBiomas como camada de referência**, e não como segundo método, depois da pesquisa de alternativas.

**A IA fez:**
- propôs um plano curto antes de cada fase, que eu aprovei ou ajustei;
- escreveu o código, os testes e os documentos;
- rodou as medições.

Eu revisei o código e preciso conseguir explicar cada decisão. Os commits
trazem a coautoria.

## Como validei as entregas

1. **Testes como critério de pronto.**
   - Valor-limite, propriedade (Hypothesis), cobertura de ramos e mutação no
     processamento. Os números estão no README.
   - Em regra, cada bug encontrado virou um teste de regressão junto com a correção.
2. **Revisão independente por fase.** Ao fim de cada fase, um agente separado
   revisava o diff procurando:
   - casos de borda, condições de corrida e deadlocks;
   - idempotência, retries e lacunas de teste;
   - desvios do plano.
   Os achados foram corrigidos ou justificados antes do commit da fase.
3. **Dados reais, não só sintéticos.**
   - Rodei o pipeline nas cenas de agosto e fevereiro e medi a concordância com
     o MapBiomas.
   - Conferi que o script de recorte reproduz o kit pixel a pixel, com mesmo transform, CRS e data.
   - Medi memória e tempo da imagem Docker limitada como o plano gratuito.
4. **Fontes.** Regra combinada: citar só o que foi aberto durante a pesquisa,
   com link ou DOI. Cada fonte está marcada [VERIFICAR] para eu conferir antes
   de entregar. Os metadados do Otsu (1979) e do Souza Jr. et al. (2020) foram
   conferidos no Crossref.
5. **Deploy.** `scripts/smoke.py` checa de fora: 401, CORS, CSP e headers.

## Erros da IA que a validação pegou

Os erros abaixo foram encontrados durante o desenvolvimento. Eles mostram por
que nada foi aceito sem conferência. A coluna "Rastro" diz onde conferir;
"sessão" quer dizer que o erro foi pego antes de chegar a um commit.

| Erro | Como apareceu | Correção | Rastro |
|---|---|---|---|
| Relatar como prontos arquivos que não existiam | Conferência do disco na fase 2 | Passei a conferir arquivos e testes, não o relato | sessão |
| Premissa errada na regra temporal ("o café sobe ~0,20 na chuva") | Medição com a cena de fevereiro: a regra rejeitava 65% das candidatas | Desconto sazonal, escolhido entre cinco variantes medidas | commit 5e11a2f |
| A própria correção acima escolheu a variante por quanto ela *mantinha*, critério circular | Revisão de metodologia por outro agente | Variantes medidas contra o MapBiomas em script; a regra foi mantida, com a troca documentada ([nota](nota-pesquisa.md#erro-encontrado)) | `scripts/sensibilidade_temporal.py` |
| Contrato divergente entre módulos (`"temporal"` × `"two_dates"`) | Teste de ponta a ponta da segunda data | Contrato único e teste | commit e21f703 |
| Aritmética errada em testes (ex.: 50 × 20 em vez de 40 × 20) | O próprio teste falhou | Valores recalculados à mão | sessão |
| Timeouts do GDAL que somavam até 120 s | Revisão da fase 5 | Prazo total de 30 s e teste com servidor que não responde | commit 7a3d9bb |
| Números do agente de pesquisa sem script no repositório, e um IoU de 0,22 tratado como "teto" | Revisão da documentação | Marcados como não reproduzíveis; "teto" virou contexto | commit f735cd9 |
| Documento de deploy dizendo que a cota volta no timeout | Conferência no código antes do commit | Texto corrigido: a cota só volta se o envio falhar antes da fila | sessão |
| Verificação do deploy aceitando o `index.html` do Pages como se fosse a amostra | Revisão da fase 6 | Checagem do `content-type` | commit 2340dfb |
| Tela dizendo "pode entrar" com a API dormindo, quando o login falharia | Revisão da fase 6 | O login fica guardado e é concluído quando a API acorda | commit 0546d12 |
| Contrato do `summary.json` sem teste (renomear uma chave não quebrava nada) | Mutação: 69% no `pipeline.py` | Teste de contrato com as chaves fixadas e as estatísticas recalculadas; o módulo subiu para 81% | fase 7 |

## Limites do uso de IA neste projeto

- **Pesquisa:** o agente leu resumos e textos completos, mas algumas páginas
  bloquearam o acesso. Nesses casos a nota diz "só resumo" na pesquisa bruta
  (`docs/research/pesquisa-bruta.md`), e a conferência final das fontes é minha.
- **Revisões:** foram feitas por outro agente do mesmo modelo. São
  independentes do código revisado, mas não de vieses comuns ao modelo. Os
  testes e as medições são a evidência principal.
