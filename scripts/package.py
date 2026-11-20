"""Build a source-only archive; local runtime/configuration never enters the archive."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
archive = root.parent / 'image-api.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for relative in ['README.md', 'requirements.txt', '.codex-plugin/plugin.json']:
        z.write(root / relative, 'image-api/' + relative)
    for folder in ['scripts', 'skills', 'tests']:
        for p in (root / folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix in {'.py', '.md', '.yaml'}:
                z.write(p, 'image-api/' + p.relative_to(root).as_posix())
    z.writestr('image-api/.mcp.json', '{"mcpServers": {}}\n')
print(archive)
