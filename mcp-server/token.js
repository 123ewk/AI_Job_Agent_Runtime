// Token 管理 —— 三方共享的浏览器桥认证令牌。
//
// 优先级（高 → 低）：
//   1. 环境变量 BROWSER_MCP_TOKEN（后端/部署方显式指定）
//   2. ~/.browser-mcp-secrets.json（本机持久化，0600 权限；browser-mcp-lite 同款格式，
//      保证与既有安装兼容）
//   3. 首次运行自动生成 randomBytes(32).hex，写入文件（0600）
//
// 消费方：
//   - Chrome 扩展：用户在 popup 粘贴令牌 → chrome.storage.local
//   - 后端 Tool Adapter：读 settings.browser_mcp_token，为空时回退同一文件
//   - server：/mcp 的 Bearer 校验 + /ws 首条 auth 消息校验
import { randomBytes } from "crypto";
import { readFileSync, writeFileSync, chmodSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import { spawn } from "child_process";

const secretsPath = join(homedir(), ".browser-mcp-secrets.json");

/**
 * 把文本写入系统剪贴板（跨平台）。
 * win32 -> clip / darwin -> pbcopy / linux -> xclip（缺失则返回 false，仅打印）。
 */
export function copyToClipboard(text) {
  return new Promise((resolve) => {
    let cmd;
    let args = [];
    if (process.platform === "win32") {
      cmd = "clip";
    } else if (process.platform === "darwin") {
      cmd = "pbcopy";
    } else {
      cmd = "xclip";
      args = ["-selection", "clipboard"];
    }
    try {
      const child = spawn(cmd, args, { stdio: ["pipe", "ignore", "ignore"] });
      child.on("error", () => resolve(false));
      child.on("close", () => resolve(true));
      child.stdin.write(text);
      child.stdin.end();
    } catch {
      resolve(false);
    }
  });
}

/** 读 ~/.browser-mcp-secrets.json 中的 token，缺失/非法返回 null。 */
export function loadTokenFromFile() {
  try {
    const secrets = JSON.parse(readFileSync(secretsPath, "utf8"));
    return secrets.token && secrets.token.length >= 32 ? secrets.token : null;
  } catch {
    return null;
  }
}

/** 读取当前生效的 token（env 优先），无则 null。 */
export function loadToken() {
  const envToken = process.env.BROWSER_MCP_TOKEN;
  if (envToken && envToken.length >= 32) return envToken;
  return loadTokenFromFile();
}

/** 确保 token 存在：env → 文件 → 生成。始终强制文件 0600。返回 { token, source, isNew }。 */
export function ensureToken() {
  const envToken = process.env.BROWSER_MCP_TOKEN;
  if (envToken && envToken.length >= 32) {
    return { token: envToken, source: "env", isNew: false };
  }

  const existing = loadTokenFromFile();
  if (existing) {
    // 每次启动都强制权限（文件可能被放宽）
    try { chmodSync(secretsPath, 0o600); } catch { /* 可能无所有权 */ }
    return { token: existing, source: "file", isNew: false };
  }

  const token = randomBytes(32).toString("hex");
  let secrets = {};
  try { secrets = JSON.parse(readFileSync(secretsPath, "utf8")); } catch { /* 首次 */ }
  secrets.token = token;

  writeFileSync(secretsPath, JSON.stringify(secrets, null, 2) + "\n", "utf8");
  chmodSync(secretsPath, 0o600);

  return { token, source: "generated", isNew: true };
}

// CLI：node token.js --print → 打印 token（自动复制到剪贴板）供扩展 popup 粘贴
if (process.argv[2] === "--print") {
  const { token, source } = ensureToken();
  const sep = "━".repeat(53);
  console.log(`\n${sep}`);
  console.log("Auth Token  (paste into Chrome Extension popup)");
  console.log(token);
  console.log(sep);
  console.log(`来源: ${source}`);
  console.log(`文件: ${secretsPath}`);
  console.log(sep);
  copyToClipboard(token).then((copied) => {
    if (copied) {
      console.log("✅ 已自动复制到剪贴板 —— 直接 Ctrl+V 粘贴到扩展 popup 的「浏览器桥」输入框即可");
    } else {
      console.log("⚠ 自动复制失败（缺少 clip/pbcopy/xclip），请手动选中上方 token 复制");
    }
    console.log(sep);
  });
}
