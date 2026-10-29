"""Camada HTTP: middlewares, schemas e rotas.

Persistência, arquivos, fila, identidade e modelo de chat chegam pelos ports
(app/ports.py, via Services). Validação de upload e emissão do JWT são funções
da própria aplicação, chamadas direto.
"""
