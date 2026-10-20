#!/usr/bin/env node
// video-watcher installer — copies the skill into your agent's skills folder.
// Usage:
//   npx github:neartana/video-watcher [--dir <path>] [--agent <name>] [--local]
//   npx video-watcher [--dir <path>] ...
//
// Targets:
//   --dir <path>        install exactly into <path>/video-watcher
//   --agent claude      ~/.claude/skills/video-watcher
//   --agent cursor      ~/.cursor/skills/video-watcher
//   --agent agents      ~/.agents/skills/video-watcher   (skills CLI default)
//   --local             ./.agents/skills/video-watcher  (per-project)
//   (no flag)           ~/.agents/skills if present, else ~/.claude/skills
import { cpSync, existsSync, mkdirSync, chmodSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);

function flag(name) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : null;
}
if (args.includes("--help") || args.includes("-h")) {
  console.log(`video-watcher installer

  npx github:neartana/video-watcher [--dir <path>] [--agent <claude|cursor|agents>] [--local]

Copies SKILL.md + scripts/ into <skills-dir>/video-watcher.
Requirements at runtime: python3, ffmpeg, node, a self-hosted Cobalt checkout.`);
  process.exit(0);
}

const home = homedir();
let skillsDir;
const dirFlag = flag("--dir");
const agentFlag = flag("--agent");
if (dirFlag) {
  skillsDir = resolve(dirFlag);
} else if (args.includes("--local")) {
  skillsDir = join(process.cwd(), ".agents", "skills");
} else if (agentFlag === "claude") {
  skillsDir = join(home, ".claude", "skills");
} else if (agentFlag === "cursor") {
  skillsDir = join(home, ".cursor", "skills");
} else if (agentFlag === "agents") {
  skillsDir = join(home, ".agents", "skills");
} else {
  skillsDir = existsSync(join(home, ".agents", "skills"))
    ? join(home, ".agents", "skills")
    : join(home, ".claude", "skills");
}

const dest = join(skillsDir, "video-watcher");
mkdirSync(join(dest, "scripts"), { recursive: true });
for (const f of ["SKILL.md", "README.md", "LICENSE"]) {
  cpSync(join(root, f), join(dest, f));
}
cpSync(join(root, "scripts", "watch_video.py"), join(dest, "scripts", "watch_video.py"));
try { chmodSync(join(dest, "scripts", "watch_video.py"), 0o755); } catch {}

console.log(`✅ video-watcher installed → ${dest}
Next steps:
  1. Make sure python3, ffmpeg/ffprobe and node are on PATH.
  2. Clone Cobalt for URL downloads:  git clone https://github.com/imputnet/cobalt
     (or set VIDEO_WATCHER_COBALT_DIR to your Cobalt api/ folder)
  3. Ask your agent about a video link — the skill takes it from there.`);
