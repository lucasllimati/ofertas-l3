-- Preço "de" efetivamente exibido no post (já verificado no histórico); NULL = sem preço riscado.
ALTER TABLE content_item ADD COLUMN price_original_shown REAL;
