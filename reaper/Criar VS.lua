-- Atalho antigo: agora o script se chama PlayPronto.lua (fica nesta mesma pasta).
local aqui = debug.getinfo(1, "S").source:sub(2):match("^(.*)[\\/]")
dofile(aqui .. "\\PlayPronto.lua")
