"""Prepare a persistent runtime; optionally register MCP and the companion skill."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
import uuid
import venv
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--destination", type=Path, default=Path.home() / "Documents" / "Codex" / "tools" / "image-api")
parser.add_argument("--register", action="store_true", help="Register the prepared runtime in user Codex config and install its skill")
parser.add_argument("--register-only", action="store_true", help="Register an already prepared runtime without downloading dependencies")
args = parser.parse_args()
dest = args.destination.expanduser().resolve()
codex = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()
python = dest / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

# Check registration conflicts before overwriting a running installation or downloading packages.
if args.register or args.register_only:
    config_path = codex / "config.toml"
    original = config_path.read_bytes() if config_path.exists() else b""
    config_text = original.decode("utf-8-sig")
    config = tomllib.loads(config_text)
    existing = config.get("mcp_servers", {}).get("image_api")
    expected_args = [str(dest / "scripts" / "server.py")]
    if existing is not None and (existing.get("command") != str(python) or existing.get("args") != expected_args):
        parser.error("A different image_api MCP entry already exists. No configuration was changed.")
    skill_target = codex / "skills" / "image-api" / "SKILL.md"
    previous_skill = dest / "skills" / "image-api" / "SKILL.md"
    acceptable_skills = {(SOURCE / "skills" / "image-api" / "SKILL.md").read_bytes()}
    if previous_skill.exists():
        acceptable_skills.add(previous_skill.read_bytes())
    if skill_target.exists() and skill_target.read_bytes() not in acceptable_skills:
        parser.error("The installed image-api skill has independent edits. No files were changed.")

if not args.register_only:
    if dest.exists() and any(dest.iterdir()):
        manifest = dest / ".codex-plugin" / "plugin.json"
        if not manifest.exists() or json.loads(manifest.read_text(encoding="utf-8"))["name"] != "image-api":
            parser.error("Destination is not an existing image-api installation; choose an empty directory.")
    if dest != SOURCE:
        shutil.copytree(SOURCE, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"))
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(dest / ".venv")
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--retries", "0",
                    "-r", str(dest / "requirements.txt")], check=True)
    # Concrete local paths avoid reliance on undocumented plugin-root interpolation.
    mcp_config = {"mcpServers": {"image_api": {
        "command": str(python), "args": [str(dest / "scripts" / "server.py")],
        "env": {"CODEX_HOME": str(codex),
                "IMAGEGEN_ALLOWED_ROOTS": str(Path.home() / "Documents" / "Codex")}
    }}}
    (dest / ".mcp.json").write_text(json.dumps(mcp_config, indent=2), encoding="utf-8")
    print(json.dumps({"prepared": str(dest)}))

if args.register or args.register_only:
    if not python.exists() or not (dest / "scripts" / "server.py").exists():
        parser.error("Prepare the runtime before registering it.")
    skill_source = dest / "skills" / "image-api" / "SKILL.md"
    if (config_path.read_bytes() if config_path.exists() else b"") != original:
        parser.error("Codex configuration changed during installation. Registration was skipped; rerun --register-only.")
    codex.mkdir(parents=True, exist_ok=True)
    if existing is None:
        block = ("\n\n[mcp_servers.image_api]\ncommand = " + json.dumps(str(python)) +
                 "\nargs = " + json.dumps(expected_args) +
                 "\nstartup_timeout_sec = 30\ntool_timeout_sec = 300\n" +
                 "[mcp_servers.image_api.env]\nCODEX_HOME = " + json.dumps(str(codex)) +
                 "\nIMAGEGEN_ALLOWED_ROOTS = " +
                 json.dumps(str(Path.home() / "Documents" / "Codex")) + "\n")
        updated = config_text + block
        tomllib.loads(updated)
        if original:
            backup = codex / ("config.toml.image-api-" + uuid.uuid4().hex[:10] + ".bak")
            with backup.open("xb") as f:
                f.write(original)
        staging = codex / (".image-api-config-" + uuid.uuid4().hex + ".tmp")
        staging.write_text(updated, encoding="utf-8")
        os.replace(staging, config_path)
    skill_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(skill_source, skill_target)
    print(json.dumps({"registered": "image_api", "skill": str(skill_target), "next": "Restart MCP or start a new chat."}))
