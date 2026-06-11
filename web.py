import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

load_dotenv()

from app.db import SessionLocal, engine
from app.models import Base
from app.scanner import load_snapshot

app = Flask(__name__, template_folder="templates")
_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    Base.metadata.create_all(bind=engine)
    _schema_ready = True


_ensure_schema()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/arbs")
def api_arbs():
    _ensure_schema()
    with SessionLocal() as session:
        return jsonify(load_snapshot(session=session))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
