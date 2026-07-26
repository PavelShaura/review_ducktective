import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="ducktective")
    subcommands = parser.add_subparsers(dest="command", required=True)

    serve_parser = subcommands.add_parser("serve", help="Запустить API")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true")

    arguments = parser.parse_args()

    if arguments.command == "serve":
        uvicorn.run(
            "ducktective.api.main:app",
            host=arguments.host,
            port=arguments.port,
            reload=arguments.reload,
        )
