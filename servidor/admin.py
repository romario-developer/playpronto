"""Administração das licenças do PlayPronto.

    python servidor\\admin.py criar  email@cliente.com "Nome do Cliente"   [--pcs 2] [--enviar-email]
    python servidor\\admin.py listar [busca]
    python servidor\\admin.py bloquear   PLAY-XXXX-XXXX-XXXX-XXXX
    python servidor\\admin.py desbloquear PLAY-XXXX-XXXX-XXXX-XXXX
    python servidor\\admin.py liberar-pcs PLAY-XXXX-XXXX-XXXX-XXXX    (cliente trocou de PC)

Usa o servidor de licenca.py (SERVIDOR_PADRAO) e o token em servidor\\.chaves\\admin_token.txt.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
import licenca  # noqa: E402

TOKEN = (AQUI / ".chaves" / "admin_token.txt").read_text().strip()


def chamar(rota, corpo=None, metodo="POST"):
    req = urllib.request.Request(
        licenca.servidor() + rota, method=metodo,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers={"authorization": f"Bearer {TOKEN}", "content-type": "application/json",
                 "user-agent": "PlayPronto-admin/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Erro {e.code}: {e.read().decode()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("criar"); c.add_argument("email"); c.add_argument("nome", nargs="?", default="")
    c.add_argument("--pcs", type=int, default=2); c.add_argument("--enviar-email", action="store_true")
    l = sub.add_parser("listar"); l.add_argument("busca", nargs="?", default="")
    for nome in ("bloquear", "desbloquear", "liberar-pcs"):
        sub.add_parser(nome).add_argument("chave")
    a = ap.parse_args()

    if a.cmd == "criar":
        r = chamar("/admin/criar", {"email": a.email, "nome": a.nome, "max_pcs": a.pcs, "enviar_email": a.enviar_email})
        print(f"Licença criada para {r['email']} ({r['max_pcs']} PCs):\n\n    {r['chave']}\n")
    elif a.cmd == "listar":
        from urllib.parse import quote
        r = chamar(f"/admin/licencas?q={quote(a.busca)}", metodo="GET")
        for x in r["licencas"]:
            data = datetime.fromtimestamp(x["criada"]).strftime("%d/%m/%Y")
            print(f"{x['chave']}  {x['status']:9s}  PCs {x['pcs']}/{x['max_pcs']}  {data}  {x['origem']:7s}  {x['email']}  {x['nome'] or ''}")
        print(f"\n{len(r['licencas'])} licença(s)")
    else:
        chamar(f"/admin/{a.cmd}", {"chave": a.chave})
        print("Feito.")


if __name__ == "__main__":
    main()
