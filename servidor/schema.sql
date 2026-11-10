-- Banco de licenças do PlayPronto (Cloudflare D1 / SQLite)
CREATE TABLE IF NOT EXISTS licencas (
  chave    TEXT PRIMARY KEY,
  email    TEXT NOT NULL,
  nome     TEXT,
  origem   TEXT,              -- hotmart | kiwify | manual
  pedido   TEXT UNIQUE,       -- código da venda (evita duplicar)
  status   TEXT NOT NULL DEFAULT 'ativa',  -- ativa | bloqueada
  max_pcs  INTEGER NOT NULL DEFAULT 2,
  criada   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_licencas_email ON licencas(email);

CREATE TABLE IF NOT EXISTS ativacoes (
  chave    TEXT NOT NULL,
  maquina  TEXT NOT NULL,
  nome_pc  TEXT,
  criada   INTEGER NOT NULL,
  visto    INTEGER NOT NULL,
  PRIMARY KEY (chave, maquina)
);

CREATE TABLE IF NOT EXISTS testes (
  maquina  TEXT PRIMARY KEY,
  usadas   INTEGER NOT NULL DEFAULT 0,
  criada   INTEGER NOT NULL
);
