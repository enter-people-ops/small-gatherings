"""
Serviço web (Railway) que:
  - GET  /            -> serve o artefato do mês (index.html), URL fixa mensal.
  - POST /run         -> roda o pipeline. ?send=false devolve os payloads das
                         mensagens para o Make enviar; ?send=true envia pelo Slack.
  - GET  /health      -> checagem simples.

O Make.com agenda o dia 1º e chama POST /run. Ver README para o cenário.
Protegido por header X-Run-Key == RUN_KEY (defina no Railway e no Make).
"""
from __future__ import annotations
import os, io, json
from flask import Flask, request, jsonify, send_file, abort
import main as pipeline

app = Flask(__name__)
DATA_DIR = os.environ.get("DATA_DIR", "../data")

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/")
def artifact():
    path = os.path.join(DATA_DIR, "index.html")
    if not os.path.exists(path):
        return "<h1>Ainda não há grupos deste mês.</h1>", 200
    return send_file(path)

@app.get("/fonts/<path:fname>")
def fonts(fname):
    """Serve as fontes Geist auto-hospedadas referenciadas pelo artefato."""
    return send_file(os.path.join(DATA_DIR, "fonts", fname))

@app.post("/run")
def run():
    if os.environ.get("RUN_KEY") and request.headers.get("X-Run-Key") != os.environ["RUN_KEY"]:
        abort(401)
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
    if os.environ.get("RUN_KEY") and request.headers.get("X-Run-Key") != os.environ["RUN_KEY"]:
        abort(401)
    try:
        return jsonify(pipeline.diagnose())
    except Exception as e:
        import traceback
        return jsonify({"error": type(e).__name__, "message": str(e),
                        "trace": traceback.format_exc().splitlines()[-6:]}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
