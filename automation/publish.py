#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish.py - Pubblica nuovi articoli sul sito Sleek Jekyll via API GitHub,
zero git locale, zero rebase.

USO:
    python publish.py articolo "Titolo" "corpo in markdown" [immagine_featured]

Esempio:
    python publish.py articolo "Il mio primo post" "Testo del post in **markdown**."

Cosa fa:
  1. Genera slug + data odierna -> nome file YYYY-MM-DD-slug.md (convenzione Jekyll)
  2. Crea il front matter compatibile col tema Sleek (layout: post)
  3. Push diretto su GitHub via API (stesso motore di fastfix.py)
  4. Stampa l'URL live (GitHub Pages impiega 1-2 min a pubblicare)

Per modificare pagine/file ESISTENTI (index.md, _config.yml, css) usa
fastfix.py invece.
"""
import sys
import os
import re
import json
import base64
import datetime
import urllib.request
import urllib.error

_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_config():
    with open(os.path.join(_DIR, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    token = None
    env_path = os.path.join(_DIR, ".env")
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("GITHUB_TOKEN="):
                token = line.strip().split("=", 1)[1]
    if not token:
        raise RuntimeError("GITHUB_TOKEN mancante in automation/.env")
    return cfg, token


def _api(url, token, method="GET", data=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", "token " + token)
    req.add_header("Accept", "application/vnd.github+json")
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=body) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("GitHub API " + str(e.code) + ": " + e.read().decode("utf-8"))


def slugify(title):
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug.strip("-")


def publish_articolo(titolo, corpo, featured_img=None):
    cfg, token = _load_config()
    slug = slugify(titolo)
    oggi = datetime.date.today().strftime("%Y-%m-%d")
    filename = oggi + "-" + slug + ".md"
    rel_path = "_posts/" + filename

    front = "---\n"
    front += "layout: post\n"
    front += "title: " + titolo + "\n"
    if featured_img:
        front += "featured-img: " + featured_img + "\n"
    front += "---\n"
    content = front + corpo + "\n"

    owner, repo, branch = cfg["github_owner"], cfg["github_repo"], cfg["github_branch"]
    url = "https://api.github.com/repos/" + owner + "/" + repo + "/contents/" + rel_path

    # controlla che non esista già
    try:
        _api(url + "?ref=" + branch, token)
        print("[ERRORE] Esiste gia' un articolo con questo slug/data: " + rel_path)
        sys.exit(1)
    except RuntimeError:
        pass  # non esiste, ok

    payload = {
        "message": "Nuovo articolo: " + titolo,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    res = _api(url, token, method="PUT", data=payload)

    # salva anche in locale per coerenza
    local_path = os.path.join(cfg["repo"], "_posts", filename)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("[OK] Creato " + rel_path)
    print("Commit: https://github.com/" + owner + "/" + repo + "/commit/" + res["commit"]["sha"])
    print("[LIVE tra 1-2 min] " + cfg["site_base"] + "/")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    comando = sys.argv[1]

    if comando == "articolo":
        if len(sys.argv) < 4:
            print('Uso: python publish.py articolo "Titolo" "corpo markdown" [immagine_featured]')
            sys.exit(1)
        titolo, corpo = sys.argv[2], sys.argv[3]
        featured_img = sys.argv[4] if len(sys.argv) > 4 else None
        publish_articolo(titolo, corpo, featured_img)

    else:
        print("Comando sconosciuto: " + comando)
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
