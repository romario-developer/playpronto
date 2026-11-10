# Servidor de licenças do PlayPronto

Cloudflare Worker + banco D1. O plano grátis da Cloudflare (100 mil acessos/dia) sobra.

## Como funciona

1. Cliente compra na Hotmart ou Kiwify → a plataforma avisa este servidor (webhook) → a licença é criada
   (e enviada por e-mail, se o Resend estiver configurado).
2. No REAPER o cliente clica em **Ativar licença** e cola a chave `PLAY-XXXX-XXXX-XXXX-XXXX`.
3. O servidor confere a chave, registra o PC (máx. 2) e devolve um **token assinado** (Ed25519).
4. O app confere a assinatura localmente: funciona **offline por até 30 dias**; com internet renova sozinho.
5. Reembolso / chargeback → a licença é bloqueada e para de funcionar na próxima renovação.
6. Sem licença: **3 músicas grátis por computador**, contadas no servidor.

## Segredos (pasta `.chaves/`, fora do git)

| Arquivo | Para que serve |
|---|---|
| `privada_pkcs8.b64` | Assina as licenças. **Se vazar, qualquer um gera licença.** |
| `publica.b64` | Vai dentro do app (`licenca.py`, `CHAVE_PUBLICA`). |
| `admin_token.txt` | Senha do `admin.py`. |

**Faça backup da pasta `.chaves`** (gerenciador de senhas ou pendrive guardado). Ela não vai para o GitHub.
Se perder a chave privada, é preciso gerar outra e lançar uma versão nova do app.

## Publicar (uma vez só)

Dentro da pasta `servidor`:

```bash
npm install
npx wrangler login
npx wrangler d1 create playpronto
```

Copie o `database_id` que aparecer para o `wrangler.toml`. Depois:

```bash
npx wrangler d1 execute playpronto --remote --file schema.sql
npx wrangler secret put LICENCA_PRIVADA
npx wrangler secret put ADMIN_TOKEN
npx wrangler deploy
```

(nos dois `secret put`, cole o conteúdo de `.chaves/privada_pkcs8.b64` e `.chaves/admin_token.txt`.)

O deploy mostra o endereço, tipo `https://playpronto-licencas.SEU-USUARIO.workers.dev`.
Coloque esse endereço em `SERVIDOR_PADRAO` no `licenca.py` e gere o instalador de novo.

## Ligar a Hotmart / Kiwify

- **Hotmart:** Ferramentas → Webhook → URL `https://.../webhook/hotmart`, eventos *Compra aprovada*,
  *Compra completa*, *Reembolso*, *Chargeback*, *Cancelada*. Copie o **hottok** e rode
  `npx wrangler secret put HOTMART_HOTTOK`.
- **Kiwify:** Apps → Webhooks → URL `https://.../webhook/kiwify`, eventos *Compra aprovada*, *Reembolso*,
  *Chargeback*. Copie o **token** e rode `npx wrangler secret put KIWIFY_TOKEN`.

Depois de ligar, use o botão de **enviar teste** da plataforma e confira com `admin.py listar`.

## Enviar a chave por e-mail (opcional)

Crie conta grátis no [Resend](https://resend.com), verifique seu domínio, e:

```bash
npx wrangler secret put RESEND_API_KEY
```

E preencha `REMETENTE` no `wrangler.toml` (ex.: `PlayPronto <licenca@seudominio.com.br>`).
Sem isso, a licença é criada mesmo assim: veja com `admin.py listar` e envie você mesmo.

## Administrar

```bash
.venv\Scripts\python servidor\admin.py criar cliente@email.com "Nome do Cliente"
.venv\Scripts\python servidor\admin.py listar
.venv\Scripts\python servidor\admin.py liberar-pcs PLAY-XXXX-XXXX-XXXX-XXXX
.venv\Scripts\python servidor\admin.py bloquear PLAY-XXXX-XXXX-XXXX-XXXX
```

## Testar localmente

```bash
npx wrangler d1 execute playpronto --local --file schema.sql
npx wrangler dev --local
```

Crie `servidor/.dev.vars` com `LICENCA_PRIVADA=...`, `ADMIN_TOKEN=...`, `HOTMART_HOTTOK=...`, `KIWIFY_TOKEN=...`
e aponte o app com a variável de ambiente `PLAYPRONTO_SERVIDOR=http://127.0.0.1:8787`.
