"""Tagore Career Institute ecosystem - run / set up from the command line.

  python run_tagore.py demo              fill a fresh database with demo data, then start
  python run_tagore.py create-director   create the first director (super admin) login
  python run_tagore.py                   start the server (http://0.0.0.0:5800)
"""
import argparse
import getpass
import sys

from tagore import create_app, create_superadmin, db, default_data_dir
from tagore.seed import seed_demo

PORT = 5800


def serve(app, host):
    try:
        from waitress import serve as wserve
        wserve(app, host=host, port=PORT, threads=8)
    except ImportError:
        app.run(host=host, port=PORT, threaded=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["serve", "demo", "create-director"], default="serve")
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to open it to phones on your network")
    a = ap.parse_args()
    app = create_app()
    print(f"Data folder: {default_data_dir()}")
    with app.app_context():
        has_users = bool(db.connect(app.config["DB_PATH"]).execute("SELECT 1 FROM users LIMIT 1").fetchone())
    if a.command == "demo":
        if has_users:
            sys.exit("This database already has users. Use a fresh folder: TAGORE_DATA=/path/to/new python run_tagore.py demo")
        info = seed_demo(app)
        print("\nDemo accounts (password for all: %s)" % info["password"])
        for k, v in info.items():
            if k != "password":
                print(f"  {k:9s} {v}")
    elif a.command == "create-director":
        login = input("Director login ID [director]: ").strip() or "director"
        name = input("Director full name: ").strip() or "Director"
        pw = getpass.getpass("Password (blank = generate): ") or None
        pw = create_superadmin(app, login, name, pw)
        print(f"Created. Login ID: {login}   Password: {pw}  (you will be asked to change it at first login)")
        return
    elif not has_users:
        print("No users yet. Run `python run_tagore.py create-director` (real use) or `python run_tagore.py demo`.")
    print(f"\nTagore ecosystem running at http://{a.host}:{PORT}")
    serve(app, a.host)


if __name__ == "__main__":
    main()
