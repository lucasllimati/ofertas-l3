# Banco local de ofertas ADIE (POC)

Este banco SQLite guarda produtos, lojas, ofertas e benefícios promocionais. A POC inclui o GTA VI para PS5 da Amazon, usando os dados visíveis na captura enviada.

## Inicialização

O arquivo `adie.sqlite` é o banco pronto para consulta. Para recriá-lo, crie um banco SQLite vazio e execute, nesta ordem:

1. `schema.sql`
2. `seed.sql`

Exemplo com a CLI do SQLite:

```text
sqlite3 adie.sqlite ".read schema.sql" ".read seed.sql"
```

## Consulta de validação

Consulte `offer_validation` para ver o desconto calculado e o resultado da regra padrão de 15%:

```sql
SELECT product_name, store_name, original_price, promotional_price,
       discount_pct, rule_status, market_value_assessment, poc_approved
FROM offer_validation;
```

O `rule_status` segue o limite configurado: a oferta da POC fica `REJECTED_LOW_DISCOUNT`, pois a página exibia 7% OFF. Separadamente, `poc_approved = 1` e `market_value_assessment = 'BELOW_MARKET_VALUE'` registram a hipótese manual pedida para a demonstração — isso não significa que o desconto ou o preço de mercado foram verificados.

O preço original de R$ 449,90 é uma estimativa derivada do percentual exibido, não um preço anterior confirmado. Os benefícios COMANOAP e PRIMEGAME5 ficam registrados separadamente, sem presumir que podem ser acumulados. Confirme preços, condições e elegibilidade no checkout antes de divulgar.

O banco é local ao dispositivo; não está hospedado nem sincronizado entre usuários.
