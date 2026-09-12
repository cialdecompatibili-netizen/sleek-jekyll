#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fastfix.py - push diretto via API GitHub, senza git/rebase.
Pensato per fix rapidi su UN file alla volta (css, html, py, ecc).
Legge/scrive direttamente su GitHub in una chiamata, poi (opzionale)
sincronizza anche la copia locale così restano sempre allineati.

Config in automation/config.json (owner/repo/branch) +
automation/.env (GITHUB_TOKEN) - entrambi ignorati da git.

USO DA RIGA DI COMANDO:
    python fastfix.py get <path_relativo_nel_repo>
        -> stampa il contenuto attuale su GitHub e lo salva anche in locale

    python fastfix.py push <path_relativo_nel_repo> "messaggio commit"
        -> legge il file LOCALE e lo pusha su GitHub (usa il file che hai
           già modificato con Desktop Commander / editor)

    python fastfix.py replace <path_relativo_nel_repo> "vecchio" "nuovo" "messaggio commit"
        -> find & replace diretto: scarica da GitHub, sostituisce, ripubblica
           tutto in una chiamata (comodo per fix di 1-2 righe)

    python fastfix.py delete <path_relativo_nel_repo> "messaggio commit"
        -> elimina il file da GitHub e in locale

    python fastfix.py tree [filtro]
        -> stampa l'elenco di tutti i file del repo (1 sola chiamata API),
           opzionale filtro per sottostringa nel path (es. "shop" o ".html")

    python fastfix.py check <url_o_path_relativo> ["testo atteso"]
        -> aspetta che GitHub Pages pubblichi la modifica, pollando ogni 20s
           (max 6 tentativi = 2 min). Se "testo atteso" e' dato, verifica che
           sia presente nella pagina; altrimenti basta che risponda 200.

    python fastfix.py undo <path_relativo_nel_repo>
        -> ripristina il file alla versione PRIMA dell'ultimo commit
           (rollback rapido in caso di fix sbagliato)

    python fastfix.py batch "file1,file2,file3" ["messaggio commit"]
        -> pusha PIU' file (letti dal locale) in UN SOLO commit, invece di
           un commit per file. Usalo quando un fix tocca più file insieme.

Oppure importa get_file() / push_file() / replace_in_file() / tree() /
check() / undo() / batch() da un altro script.
"""
import sys
import os
import json
import base64
import urllib.request
import urllib.error

_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_config():
    with open(os.path.join(_DIR, "config.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)
    env_path = os.path.join(_DIR, ".env")
    token = None
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("GITHUB_TOKEN="):
                    token = line.strip().split("=", 1)[1]
    if not token:
        raise RuntimeError("GITHUB_TOKEN mancante in automation/.env")
    return cfg, token


def _api(url, token, method="GET", data=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=body) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub API {e.code}: {e.read().decode('utf-8')}")

def get_file(rel_path, save_local=True):
    """Scarica il contenuto attuale da GitHub. Ritorna (content_str, sha)."""
    cfg, token = _load_config()
    url = (f"https://api.github.com/repos/{cfg['github_owner']}/{cfg['github_repo']}"
           f"/contents/{rel_path}?ref={cfg['github_branch']}")
    res = _api(url, token)
    content = base64.b64decode(res["content"]).decode("utf-8")
    if save_local:
        local_path = os.path.join(cfg["repo"], rel_path.replace("/", os.sep))
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    return content, res["sha"]


def push_file(rel_path, content=None, message="fastfix update"):
    """Pusha su GitHub. Se content è None, legge dal file locale."""
    cfg, token = _load_config()
    local_path = os.path.join(cfg["repo"], rel_path.replace("/", os.sep))
    if content is None:
        with open(local_path, "r", encoding="utf-8") as f:
            content = f.read()

    base_url = f"https://api.github.com/repos/{cfg['github_owner']}/{cfg['github_repo']}/contents/{rel_path}"
    # serve lo sha attuale per aggiornare (non serve per file nuovi)
    sha = None
    try:
        cur = _api(f"{base_url}?ref={cfg['github_branch']}", token)
        sha = cur["sha"]
    except RuntimeError:
        pass  # file non esiste ancora su GitHub -> lo crea

    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": cfg["github_branch"],
    }
    if sha:
        payload["sha"] = sha

    res = _api(base_url, token, method="PUT", data=payload)

    # tiene allineata anche la copia locale
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "w", encoding="utf-8", newline="") as f:
        f.write(content)

    print(f"OK -> https://github.com/{cfg['github_owner']}/{cfg['github_repo']}/commit/{res['commit']['sha']}")
    print(f"Live tra 1-2 min su: {cfg['site_base']}")
    return res


def delete_file(rel_path, message="fastfix delete"):
    """Cancella un file sia su GitHub che in locale."""
    cfg, token = _load_config()
    base_url = f"https://api.github.com/repos/{cfg['github_owner']}/{cfg['github_repo']}/contents/{rel_path}"
    cur = _api(f"{base_url}?ref={cfg['github_branch']}", token)
    _api(base_url, token, method="DELETE",
         data={"message": message, "sha": cur["sha"], "branch": cfg["github_branch"]})
    local_path = os.path.join(cfg["repo"], rel_path.replace("/", os.sep))
    if os.path.exists(local_path):
        os.remove(local_path)
    print(f"Eliminato {rel_path} da GitHub e locale.")


def replace_in_file(rel_path, old, new, message="fastfix replace"):
    """Find & replace in un colpo: scarica, sostituisce, ripubblica."""
    content, _ = get_file(rel_path, save_local=False)
    if old not in content:
        raise RuntimeError(f"Testo da sostituire non trovato in {rel_path}")
    if content.count(old) > 1:
        raise RuntimeError(f"'{old[:50]}...' trovato piu' di una volta ({content.count(old)}x) - rendi la stringa piu' specifica")
    new_content = content.replace(old, new)
    return push_file(rel_path, content=new_content, message=message)

def tree(prefix_filter=None):
    """Albero del repo in 1 sola chiamata API (Git Trees ricorsivo)."""
    cfg, token = _load_config()
    url = f"https://api.github.com/repos/{cfg['github_owner']}/{cfg['github_repo']}/git/trees/{cfg['github_branch']}?recursive=1"
    res = _api(url, token)
    paths = sorted(item["path"] for item in res["tree"] if item["type"] == "blob")
    if prefix_filter:
        paths = [p for p in paths if prefix_filter in p]
    for p in paths:
        print(p)
    print(f"-- {len(paths)} file" + (f" (filtro: {prefix_filter})" if prefix_filter else ""))


def check(rel_path, expect_text=None, tries=6, wait_s=20):
    """Polla il sito live finche' la pagina/il file risulta aggiornato. Output minimo."""
    import time
    cfg, _ = _load_config()
    url = rel_path if rel_path.startswith("http") else f"{cfg['site_base'].rstrip('/')}/{rel_path.lstrip('/')}"
    for i in range(1, tries + 1):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                body = r.read().decode("utf-8", errors="ignore")
            if expect_text is None or expect_text in body:
                print(f"LIVE ({i * wait_s}s) -> {url}")
                return True
            print(f"[{i}/{tries}] non ancora aggiornato...")
        except Exception as e:
            print(f"[{i}/{tries}] non raggiungibile ({e})")
        if i < tries:
            time.sleep(wait_s)
    print(f"TIMEOUT dopo {tries * wait_s}s -> {url}")
    return False


def undo(rel_path):
    """Ripristina un file alla versione del commit PRECEDENTE all'ultimo."""
    cfg, token = _load_config()
    commits_url = f"https://api.github.com/repos/{cfg['github_owner']}/{cfg['github_repo']}/commits?path={rel_path}&per_page=2"
    commits = _api(commits_url, token)
    if len(commits) < 2:
        print("Nessun commit precedente per questo file.")
        return
    prev_sha = commits[1]["sha"]
    file_url = f"https://api.github.com/repos/{cfg['github_owner']}/{cfg['github_repo']}/contents/{rel_path}?ref={prev_sha}"
    res = _api(file_url, token)
    content = base64.b64decode(res["content"]).decode("utf-8")
    push_file(rel_path, content=content, message=f"undo: ripristina a {prev_sha[:7]}")


def batch(files, message="fastfix batch update"):
    """
    Pusha PIU' file in UN SOLO commit (1 chiamata Git Trees + 1 commit),
    invece di N push_file() separati = N commit. Usalo quando un fix tocca
    più file insieme (es. un CSS + un include).

    files: lista di path relativi -> legge SEMPRE dal locale (come push).
           Se un file non esiste ancora su GitHub, viene creato.
    """
    cfg, token = _load_config()
    owner, repo, branch = cfg["github_owner"], cfg["github_repo"], cfg["github_branch"]
    base = f"https://api.github.com/repos/{owner}/{repo}"

    # 1. sha dell'ultimo commit sul branch -> serve come parent
    ref = _api(f"{base}/git/refs/heads/{branch}", token)
    base_commit_sha = ref["object"]["sha"]
    base_commit = _api(f"{base}/git/commits/{base_commit_sha}", token)
    base_tree_sha = base_commit["tree"]["sha"]

    # 2. crea un blob per ogni file locale
    tree_items = []
    for rel_path in files:
        git_path = rel_path.replace("\\", "/")  # GitHub vuole SEMPRE slash Unix nel tree
        local_path = os.path.join(cfg["repo"], rel_path.replace("/", os.sep))
        with open(local_path, "r", encoding="utf-8") as f:
            content = f.read()
        blob = _api(f"{base}/git/blobs", token, method="POST",
                     data={"content": content, "encoding": "utf-8"})
        tree_items.append({"path": git_path, "mode": "100644", "type": "blob", "sha": blob["sha"]})

    # 3. crea un nuovo tree basato sul precedente + i file modificati
    new_tree = _api(f"{base}/git/trees", token, method="POST",
                     data={"base_tree": base_tree_sha, "tree": tree_items})

    # 4. crea il commit e sposta il branch
    new_commit = _api(f"{base}/git/commits", token, method="POST",
                       data={"message": message, "tree": new_tree["sha"], "parents": [base_commit_sha]})
    _api(f"{base}/git/refs/heads/{branch}", token, method="PATCH",
         data={"sha": new_commit["sha"]})

    print(f"OK ({len(files)} file, 1 commit) -> https://github.com/{owner}/{repo}/commit/{new_commit['sha']}")
    print(f"Live tra 1-2 min su: {cfg['site_base']}")
    return new_commit


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "get":
        content, sha = get_file(sys.argv[2])
        print(f"Scaricato ({len(content)} char, sha {sha[:8]}) e salvato in locale.")

    elif cmd == "push":
        msg = sys.argv[3] if len(sys.argv) > 3 else "fastfix update"
        push_file(sys.argv[2], message=msg)

    elif cmd == "replace":
        if len(sys.argv) < 5:
            print("Uso: python fastfix.py replace <path> \"vecchio\" \"nuovo\" [\"messaggio\"]")
            sys.exit(1)
        msg = sys.argv[5] if len(sys.argv) > 5 else "fastfix replace"
        replace_in_file(sys.argv[2], sys.argv[3], sys.argv[4], message=msg)

    elif cmd == "delete":
        msg = sys.argv[3] if len(sys.argv) > 3 else "fastfix delete"
        delete_file(sys.argv[2], message=msg)

    elif cmd == "tree":
        flt = sys.argv[2] if len(sys.argv) > 2 else None
        tree(flt)

    elif cmd == "check":
        if len(sys.argv) < 3:
            print("Uso: python fastfix.py check <url_o_path> [\"testo atteso\"]")
            sys.exit(1)
        expect = sys.argv[3] if len(sys.argv) > 3 else None
        ok = check(sys.argv[2], expect_text=expect)
        sys.exit(0 if ok else 1)

    elif cmd == "undo":
        if len(sys.argv) < 3:
            print("Uso: python fastfix.py undo <path>")
            sys.exit(1)
        undo(sys.argv[2])

    elif cmd == "batch":
        if len(sys.argv) < 3:
            print('Uso: python fastfix.py batch "file1.html,file2.scss,file3.md" ["messaggio"]')
            sys.exit(1)
        files = [f.strip() for f in sys.argv[2].split(",") if f.strip()]
        msg = sys.argv[3] if len(sys.argv) > 3 else "fastfix batch update"
        batch(files, message=msg)

    else:
        print(f"Comando sconosciuto: {cmd}")
        print(__doc__)
        sys.exit(1)
