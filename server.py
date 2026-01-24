# server.py
import argparse
from pathlib import Path
import uvicorn

from db import init_db

def parse_args():
    parser = argparse.ArgumentParser(
        description="ItemQ Backend Server"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080
    )
    return parser.parse_args()

def main():
    args = parse_args()
    
    uvicorn.run(
        "routes:app",
        host=args.host,
        port=args.port,
        reload=True
    )

if __name__ == "__main__":
    main()
