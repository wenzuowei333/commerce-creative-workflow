"""Run source regression tests and isolated real PostgreSQL/Redis checks."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres-only", action="store_true")
    parser.add_argument("-k", default=None)
    args = parser.parse_args()
    env = os.environ.copy()
    env.update(PYTHONPATH=os.pathsep.join([str(ROOT/"backend"),str(ROOT)]), PYTHONDONTWRITEBYTECODE="1")
    (ROOT/"runtime").mkdir(exist_ok=True)
    if not args.postgres_only:
        subprocess.run([sys.executable,"-m","pytest","backend/tests","--junitxml=runtime/source-validation.xml"],cwd=ROOT,env=env,check=True)
    subprocess.run(["docker","compose","--profile","checks","up","-d","test-postgres","test-redis","--wait"],cwd=ROOT,check=True)
    env["SHOWCASE_PG_CHECKS"]="1"
    command=[sys.executable,"-m","pytest","checks","-q","--junitxml=runtime/postgres-validation.xml"]
    if args.k: command += ["-k",args.k]
    subprocess.run(command,cwd=ROOT,env=env,check=True)


if __name__=="__main__":
    main()
