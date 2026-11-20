"""Explicit opt-in online test using the same service as MCP; one request, no retry."""
import argparse
import asyncio
import json
from image_service import Settings, ImageService, ImageError

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["status", "models", "generate"])
parser.add_argument("--output-dir")
parser.add_argument("--model")
args = parser.parse_args()


async def main():
    try:
        service = ImageService(Settings.load())
        if args.mode == "status":
            result = service.status()
        elif args.mode == "models":
            result = await service.models()
        else:
            if not args.output_dir:
                parser.error("--output-dir is required for generate")
            result = await service.create(
                "A simple flat illustration of a teal ceramic cup on a warm cream background. No text, no logo.",
                args.output_dir, model=args.model, quality="low")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ImageError as e:
        print(json.dumps({"error": str(e)}))
        raise SystemExit(1)


asyncio.run(main())
