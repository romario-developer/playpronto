--[[
  PlayPronto - playback com IA direto no REAPER
  Link do YouTube (ou arquivo do PC) -> IA separa os instrumentos -> abre pronto no REAPER:
    GUIA - Original (mudo) | GUIA - Voz (mudo) | CLICK | pasta com os instrumentos
]]

local NOME = "PlayPronto"

-- pasta do script = ...\CRIAR VS\reaper  ->  criador fica na pasta de cima
local AQUI = debug.getinfo(1, "S").source:sub(2):match("^(.*)[\\/]") or "."
local PASTA_CRIADOR = AQUI:match("^(.*)[\\/]") or AQUI
-- instalado: Python portátil em \python | desenvolvimento: \.venv
local PYTHON = PASTA_CRIADOR .. [[\python\python.exe]]
do
  local f = io.open(PYTHON, "rb")
  if f then f:close() else PYTHON = PASTA_CRIADOR .. [[\.venv\Scripts\python.exe]] end
end
local SCRIPT = PASTA_CRIADOR .. [[\criar_vs.py]]
local TMP    = PASTA_CRIADOR .. [[\VS\_reaper]]
local LOGO   = AQUI .. [[\icones\logo.png]]

------------------------------------------------------------------ util
local function existe(p)
  if reaper.file_exists then return reaper.file_exists(p) end -- entende acentos no nome
  local f = io.open(p, "rb"); if f then f:close(); return true end; return false
end
local function ler(p) local f = io.open(p, "rb"); if not f then return nil end; local s = f:read("*a"); f:close(); return s end
local function gravar(p, s) local f = io.open(p, "wb"); f:write(s); f:close() end
local function aspas(s) return '"' .. s .. '"' end
local function trim(s) return (s or ""):gsub("^%s+", ""):gsub("%s+$", "") end

local function cfg(k, padrao) local v = reaper.GetExtState(NOME, k); if v == "" then return padrao end; return v end
local function set_cfg(k, v) reaper.SetExtState(NOME, k, v, true) end

if not existe(PYTHON) or not existe(SCRIPT) then
  reaper.ShowMessageBox("Não achei o criador em:\n" .. PASTA_CRIADOR ..
    "\n\nRode o instalador do PlayPronto de novo.", NOME, 0)
  return
end

------------------------------------------------------------------ estado
local E = {
  tela = "inicio",          -- inicio | processando | pronto | erro
  modo = cfg("modo", "aba"),-- aba (abre em nova aba) | atual (insere no cursor)
  tipo = cfg("tipo", "vs"), -- vs (instrumentos separados) | playback (só tira a voz)
  mp3 = nil,
  bpm = "",
  tom = 0,                  -- semitons (-12 a +12); bateria e percussão não mudam
  etapa = "", porc = nil, inicio = 0, titulo = "", msg = "",
  res = nil, log = nil, pid = nil, posicao = 0,
  lic = { tipo = "carregando" },  -- licenca | teste | sem_licenca | erro | carregando
  lic_job = nil,
}
local janela = true
local LICENCA_PY = PASTA_CRIADOR .. [[\licenca.py]]

------------------------------------------------------------------ licença (roda licenca.py escondido)
local function rodar_escondido(args, res, log)
  reaper.RecursiveCreateDirectory(TMP, 0)
  local id = os.date("%H%M%S") .. "_" .. math.random(1000, 9999)
  local bat = TMP .. "\\lic_" .. id .. ".bat"
  local vbs = TMP .. "\\lic_" .. id .. ".vbs"
  gravar(bat, "@echo off\r\nchcp 65001 >nul\r\nset PYTHONUTF8=1\r\n" .. aspas(PYTHON) .. " " .. args ..
              " > " .. aspas(log) .. " 2>&1\r\ndel \"%~dp0lic_" .. id .. ".vbs\"\r\ndel \"%~f0\"\r\n")
  gravar(vbs, 'CreateObject("WScript.Shell").Run """' .. bat .. '""", 0, False\r\n')
  reaper.ExecProcess('wscript.exe "' .. vbs .. '"', -1)
end

local function licenca(acao, chave)
  local id = math.random(100000, 999999)
  local res = TMP .. "\\licres_" .. id .. ".txt"
  local args = aspas(LICENCA_PY) .. " --" .. acao
  if chave then args = args .. " " .. chave end
  rodar_escondido(args .. " --saida " .. aspas(res), res, TMP .. "\\liclog.txt")
  E.lic_job = { acao = acao, res = res, inicio = reaper.time_precise() }
  if acao == "status" and E.lic.tipo ~= "licenca" and E.lic.tipo ~= "teste" then E.lic = { tipo = "carregando" } end
end

local function ler_tabela(txt)
  local t = {}
  for linha in txt:gmatch("[^\r\n]+") do
    local k, v = linha:match("^(%u+)\t(.*)$")
    if k then t[k:lower()] = v end
  end
  return t
end

local function verificar_licenca()
  local j = E.lic_job
  if not j then return end
  local txt = ler(j.res)
  if not (txt and txt:find("\nFIM") or (txt and txt:find("^FIM"))) then
    if reaper.time_precise() - j.inicio > 40 then
      E.lic_job = nil
      E.lic = { tipo = "erro", msg = "O verificador de licença não respondeu." }
    end
    return
  end
  os.remove(j.res)
  E.lic_job = nil
  local t = ler_tabela(txt)
  if j.acao == "status" then
    t.restantes = tonumber(t.restantes)
    E.lic = t
  elseif j.acao == "ativar" then
    if t.tipo == "ativada" then
      reaper.ShowMessageBox("Licença ativada! Obrigado por comprar o PlayPronto." ..
        ((t.nome or "") ~= "" and ("\n\nLicenciado para: " .. t.nome) or ""), NOME, 0)
      if E.tela == "licenca" then E.tela = "inicio" end
    else
      reaper.ShowMessageBox("Não consegui ativar:\n\n" .. (t.msg or "erro desconhecido"), NOME, 0)
    end
    licenca("status")
  elseif j.acao == "desativar" then
    reaper.ShowMessageBox(t.msg or "Pronto.", NOME, 0)
    licenca("status")
  end
end

local function pedir_chave()
  local ok, r = reaper.GetUserInputs(NOME .. " - ativar licença", 1,
    "Chave de licença (PLAY-....):,extrawidth=260", "")
  if not ok then return end
  local chave = trim(r):upper():gsub("[^A-Z0-9%-]", "")
  if not chave:match("^PLAY%-%w%w%w%w%-%w%w%w%w%-%w%w%w%w%-%w%w%w%w$") then
    reaper.ShowMessageBox("Chave inválida. Ela tem este formato:\nPLAY-XXXX-XXXX-XXXX-XXXX", NOME, 0)
    return
  end
  licenca("ativar", chave)
end

local function menu_licenca()
  if E.lic_job then return end
  if E.lic.tipo == "licenca" then
    local r = reaper.ShowMessageBox("PlayPronto licenciado" ..
      ((E.lic.nome or "") ~= "" and (" para " .. E.lic.nome) or "") ..
      ((E.lic.email or "") ~= "" and ("\n" .. E.lic.email) or "") ..
      "\n\nQuer DESATIVAR este computador?\n(libera a vaga para usar a licença em outro PC)", NOME, 4)
    if r == 6 then licenca("desativar") end
  else
    pedir_chave()
  end
end

local function abrir_link(u)
  if u and u ~= "" then reaper.ExecProcess('cmd.exe /C start "" "' .. u .. '"', -1) end
end

------------------------------------------------------------------ rodar o Python separado do REAPER
local function iniciar(entrada)
  entrada = trim(entrada)
  if entrada == "" then return end
  if E.lic.tipo == "sem_licenca" then -- nem começa: vai direto para a tela de licença
    E.msg = E.lic.msg or "Ative sua licença para continuar."
    E.tela = "licenca"
    return
  end
  reaper.RecursiveCreateDirectory(TMP, 0)
  local id = os.date("%Y%m%d_%H%M%S") .. "_" .. math.random(100, 999)
  E.res = TMP .. "\\res_" .. id .. ".txt"
  E.log = TMP .. "\\log_" .. id .. ".txt"
  local bat = TMP .. "\\run_" .. id .. ".bat"
  local vbs = TMP .. "\\run_" .. id .. ".vbs"

  local linha = aspas(PYTHON) .. " -u " .. aspas(SCRIPT) .. " " .. aspas(entrada:gsub("%%", "%%%%")) ..
                " --resultado " .. aspas(E.res) .. " --modo " .. E.tipo
  if E.bpm ~= "" then linha = linha .. " --bpm " .. E.bpm end
  if E.tom ~= 0 then linha = linha .. " --tom " .. E.tom end
  gravar(bat, "@echo off\r\nchcp 65001 >nul\r\nset PYTHONUTF8=1\r\nset PYTHONIOENCODING=utf-8\r\n" ..
              linha .. " > " .. aspas(E.log) .. " 2>&1\r\n")
  -- VBS roda o .bat escondido e totalmente separado do REAPER (não morre se fechar o REAPER)
  gravar(vbs, 'CreateObject("WScript.Shell").Run """' .. bat .. '""", 0, False\r\n')
  reaper.ExecProcess('wscript.exe "' .. vbs .. '"', -1)

  E.tela, E.etapa, E.porc, E.pid = "processando", "Iniciando...", nil, nil
  E.titulo = entrada:match("[^\\/]+$") or entrada
  if entrada:match("^https?://") then E.titulo = "YouTube" end
  E.inicio = reaper.time_precise()
  E.posicao = reaper.GetCursorPosition()
end

-- deixa o link limpo: tira playlist/rádio (&list=..., &start_radio=...)
local function limpar_link(u)
  u = trim(u)
  local id = u:match("youtube%.com/watch%?.-v=([%w_%-]+)") or u:match("youtube%.com/shorts/([%w_%-]+)")
          or u:match("youtu%.be/([%w_%-]+)")
  if id then return "https://www.youtube.com/watch?v=" .. id, id end
  return u, nil
end

-- link copiado (precisa da extensão SWS para ler a área de transferência)
local clip_cache, clip_t = nil, -10
local function link_copiado()
  if not reaper.CF_GetClipboard then return nil end
  if reaper.time_precise() - clip_t > 0.7 then
    clip_t = reaper.time_precise()
    local c = trim(reaper.CF_GetClipboard(""))
    clip_cache = c:match("^https?://%S+$") and c or nil
  end
  return clip_cache
end

local function colar_link()
  clip_t = -10
  local c = link_copiado()
  if c then iniciar(limpar_link(c)); return end -- tem link copiado: vai direto
  local ok, r = reaper.GetUserInputs(NOME, 1, "Link do YouTube:,extrawidth=420", "")
  if ok and trim(r) ~= "" then iniciar(limpar_link(r)) end
end

local function escolher_arquivo()
  local ok, f = reaper.GetUserFileNameForRead("", NOME .. " - escolha a música", "*.mp3;*.wav;*.flac;*.m4a;*.ogg")
  if ok then iniciar(f) end
end

local function mudar_bpm()
  local ok, r = reaper.GetUserInputs(NOME, 1, "BPM (vazio = detectar sozinho):", E.bpm)
  if not ok then return end
  r = trim(r)
  if r == "" or tonumber(r) then E.bpm = r
  else reaper.ShowMessageBox("BPM inválido: " .. r, NOME, 0) end
end

local function tom_txt() return E.tom == 0 and "0" or string.format("%+d", E.tom) end

local function mudar_tom()
  local ok, r = reaper.GetUserInputs(NOME, 1,
    "Tom em semitons (-12 a +12; 0 = original):,extrawidth=60", tom_txt())
  if not ok then return end
  local n = tonumber((trim(r):gsub("^%+", "")))
  if n and n == math.floor(n) and n >= -12 and n <= 12 then E.tom = math.floor(n)
  else reaper.ShowMessageBox("Tom inválido: " .. r .. "\nUse um número inteiro de -12 a +12.", NOME, 0) end
end

local function cancelar()
  if E.pid then reaper.ExecProcess("taskkill /PID " .. E.pid .. " /T /F", 2000) end
  E.tela = "inicio"
end

------------------------------------------------------------------ colocar no REAPER
local function cor(r, g, b) return reaper.ColorToNative(r, g, b) | 0x1000000 end

local function ler_resultado(txt)
  local d = { tracks = {} }
  for linha in txt:gmatch("[^\r\n]+") do
    local c = {}
    for campo in (linha .. "\t"):gmatch("(.-)\t") do c[#c + 1] = campo end
    if c[1] == "BPM" then d.bpm = tonumber(c[2])
    elseif c[1] == "TITULO" then d.titulo = c[2]
    elseif c[1] == "RPP" then d.rpp = c[2]
    elseif c[1] == "MP3" then d.mp3 = c[2]
    elseif c[1] == "TRACK" or c[1] == "FOLDER" then d.tracks[#d.tracks + 1] = c end
  end
  return d
end

local function projeto_vazio()
  return reaper.CountTracks(0) == 0 and reaper.IsProjectDirty(0) == 0
end

local function abrir_em_aba(d)
  if not projeto_vazio() then reaper.Main_OnCommand(40859, 0) end -- nova aba de projeto
  reaper.Main_openProject("noprompt:" .. d.rpp)
end

local function inserir_no_cursor(d, pos)
  reaper.Undo_BeginBlock()
  reaper.PreventUIRefresh(1)
  if d.bpm and d.bpm > 0 then reaper.SetTempoTimeSigMarker(0, -1, pos, -1, -1, d.bpm, 4, 4, false) end
  local idx = reaper.CountTracks(0)
  for _, c in ipairs(d.tracks) do
    reaper.InsertTrackAtIndex(idx, true)
    local tr = reaper.GetTrack(0, idx); idx = idx + 1
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", c[2], true)
    if c[1] == "FOLDER" then
      reaper.SetMediaTrackInfo_Value(tr, "I_CUSTOMCOLOR", cor(tonumber(c[3]), tonumber(c[4]), tonumber(c[5])))
      reaper.SetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH", 1)
    else
      reaper.SetMediaTrackInfo_Value(tr, "I_CUSTOMCOLOR", cor(tonumber(c[4]), tonumber(c[5]), tonumber(c[6])))
      reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", tonumber(c[7]))
      reaper.SetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH", tonumber(c[8]))
      reaper.SetMediaTrackInfo_Value(tr, "D_VOL", tonumber(c[9]) or 1)
      local src = reaper.PCM_Source_CreateFromFile(c[3])
      if src then
        local item = reaper.AddMediaItemToTrack(tr)
        local take = reaper.AddTakeToMediaItem(item)
        reaper.SetMediaItemTake_Source(take, src)
        reaper.SetMediaItemInfo_Value(item, "D_POSITION", pos)
        reaper.SetMediaItemInfo_Value(item, "D_LENGTH", reaper.GetMediaSourceLength(src))
        reaper.GetSetMediaItemTakeInfo_String(take, "P_NAME", c[2], true)
      end
    end
  end
  reaper.AddProjectMarker2(0, false, pos, 0, d.titulo or NOME, -1, 0)
  reaper.PreventUIRefresh(-1)
  reaper.TrackList_AdjustWindows(false)
  reaper.UpdateArrange()
  reaper.Main_OnCommand(40047, 0) -- gera waveforms
  reaper.Undo_EndBlock(NOME .. ": " .. (d.titulo or ""), -1)
end

local function concluir(txt)
  local d = ler_resultado(txt)
  if E.modo == "aba" and d.rpp and existe(d.rpp) then abrir_em_aba(d)
  else inserir_no_cursor(d, E.posicao) end
  os.remove(E.res)
  E.titulo = d.titulo or ""
  E.mp3 = d.mp3
  if d.mp3 then
    E.msg = "Playback sem voz no Reaper + MP3 salvo na pasta"
  else
    E.msg = "BPM " .. (d.bpm or "?") .. "  •  guias Original e Voz entraram mutadas"
  end
  E.tela = "pronto"
  if not janela then reaper.ShowMessageBox("Pronto: " .. E.titulo .. "\n" .. E.msg, NOME, 0) end
  if E.lic.tipo == "teste" then licenca("status") end -- atualiza quantas músicas grátis restam
end

local function verificar()
  local log = E.log and ler(E.log)
  if log then
    E.pid = E.pid or log:match("PID:(%d+)")
    for e in log:gmatch(">> ([^\r\n]+)") do E.etapa = e end
    local t = log:match("Convertendo para WAV: ([^\r\n]+)")
    if t then E.titulo = t end
    E.porc = nil
    if E.etapa:find("Separando") then
      for p in log:gmatch("(%d+)%%|") do E.porc = tonumber(p) end
    elseif E.etapa:find("Baixando") then
      for p in log:gmatch("%[download%]%s+([%d%.]+)%%") do E.porc = math.floor(tonumber(p)) end
    end
  end
  local res = ler(E.res)
  if res and res:find("\nFIM") then concluir(res); return end
  if res and res:find("^ERRO") then
    E.msg = res:match("^ERRO\t([^\r\n]*)") or "erro desconhecido"
    local m = E.msg:match("^LICENCA|(.*)$")
    if m then E.msg = m; E.tela = "licenca"; licenca("status"); return end
    E.tela = "erro"; return
  end
  if log and log:find("Traceback") and reaper.time_precise() - E.inicio > 5 then
    E.msg = "O processo parou com erro."; E.tela = "erro"
  end
end

local verificar_base = verificar
verificar = function()
  verificar_base()
  if E.tela == "erro" and not janela then
    reaper.ShowMessageBox("Deu erro no PlayPronto:\n" .. E.msg .. "\n\nLog:\n" .. (E.log or ""), NOME, 0)
  end
end

------------------------------------------------------------------ desenho
local W, H = 440, 326
local mouse_antes = 0
local clique = false

local function fonte(n) gfx.setfont(n) end
local function rgb(r, g, b, a) gfx.set(r / 255, g / 255, b / 255, a or 1) end

local function texto(s, x, y, r, g, b) rgb(r, g, b); gfx.x, gfx.y = x, y; gfx.drawstr(s) end

local function caixa(x, y, w, h, raio, preenche)
  gfx.roundrect(x, y, w, h, raio, 1)
  if preenche then
    gfx.rect(x + 1, y + raio, w - 1, h - raio * 2 + 1, 1)
    gfx.rect(x + raio, y + 1, w - raio * 2 + 1, h - 1, 1)
    for i = 0, raio do -- cantos arredondados preenchidos
      local dx = raio - math.sqrt(raio * raio - (raio - i) ^ 2)
      gfx.line(x + dx, y + i, x + w - dx, y + i)
      gfx.line(x + dx, y + h - i, x + w - dx, y + h - i)
    end
  end
end

-- botão: retorna true quando clicado
local function botao(rot, x, y, w, h, principal, destaque)
  local sobre = gfx.mouse_x >= x and gfx.mouse_x <= x + w and gfx.mouse_y >= y and gfx.mouse_y <= y + h
  local apertado = sobre and (gfx.mouse_cap & 1) == 1
  if destaque and not principal then -- opção ligada (ex.: tom mudado): borda dourada
    rgb(245, 170, 35); caixa(x - 2, y - 2, w + 4, h + 4, 9, true)
  end
  if principal then
    if apertado then rgb(200, 130, 20) elseif sobre then rgb(255, 190, 60) else rgb(245, 170, 35) end
  else
    if apertado then rgb(45, 45, 52) elseif sobre then rgb(70, 70, 80) else rgb(55, 55, 63) end
  end
  caixa(x, y, w, h, 8, true)
  fonte(principal and 2 or 3)
  local tw, th = gfx.measurestr(rot)
  if principal then rgb(35, 20, 5) else rgb(230, 230, 235) end
  gfx.x, gfx.y = x + (w - tw) / 2, y + (h - th) / 2
  gfx.drawstr(rot)
  return sobre and clique
end

-- cartão de escolha (VS / Playback)
local function cartao(tit, sub, x, y, w, h, marcado)
  local sobre = gfx.mouse_x >= x and gfx.mouse_x <= x + w and gfx.mouse_y >= y and gfx.mouse_y <= y + h
  if marcado then rgb(245, 170, 35) else rgb(70, 70, 80) end
  caixa(x, y, w, h, 10, true)
  if marcado then rgb(60, 45, 25) elseif sobre then rgb(55, 55, 63) else rgb(42, 42, 48) end
  caixa(x + 2, y + 2, w - 4, h - 4, 9, true)
  fonte(2)
  local tw = gfx.measurestr(tit)
  if marcado then rgb(255, 200, 90) else rgb(230, 230, 235) end
  gfx.x, gfx.y = x + (w - tw) / 2, y + 9; gfx.drawstr(tit)
  fonte(3)
  tw = gfx.measurestr(sub)
  rgb(170, 170, 180); gfx.x, gfx.y = x + (w - tw) / 2, y + 31; gfx.drawstr(sub)
  return sobre and clique
end

local function cabecalho(sub)
  if gfx.loadimg and existe(LOGO) and not E.logo_ok then gfx.loadimg(1, LOGO); E.logo_ok = true end
  if E.logo_ok then gfx.x, gfx.y = 18, 16; gfx.blit(1, 0.75, 0) end
  fonte(1); texto("PlayPronto", 74, 18, 255, 255, 255)
  fonte(3); texto(sub, 74, 46, 160, 160, 170)
end

-- selo no canto: estado da licença (clicável)
local function selo_licenca()
  local L = E.lic
  local rot, cor_f, cor_t = "verificando...", { 50, 50, 58 }, { 150, 150, 160 }
  if E.lic_job and E.lic_job.acao ~= "status" then rot = "aguarde..."
  elseif L.tipo == "licenca" then rot, cor_f, cor_t = "✓ Licenciado", { 35, 70, 40 }, { 140, 230, 150 }
  elseif L.tipo == "teste" then
    rot, cor_f, cor_t = "Teste: " .. (L.restantes or "?") .. " grátis", { 70, 55, 25 }, { 255, 200, 90 }
  elseif L.tipo == "sem_licenca" then rot, cor_f, cor_t = "Ativar licença", { 245, 170, 35 }, { 35, 20, 5 }
  elseif L.tipo == "erro" then rot, cor_f, cor_t = "Sem conexão", { 80, 40, 40 }, { 240, 150, 140 }
  end
  fonte(3)
  local tw = gfx.measurestr(rot)
  local w, h = tw + 20, 24
  local x, y = W - 16 - w, 18
  local sobre = gfx.mouse_x >= x and gfx.mouse_x <= x + w and gfx.mouse_y >= y and gfx.mouse_y <= y + h
  rgb(cor_f[1] + (sobre and 20 or 0), cor_f[2] + (sobre and 20 or 0), cor_f[3] + (sobre and 20 or 0))
  caixa(x, y, w, h, 11, true)
  rgb(cor_t[1], cor_t[2], cor_t[3]); gfx.x, gfx.y = x + 10, y + 4; gfx.drawstr(rot)
  if sobre and clique then
    if L.tipo == "erro" then licenca("status") else menu_licenca() end
  end
end

-- quebra texto em linhas que cabem na largura
local function texto_quebrado(s, x, y, largura, r, g, b, alt)
  local linha = ""
  for palavra in (s or ""):gmatch("%S+") do
    local teste = linha == "" and palavra or (linha .. " " .. palavra)
    if gfx.measurestr(teste) > largura and linha ~= "" then
      texto(linha, x, y, r, g, b); y = y + (alt or 20); linha = palavra
    else linha = teste end
  end
  if linha ~= "" then texto(linha, x, y, r, g, b); y = y + (alt or 20) end
  return y
end

local function tela_licenca()
  cabecalho("Licença necessária")
  fonte(3)
  local y = texto_quebrado(E.msg, 20, 92, W - 40, 240, 200, 120)
  texto_quebrado("Já comprou? Clique em Ativar e cole a chave que chegou no seu e-mail.", 20, y + 10, W - 40,
    170, 170, 180)
  if botao("Ativar licença", 20, 200, W - 40, 42, true) then pedir_chave() end
  if (E.lic.link or "") ~= "" and botao("Comprar o PlayPronto", 20, 250, 200, 38) then abrir_link(E.lic.link) end
  if botao("Voltar", W - 140, 250, 120, 38) then E.tela = "inicio" end
end

local function tela_inicio()
  cabecalho("Playback e VS com IA direto no Reaper")
  selo_licenca()
  local cw = (W - 50) / 2
  if cartao("VS", "instrumentos separados", 20, 78, cw, 54, E.tipo == "vs") then
    E.tipo = "vs"; set_cfg("tipo", "vs") end
  if cartao("Playback", "só tira a voz", 30 + cw, 78, cw, 54, E.tipo == "playback") then
    E.tipo = "playback"; set_cfg("tipo", "playback") end
  local copiado = link_copiado()
  if botao(copiado and "Criar com o link copiado" or "Colar link do YouTube", 20, 146, W - 40, 46, true) then
    colar_link()
  end
  fonte(3)
  if copiado then
    local u, id = limpar_link(copiado)
    local mostra = id and ("youtube.com/watch?v=" .. id) or u:gsub("^https?://", ""):sub(1, 52)
    texto("Link: " .. mostra, 22, 194, 120, 200, 120)
  elseif reaper.CF_GetClipboard then
    texto("Copie o link no YouTube (Ctrl+C) e ele aparece aqui", 22, 194, 120, 120, 130)
  end
  local bw3 = (W - 60) / 3
  if botao("Arquivo do PC", 20, 220, bw3, 34) then escolher_arquivo() end
  local bl = E.bpm == "" and "BPM: auto" or ("BPM: " .. E.bpm)
  if botao(bl, 30 + bw3, 220, bw3, 34) then mudar_bpm() end
  if botao("Tom: " .. tom_txt(), 40 + bw3 * 2, 220, bw3, 34, false, E.tom ~= 0) then mudar_tom() end
  -- onde abrir
  fonte(3); texto("Quando terminar:", 20, 266, 160, 160, 170)
  if botao((E.modo == "aba" and "● " or "○ ") .. "Abrir em nova aba", 20, 286, 196, 26) then
    E.modo = "aba"; set_cfg("modo", "aba") end
  if botao((E.modo == "atual" and "● " or "○ ") .. "Pôr no cursor (setlist)", 224, 286, 196, 26) then
    E.modo = "atual"; set_cfg("modo", "atual") end
end

local function tela_processando()
  cabecalho((E.tipo == "playback" and "Playback: " or "VS: ") .. E.titulo:sub(1, 40))
  fonte(3); texto(E.etapa:sub(1, 60), 20, 92, 220, 220, 225)
  local bw = W - 40
  rgb(50, 50, 58); caixa(20, 118, bw, 16, 8, true)
  rgb(245, 170, 35)
  if E.porc and E.porc > 2 then caixa(20, 118, math.max(16, bw * E.porc / 100), 16, 8, true)
  elseif not E.porc then
    local t = (reaper.time_precise() * 0.5) % 1
    caixa(20 + (bw - 90) * t, 118, 90, 16, 8, true)
  end
  local s = math.floor(reaper.time_precise() - E.inicio)
  texto(string.format("%d:%02d   %s", s // 60, s % 60, E.porc and (E.porc .. "%") or ""), 20, 142, 150, 150, 160)
  texto("Pode fechar esta janela: ele continua e avisa quando acabar.", 20, 166, 120, 120, 130)
  if botao("Cancelar", W - 140, 200, 120, 32) then cancelar() end
end

local function tela_pronto()
  cabecalho("Playback pronto!")
  fonte(2); texto(E.titulo:sub(1, 40), 20, 96, 120, 220, 120)
  fonte(3); texto(E.msg, 20, 126, 170, 170, 180)
  if E.mp3 and botao("Abrir pasta do MP3", 20, 160, W - 40, 34) then
    reaper.ExecProcess('explorer.exe /select,"' .. E.mp3 .. '"', -1)
  end
  if botao("Criar outro", 20, 250, 200, 38, true) then E.tela = "inicio" end
  if botao("Fechar", W - 140, 250, 120, 38) then gfx.quit(); janela = false end
end

local function tela_erro()
  cabecalho("Deu erro")
  fonte(3); texto(E.msg:sub(1, 64), 20, 96, 240, 120, 110)
  texto("Dica: confira o link. Se continuar, me mande o log.", 20, 122, 170, 170, 180)
  if botao("Ver log", 20, 250, 120, 38) then reaper.ExecProcess('notepad.exe "' .. E.log .. '"', -1) end
  if botao("Voltar", W - 140, 250, 120, 38, true) then E.tela = "inicio" end
end

------------------------------------------------------------------ loop
local ultimo = 0

local function loop()
  if reaper.time_precise() - ultimo > 0.5 then
    ultimo = reaper.time_precise()
    if E.tela == "processando" then verificar() end
    verificar_licenca()
  end

  if janela then
    local ch = gfx.getchar()
    if ch < 0 or ch == 27 then gfx.quit(); janela = false
    else
      clique = (mouse_antes & 1) == 1 and (gfx.mouse_cap & 1) == 0 -- soltou o botão
      rgb(28, 28, 33); gfx.rect(0, 0, gfx.w, gfx.h, 1)
      if E.tela == "inicio" then tela_inicio()
      elseif E.tela == "processando" then tela_processando()
      elseif E.tela == "pronto" then tela_pronto()
      elseif E.tela == "licenca" then tela_licenca()
      else tela_erro() end
      mouse_antes = gfx.mouse_cap
      gfx.update()
    end
  end

  if janela or E.tela == "processando" or E.lic_job then reaper.defer(loop) end
end

gfx.init(NOME, W, H, 0, 300, 200)
gfx.setfont(1, "Segoe UI", 24, string.byte("b"))
gfx.setfont(2, "Segoe UI", 17, string.byte("b"))
gfx.setfont(3, "Segoe UI", 15)
licenca("status")
loop()
