"""
Serviço web (Railway) que:
  - GET  /            -> serve o artefato do mês (index.html), URL fixa mensal.
  - POST /run         -> roda o pipeline (gera grupos/artefato). ?send=true
                         também envia direto pelo Slack (atalho manual — ver
                         GATE DE APROVAÇÃO abaixo); default é ?send=false.
  - GET  /admin       -> painel admin (mover/adicionar/remover pessoas,
                         editar sugestões de rolê, apertar "enviar").
  - GET  /health      -> checagem simples.

GATE DE APROVAÇÃO (set/2026): o Make agenda o dia 1º e chama POST
/run?send=false (só gera). Ninguém recebe mensagem até um admin revisar em
/admin e clicar em "Enviar" (POST /admin/api/send) — ver CLAUDE.md seção 17.
Protegido por header X-Run-Key == RUN_KEY (defina no Railway e no Make).
"""
from __future__ import annotations
import os, io, json
from flask import Flask, request, jsonify, send_file, abort
import main as pipeline
import group_admin

app = Flask(__name__)
DATA_DIR = os.environ.get("DATA_DIR", "../data")

def _check_key():
    if os.environ.get("RUN_KEY") and request.headers.get("X-Run-Key") != os.environ["RUN_KEY"]:
        abort(401)

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/")
def artifact():
    path = pipeline.artifact_path()
    if not os.path.exists(path):
        return "<h1>Ainda não há grupos deste mês.</h1>", 200
    return send_file(path)

@app.get("/fonts/<path:fname>")
def fonts(fname):
    """Serve as fontes Geist auto-hospedadas referenciadas pelo artefato."""
    return send_file(os.path.join(DATA_DIR, "fonts", fname))

@app.get("/favicon.svg")
def favicon():
    """Ícone da aba do artefato (logo-key, marca Enter)."""
    return send_file(os.path.join(DATA_DIR, "logo-key.svg"))

@app.post("/run")
def run():
    _check_key()
    send = request.args.get("send", "false").lower() == "true"
    try:
        result = pipeline.run_api(send=send)
        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({"error": type(e).__name__, "message": str(e),
                        "trace": traceback.format_exc().splitlines()[-6:]}), 200

@app.get("/debug")
def debug():
    _check_key()
    try:
        return jsonify(pipeline.diagnose())
    except Exception as e:
        import traceback
        return jsonify({"error": type(e).__name__, "message": str(e),
                        "trace": traceback.format_exc().splitlines()[-6:]}), 200

@app.get("/debug/convenia")
def debug_convenia():
    """Diagnóstico do que a API do Convenia realmente devolve (sem filtrar
    elegibilidade) — pra investigar divergência de headcount com o painel."""
    _check_key()
    try:
        return jsonify(pipeline.convenia_report(name_filter=request.args.get("nome")))
    except Exception as e:
        import traceback
        return jsonify({"error": type(e).__name__, "message": str(e),
                        "trace": traceback.format_exc().splitlines()[-6:]}), 200

@app.get("/admin")
def admin_page():
    """Painel de admin: HTML estático (sem dado nenhum embutido). A própria
    página pede a X-Run-Key no navegador e a usa em fetch() pras chamadas
    abaixo — não há sessão de verdade, é o mesmo modelo de segredo compartilhado
    já usado em /run e /debug."""
    return send_file(os.path.join(os.path.dirname(__file__), "admin.html"))

@app.get("/admin/api/groups")
def admin_get_groups():
    _check_key()
    try:
        data = group_admin.load_groups()
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    data["min_women"] = int(os.environ.get("GROUP_MIN_WOMEN", "2"))
    data["unresolved"] = [p["name"] for g in data["groups"] for p in g if not p.get("slack_id")]
    return jsonify(data)

@app.post("/admin/api/groups")
def admin_save_groups():
    _check_key()
    body = request.get_json(force=True, silent=True) or {}
    assignments = body.get("assignments")
    if not isinstance(assignments, dict):
        return jsonify({"error": "Campo 'assignments' (objeto {person_id: group_index}) é obrigatório."}), 400
    try:
        return jsonify(group_admin.save_assignments(assignments))
    except (ValueError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 400

@app.get("/admin/api/roster")
def admin_roster():
    """Gente elegível no Convenia que ainda não está em nenhum grupo — pra
    o painel oferecer como 'adicionar pessoa'. Exige ?q= (>=2 caracteres)."""
    _check_key()
    try:
        return jsonify(group_admin.list_roster(request.args.get("q", "")))
    except (ValueError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 400

@app.get("/admin/api/hotspots")
def admin_get_hotspots():
    _check_key()
    return jsonify(group_admin.load_hotspots())

@app.post("/admin/api/hotspots")
def admin_save_hotspots():
    _check_key()
    body = request.get_json(force=True, silent=True) or {}
    items = body.get("items")
    try:
        return jsonify(group_admin.save_hotspots(items))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.post("/admin/api/send")
def admin_send():
    """O ÚNICO gatilho de envio real das mensagens no Slack, a partir de
    set/2026 — um admin revisa tudo em /admin e aperta este botão. POST
    /run?send=true continua existindo como atalho manual (gera E envia na
    mesma chamada, pulando a revisão), mas não é mais o caminho do Make."""
    _check_key()
    body = request.get_json(force=True, silent=True) or {}
    force = bool(body.get("force", False))
    try:
        return jsonify(group_admin.send_now(force=force))
    except (ValueError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
