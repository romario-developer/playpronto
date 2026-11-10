"""Licença do PlayPronto: ativação online, renovação, teste grátis por computador.

O servidor devolve um token assinado (Ed25519). O app confere a assinatura com a chave
pública abaixo, então funciona offline até o token vencer (30 dias); com internet ele
renova sozinho a cada poucos dias.

Uso pela linha de comando (o botão do REAPER usa isto):
    python licenca.py --status            [--saida arquivo.txt]
    python licenca.py --ativar PLAY-XXXX-XXXX-XXXX-XXXX
    python licenca.py --desativar
"""
import argparse
import base64
import hashlib
import json
import os
import platform
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVIDOR_PADRAO = "https://playpronto-licencas.romariotecla.workers.dev"
CHAVE_PUBLICA = "7KM/h9jtyxR5m6szR+P0sjyfo1A4JeZD9Vv4Uulq870="
RENOVAR_APOS_DIAS = 3
RAIZ = Path(__file__).resolve().parent
DADOS = Path(os.environ.get("PLAYPRONTO_DADOS") or Path(os.environ.get("APPDATA", Path.home())) / "PlayPronto")
ARQ_LICENCA = DADOS / "licenca.json"


class ErroLicenca(Exception):
    def __init__(self, codigo, msg, extra=None):
        super().__init__(msg)
        self.codigo, self.msg, self.extra = codigo, msg, extra or {}


# ------------------------------------------------------------------ configuração e máquina
def servidor():
    if os.environ.get("PLAYPRONTO_SERVIDOR"):  # testes
        return os.environ["PLAYPRONTO_SERVIDOR"].rstrip("/")
    cfg = RAIZ / "config.ini"
    if cfg.exists():
        for linha in cfg.read_text(encoding="utf-8").splitlines():
            if linha.strip().lower().startswith("servidor="):
                return linha.split("=", 1)[1].strip().rstrip("/")
    return SERVIDOR_PADRAO


def maquina_id():
    """Identificador do computador (não muda ao reinstalar o PlayPronto)."""
    guid = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            guid = winreg.QueryValueEx(k, "MachineGuid")[0]
    except OSError:
        guid = platform.node()
    return hashlib.sha256(f"playpronto:{guid}".encode()).hexdigest()[:32]


def nome_pc():
    return (os.environ.get("COMPUTERNAME") or platform.node() or "PC")[:60]


# ------------------------------------------------------------------ servidor
def chamar(rota, dados, timeout=12):
    req = urllib.request.Request(
        servidor() + rota, data=json.dumps(dados).encode(), method="POST",
        headers={"content-type": "application/json", "user-agent": "PlayPronto/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            corpo = json.loads(e.read().decode())
        except Exception:
            corpo = {}
        raise ErroLicenca(corpo.get("erro", "http"), corpo.get("msg", f"Erro {e.code} no servidor."), corpo)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ErroLicenca("sem_internet", "Sem conexão com o servidor de licenças. Confira sua internet.")


# ------------------------------------------------------------------ token
def _b64url(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def conferir_token(token, maquina=None):
    """Devolve os dados do token se a assinatura for válida e for deste PC. Não olha validade."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        corpo_b64, sig_b64 = token.split(".")
        corpo, sig = _b64url(corpo_b64), _b64url(sig_b64)
        Ed25519PublicKey.from_public_bytes(base64.b64decode(CHAVE_PUBLICA)).verify(sig, corpo)
        dados = json.loads(corpo)
    except (ValueError, InvalidSignature, json.JSONDecodeError):
        return None
    if dados.get("m") != (maquina or maquina_id()):
        return None
    return dados


def _salvar(token):
    DADOS.mkdir(parents=True, exist_ok=True)
    ARQ_LICENCA.write_text(json.dumps({"token": token}), encoding="utf-8")


def _ler():
    try:
        return json.loads(ARQ_LICENCA.read_text(encoding="utf-8")).get("token")
    except (OSError, ValueError):
        return None


def _apagar():
    try:
        ARQ_LICENCA.unlink()
    except OSError:
        pass


# ------------------------------------------------------------------ operações
def ativar(chave):
    r = chamar("/v1/ativar", {"chave": chave.strip(), "maquina": maquina_id(), "nome_pc": nome_pc()})
    if not conferir_token(r["token"]):
        raise ErroLicenca("token_invalido", "Resposta inválida do servidor de licenças.")
    _salvar(r["token"])
    return r


def desativar():
    token = _ler()
    dados = conferir_token(token) if token else None
    if dados:
        try:
            chamar("/v1/desativar", {"chave": dados["c"], "maquina": dados["m"]})
        finally:
            _apagar()
    else:
        _apagar()


def status():
    """{'tipo': 'licenca'|'teste'|'sem_licenca', 'nome', 'email', 'restantes', 'total', 'msg', 'link'}"""
    maquina = maquina_id()
    token = _ler()
    dados = conferir_token(token, maquina) if token else None
    aviso = None
    if dados:
        agora = time.time()
        if agora - dados.get("iat", 0) > RENOVAR_APOS_DIAS * 86400:
            try:
                r = chamar("/v1/renovar", {"chave": dados["c"], "maquina": maquina})
                if conferir_token(r["token"], maquina):
                    _salvar(r["token"])
                    dados = conferir_token(r["token"], maquina)
            except ErroLicenca as e:
                if e.codigo in ("bloqueada", "desativada", "chave_invalida"):
                    _apagar()
                    dados = None
                    aviso = e.msg
                # sem internet: segue com o token atual até ele vencer
        if dados and dados.get("exp", 0) > agora:
            return {"tipo": "licenca", "nome": dados.get("n", ""), "email": dados.get("e", ""),
                    "chave": dados.get("c", ""), "msg": ""}
        if dados:
            return {"tipo": "sem_licenca", "msg": "Sua licença precisa ser renovada: conecte na internet e tente de novo."}
    if aviso:
        return {"tipo": "sem_licenca", "msg": aviso}
    r = chamar("/v1/teste/status", {"maquina": maquina})
    if r["restantes"] > 0:
        return {"tipo": "teste", "restantes": r["restantes"], "total": r["total"], "link": r.get("link", ""), "msg": ""}
    return {"tipo": "sem_licenca", "restantes": 0, "total": r["total"], "link": r.get("link", ""),
            "msg": f"Seu teste grátis de {r['total']} músicas acabou. Ative sua licença para continuar."}


def checar_para_uso():
    """Chamado antes de processar. Levanta ErroLicenca se não puder usar."""
    st = status()
    if st["tipo"] == "sem_licenca":
        raise ErroLicenca("sem_licenca", st["msg"], st)
    return st


def consumir_teste():
    r = chamar("/v1/teste/usar", {"maquina": maquina_id()})
    return r["restantes"]


# ------------------------------------------------------------------ linha de comando
def _escrever(saida, st):
    linhas = [f"{k.upper()}\t{str(v).replace(chr(9), ' ').replace(chr(10), ' ')}" for k, v in st.items()]
    texto = "\n".join(linhas + ["FIM"]) + "\n"
    if saida:
        Path(saida).write_text(texto, encoding="utf-8")
    else:
        print(texto)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--ativar", metavar="CHAVE")
    g.add_argument("--desativar", action="store_true")
    ap.add_argument("--saida")
    a = ap.parse_args()
    try:
        if a.ativar:
            r = ativar(a.ativar)
            st = {"tipo": "ativada", "nome": r.get("nome", ""), "email": r.get("email", ""), "msg": "Licença ativada!"}
        elif a.desativar:
            desativar()
            st = {"tipo": "desativada", "msg": "Este computador foi desativado."}
        else:
            st = status()
    except ErroLicenca as e:
        st = {"tipo": "erro", "codigo": e.codigo, "msg": e.msg}
    _escrever(a.saida, st)


if __name__ == "__main__":
    main()
