"""Compatibility launcher for the current frozen public-tool replay."""
import argparse, os, subprocess, sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True,help='Fresh output directory')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    env=dict(os.environ,PYTHON=sys.executable,OUTPUT=str(args.out.resolve()))
    subprocess.run(['sh',str(root/'run.sh')],cwd=root,env=env,check=True)

if __name__=='__main__':
    main()
