// Servidor de licenças do PlayPronto (Cloudflare Worker + D1)
//
// App (público):
//   POST /v1/ativar        {chave, maquina, nome_pc}  -> {token}
//   POST /v1/renovar       {chave, maquina}           -> {token}
//   POST /v1/desativar     {chave, maquina}           -> {ok}
//   POST /v1/teste/status  {maquina}                  -> {restantes, total}
//   POST /v1/teste/usar    {maquina}                  -> {restantes, total}
// Vendas:
//   POST /webhook/hotmart  (header X-HOTMART-HOTTOK)
//   POST /webhook/kiwify?signature=...
// Admin (header Authorization: Bearer ADMIN_TOKEN):
//   POST /admin/criar      {email, nome, max_pcs?}    -> {chave}
//   GET  /admin/licencas?q=texto
//   POST /admin/bloquear   {chave}  /admin/desbloquear {chave}  /admin/liberar-pcs {chave}

const agora = () => Math.floor(Date.now() / 1000);

function json(dados, status = 200) {
  return new Response(JSON.stringify(dados), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
const erro = (codigo, msg, status = 400, extra = {}) => json({ erro: codigo, msg, ...extra }, status);

// ------------------------------------------------------------------ chaves e assinatura
const ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // sem 0/O/1/I (não confunde)

function novaChave() {
  const b = crypto.getRandomValues(new Uint8Array(16));
  let s = "";
  for (let i = 0; i < 16; i++) s += ALFABETO[b[i] % 32];
  return `PLAY-${s.slice(0, 4)}-${s.slice(4, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}`;
}

const normalizarChave = (c) => String(c || "").toUpperCase().replace(/\s+/g, "").trim();
const maquinaValida = (m) => typeof m === "string" && /^[a-f0-9]{32}$/.test(m);

function b64url(bytes) {
  let s = btoa(String.fromCharCode(...new Uint8Array(bytes)));
  return s.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

let _chavePrivada = null;
async function chavePrivada(env) {
  if (!_chavePrivada) {
    const der = Uint8Array.from(atob(env.LICENCA_PRIVADA.trim()), (c) => c.charCodeAt(0));
    _chavePrivada = await crypto.subtle.importKey("pkcs8", der, { name: "Ed25519" }, false, ["sign"]);
  }
  return _chavePrivada;
}

// token = base64url(json) + "." + base64url(assinatura Ed25519)
async function emitirToken(env, lic, maquina) {
  const dias = parseInt(env.VALIDADE_DIAS || "30", 10);
  const dados = {
    c: lic.chave, m: maquina, n: lic.nome || "", e: lic.email,
    iat: agora(), exp: agora() + dias * 86400,
  };
  const corpo = new TextEncoder().encode(JSON.stringify(dados));
  const sig = await crypto.subtle.sign({ name: "Ed25519" }, await chavePrivada(env), corpo);
  return `${b64url(corpo)}.${b64url(sig)}`;
}

// ------------------------------------------------------------------ licenças
async function buscarLicenca(env, chave) {
  return env.DB.prepare("SELECT * FROM licencas WHERE chave = ?").bind(chave).first();
}

async function criarLicenca(env, { email, nome, origem, pedido, max_pcs }) {
  if (pedido) {
    const ja = await env.DB.prepare("SELECT * FROM licencas WHERE pedido = ?").bind(pedido).first();
    if (ja) return { lic: ja, nova: false };
  }
  const lic = {
    chave: novaChave(), email: String(email).toLowerCase().trim(), nome: nome || "",
    origem: origem || "manual", pedido: pedido || null,
    max_pcs: max_pcs || parseInt(env.MAX_PCS_PADRAO || "2", 10), criada: agora(),
  };
  await env.DB.prepare(
    "INSERT INTO licencas (chave, email, nome, origem, pedido, status, max_pcs, criada) VALUES (?,?,?,?,?, 'ativa', ?, ?)"
  ).bind(lic.chave, lic.email, lic.nome, lic.origem, lic.pedido, lic.max_pcs, lic.criada).run();
  return { lic: { ...lic, status: "ativa" }, nova: true };
}

async function mudarStatusPorPedido(env, pedido, status) {
  if (!pedido) return;
  await env.DB.prepare("UPDATE licencas SET status = ? WHERE pedido = ?").bind(status, pedido).run();
}

async function enviarEmail(env, lic) {
  if (!env.RESEND_API_KEY || !env.REMETENTE) return false;
  const html = `<p>Olá${lic.nome ? ", " + lic.nome.split(" ")[0] : ""}!</p>
    <p>Obrigado por comprar o <b>PlayPronto</b>. Sua chave de licença é:</p>
    <p style="font-size:22px;font-family:monospace;background:#f4f4f4;padding:12px;display:inline-block">${lic.chave}</p>
    <p>No REAPER, abra o PlayPronto, clique em <b>Ativar</b> e cole a chave.
    Ela funciona em até ${lic.max_pcs} computadores.</p>`;
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "content-type": "application/json" },
    body: JSON.stringify({ from: env.REMETENTE, to: [lic.email], subject: "Sua licença do PlayPronto", html }),
  });
  return r.ok;
}

// ------------------------------------------------------------------ rotas do app
async function ativar(env, corpo) {
  const chave = normalizarChave(corpo.chave);
  const maquina = corpo.maquina;
  if (!maquinaValida(maquina)) return erro("pedido_invalido", "Identificação do computador inválida.");
  const lic = await buscarLicenca(env, chave);
  if (!lic) return erro("chave_invalida", "Chave não encontrada. Confira se copiou certinho.", 404);
  if (lic.status !== "ativa") return erro("bloqueada", "Esta licença está bloqueada. Fale com o suporte.", 403);

  const ja = await env.DB.prepare("SELECT 1 FROM ativacoes WHERE chave = ? AND maquina = ?").bind(chave, maquina).first();
  if (!ja) {
    const { results } = await env.DB.prepare("SELECT nome_pc FROM ativacoes WHERE chave = ? ORDER BY criada").bind(chave).all();
    if (results.length >= lic.max_pcs) {
      return erro("limite_pcs",
        `Esta licença já está ativa em ${lic.max_pcs} computadores (${results.map((r) => r.nome_pc || "?").join(", ")}). ` +
        "Desative em um deles ou fale com o suporte.", 409, { pcs: results.map((r) => r.nome_pc) });
    }
    await env.DB.prepare("INSERT INTO ativacoes (chave, maquina, nome_pc, criada, visto) VALUES (?,?,?,?,?)")
      .bind(chave, maquina, String(corpo.nome_pc || "").slice(0, 60), agora(), agora()).run();
  } else {
    await env.DB.prepare("UPDATE ativacoes SET visto = ? WHERE chave = ? AND maquina = ?").bind(agora(), chave, maquina).run();
  }
  return json({ token: await emitirToken(env, lic, maquina), nome: lic.nome, email: lic.email });
}

async function renovar(env, corpo) {
  const chave = normalizarChave(corpo.chave);
  const lic = await buscarLicenca(env, chave);
  if (!lic) return erro("chave_invalida", "Licença não encontrada.", 404);
  if (lic.status !== "ativa") return erro("bloqueada", "Esta licença foi bloqueada.", 403);
  const ja = await env.DB.prepare("SELECT 1 FROM ativacoes WHERE chave = ? AND maquina = ?").bind(chave, corpo.maquina).first();
  if (!ja) return erro("desativada", "Este computador foi desativado. Ative de novo.", 403);
  await env.DB.prepare("UPDATE ativacoes SET visto = ? WHERE chave = ? AND maquina = ?").bind(agora(), chave, corpo.maquina).run();
  return json({ token: await emitirToken(env, lic, corpo.maquina), nome: lic.nome, email: lic.email });
}

async function desativar(env, corpo) {
  await env.DB.prepare("DELETE FROM ativacoes WHERE chave = ? AND maquina = ?")
    .bind(normalizarChave(corpo.chave), corpo.maquina).run();
  return json({ ok: true });
}

async function teste(env, corpo, usar) {
  const maquina = corpo.maquina;
  if (!maquinaValida(maquina)) return erro("pedido_invalido", "Identificação do computador inválida.");
  const total = parseInt(env.TESTE_MUSICAS || "3", 10);
  let t = await env.DB.prepare("SELECT usadas FROM testes WHERE maquina = ?").bind(maquina).first();
  let usadas = t ? t.usadas : 0;
  if (usar) {
    if (usadas >= total) return erro("teste_acabou", "O teste grátis acabou.", 403, { restantes: 0, total, link: env.LINK_COMPRA || "" });
    usadas += 1;
    await env.DB.prepare(
      "INSERT INTO testes (maquina, usadas, criada) VALUES (?, ?, ?) ON CONFLICT(maquina) DO UPDATE SET usadas = excluded.usadas"
    ).bind(maquina, usadas, agora()).run();
  }
  return json({ restantes: Math.max(0, total - usadas), total, link: env.LINK_COMPRA || "" });
}

// ------------------------------------------------------------------ webhooks de venda
async function hotmart(env, req) {
  if (!env.HOTMART_HOTTOK || req.headers.get("x-hotmart-hottok") !== env.HOTMART_HOTTOK) {
    return erro("nao_autorizado", "hottok inválido", 401);
  }
  const b = await req.json();
  const ev = b.event || "";
  const d = b.data || {};
  const pedido = d.purchase?.transaction;
  if (["PURCHASE_APPROVED", "PURCHASE_COMPLETE"].includes(ev)) {
    const email = d.buyer?.email;
    if (!email || !pedido) return erro("dados_faltando", "sem e-mail ou transação");
    const { lic, nova } = await criarLicenca(env, { email, nome: d.buyer?.name, origem: "hotmart", pedido });
    if (nova) await enviarEmail(env, lic);
    return json({ ok: true, chave: lic.chave });
  }
  if (["PURCHASE_REFUNDED", "PURCHASE_CHARGEBACK", "PURCHASE_CANCELED", "PURCHASE_PROTEST"].includes(ev)) {
    await mudarStatusPorPedido(env, pedido, "bloqueada");
  }
  return json({ ok: true, ignorado: ev });
}

async function hmacSha1Hex(segredo, texto) {
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(segredo), { name: "HMAC", hash: "SHA-1" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(texto));
  return [...new Uint8Array(sig)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

async function kiwify(env, req, url) {
  const texto = await req.text();
  if (!env.KIWIFY_TOKEN || url.searchParams.get("signature") !== (await hmacSha1Hex(env.KIWIFY_TOKEN, texto))) {
    return erro("nao_autorizado", "assinatura inválida", 401);
  }
  const b = JSON.parse(texto);
  const status = b.order_status || "";
  const pedido = b.order_id;
  if (status === "paid") {
    const email = b.Customer?.email;
    if (!email || !pedido) return erro("dados_faltando", "sem e-mail ou pedido");
    const { lic, nova } = await criarLicenca(env, { email, nome: b.Customer?.full_name, origem: "kiwify", pedido });
    if (nova) await enviarEmail(env, lic);
    return json({ ok: true, chave: lic.chave });
  }
  if (["refunded", "chargedback"].includes(status)) await mudarStatusPorPedido(env, pedido, "bloqueada");
  return json({ ok: true, ignorado: status });
}

// ------------------------------------------------------------------ admin
async function admin(env, req, url) {
  const tok = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!env.ADMIN_TOKEN || tok !== env.ADMIN_TOKEN) return erro("nao_autorizado", "token de admin inválido", 401);
  const rota = url.pathname.replace("/admin/", "");
  if (req.method === "GET" && rota === "licencas") {
    const q = `%${url.searchParams.get("q") || ""}%`;
    const { results } = await env.DB.prepare(
      `SELECT l.*, (SELECT COUNT(*) FROM ativacoes a WHERE a.chave = l.chave) AS pcs
       FROM licencas l WHERE l.email LIKE ? OR l.chave LIKE ? OR l.nome LIKE ? ORDER BY l.criada DESC LIMIT 200`
    ).bind(q, q, q).all();
    return json({ licencas: results });
  }
  const b = await req.json().catch(() => ({}));
  const chave = normalizarChave(b.chave);
  if (rota === "criar") {
    if (!b.email) return erro("dados_faltando", "informe o e-mail");
    const { lic } = await criarLicenca(env, { email: b.email, nome: b.nome, origem: "manual", max_pcs: b.max_pcs });
    if (b.enviar_email) await enviarEmail(env, lic);
    return json({ chave: lic.chave, email: lic.email, max_pcs: lic.max_pcs });
  }
  if (rota === "bloquear" || rota === "desbloquear") {
    await env.DB.prepare("UPDATE licencas SET status = ? WHERE chave = ?").bind(rota === "bloquear" ? "bloqueada" : "ativa", chave).run();
    return json({ ok: true });
  }
  if (rota === "liberar-pcs") {
    await env.DB.prepare("DELETE FROM ativacoes WHERE chave = ?").bind(chave).run();
    return json({ ok: true });
  }
  return erro("rota_desconhecida", "rota de admin desconhecida", 404);
}

// ------------------------------------------------------------------ roteador
export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    try {
      if (req.method === "GET" && url.pathname === "/") return json({ servico: "PlayPronto licenças", ok: true });
      if (url.pathname.startsWith("/admin/")) return await admin(env, req, url);
      if (req.method !== "POST") return erro("metodo", "use POST", 405);
      if (url.pathname === "/webhook/hotmart") return await hotmart(env, req);
      if (url.pathname === "/webhook/kiwify") return await kiwify(env, req, url);
      const corpo = await req.json().catch(() => ({}));
      switch (url.pathname) {
        case "/v1/ativar": return await ativar(env, corpo);
        case "/v1/renovar": return await renovar(env, corpo);
        case "/v1/desativar": return await desativar(env, corpo);
        case "/v1/teste/status": return await teste(env, corpo, false);
        case "/v1/teste/usar": return await teste(env, corpo, true);
      }
      return erro("rota_desconhecida", "rota desconhecida", 404);
    } catch (e) {
      console.error(e);
      return erro("interno", "Erro no servidor de licenças. Tente de novo em instantes.", 500);
    }
  },
};
