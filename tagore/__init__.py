"""Tagore Career Institute - student / parent / teacher / office / director ecosystem."""
from __future__ import annotations

import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash

from . import db
from .core import api, gen_password

STATIC = Path(__file__).parent / "static"


def default_data_dir() -> Path:
    env = os.environ.get("TAGORE_DATA")
    return Path(env) if env else Path.cwd() / "tagore-data"


def _secret_key(data_dir: Path) -> str:
    """Stable per-install key (env wins) so logins survive restarts."""
    if os.environ.get("TAGORE_SECRET"):
        return os.environ["TAGORE_SECRET"]
    f = data_dir / "secret.key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
        try:
            f.chmod(0o600)
        except OSError:
            pass
    return f.read_text().strip()


def create_app(data_dir: Path | str | None = None) -> Flask:
    data_dir = Path(data_dir) if data_dir else default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False
    app.config.update(
        DB_PATH=str(data_dir / "tagore.db"),
        SECRET_KEY=_secret_key(data_dir),
        MAX_CONTENT_LENGTH=4 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("TAGORE_HTTPS") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
    )
    db.init_db(app.config["DB_PATH"])

    from . import (routes_comms, routes_connect, routes_finance, routes_learning, routes_people,  # noqa: F401
                   routes_reports)
    app.register_blueprint(api)

    @app.after_request
    def finish(resp):
        con = db.g.pop("db", None)
        if con is not None:
            (con.commit if resp.status_code < 400 else con.rollback)()
            con.close()
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if resp.mimetype == "application/json":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.teardown_request
    def cleanup(exc):
        con = db.g.pop("db", None)
        if con is not None:
            con.rollback()
            con.close()

    @app.errorhandler(HTTPException)
    def http_error(e):
        from flask import request
        if request.path.startswith("/api/"):
            return jsonify(error=e.description), e.code
        return e

    @app.errorhandler(Exception)
    def crash(e):
        app.logger.exception("Unhandled error")
        return jsonify(error="Something went wrong on the server"), 500

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/<path:name>")
    def assets(name):
        return send_from_directory(STATIC, name)

    return app


def create_superadmin(app: Flask, login_id: str, name: str, password: str | None = None) -> str:
    """Create the first director login. Returns the password used."""
    password = password or gen_password(10)
    con = db.connect(app.config["DB_PATH"])
    try:
        con.execute("INSERT INTO users(role,login_id,password_hash,name,must_change) VALUES('superadmin',?,?,?,1)",
                    (login_id, generate_password_hash(password), name))
        con.commit()
    finally:
        con.close()
    return password
