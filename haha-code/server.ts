// haha-code/server.ts — 轻量 HTTP 服务封装，提供 /review 端点供 server 调用
import { join } from "path";
import { appendFileSync, mkdirSync, existsSync } from "fs";

const PORT = parseInt(process.env.HAHA_CODE_PORT || "3000", 10);
const ROOT_DIR = import.meta.dir;
const CLI_PATH = join(ROOT_DIR, "src", "entrypoints", "cli.tsx");
const REVIEW_TIMEOUT = parseInt(process.env.REVIEW_TIMEOUT_MS || "600000", 10); // 10 min

// 日志目录：保存错误日志和工具调用流摘要
const LOG_DIR = join(ROOT_DIR, "logs");
const ERROR_LOG_FILE = join(LOG_DIR, "review-errors.log");
try {
  mkdirSync(LOG_DIR, { recursive: true });
} catch {}

interface ReviewRequest {
  clause: {
    clause_index: number;
    clause_text: string;
    basis_text: string;
    severity: string;
    source_module: string;
  };
  folder_path: string;
  project_context: string;
  tender_context: string;
}

interface ReviewResult {
  result: "pass" | "fail" | "warning" | "error";
  confidence: number;
  reason: string;
  locations: Array<{
    para_index: number;
    text_snippet: string;
    reason: string;
  }>;
  recoverable?: boolean;
}

function buildPrompt(req: ReviewRequest): string {
  let prompt = `请使用 /bid-review skill 审查以下条款。

## 条款信息
- 条款内容：${req.clause.clause_text}
- 条款依据：${req.clause.basis_text}
- 严重等级：${req.clause.severity}

## 项目背景
${req.project_context}
`;

  if (req.tender_context) {
    prompt += `
## 相关招标原文参考
以下是从招标文件中预提取的、与该条款相关的原文片段，用于帮助理解条款的背景和要求。请结合条款内容进行判断，仅在与条款确实相关时才参考这些内容：

${req.tender_context}

`;
  }

  prompt += `## 投标文件位置
文件夹路径：${req.folder_path}

请先调用 /bid-review skill，skill 会自动读取投标文件文件夹进行审查。如果 skill 未被自动触发，请手动输入 /bid-review 后跟随上述条款信息。`;
  return prompt;
}

function parseResult(stdout: string): ReviewResult {
  // 从输出中提取 JSON
  const jsonMatch = stdout.match(/\{[\s\S]*"result"[\s\S]*\}/);
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[0]);
      return {
        result: parsed.result || "error",
        confidence: parseInt(parsed.confidence) || 0,
        reason: parsed.reason || "",
        locations: Array.isArray(parsed.locations) ? parsed.locations : [],
      };
    } catch {}
  }
  return {
    result: "error",
    confidence: 0,
    reason: `智能体输出解析失败: ${stdout.slice(0, 200)}`,
    locations: [],
  };
}

function analyzeExitError(exitCode: number, stderr: string, stdout: string): {
  reason: string;
  recoverable: boolean;
} {
  const stderrText = stderr.slice(0, 2000);
  const stdoutText = stdout.slice(0, 500);

  // Log full details for server-side debugging
  console.error(
    `[haha-code] CLI exited code ${exitCode} | stderr: ${stderrText} | stdout: ${stdoutText}`
  );

  // 持久化到文件：包含完整 stderr、stdout、时间戳
  const timestamp = new Date().toISOString();
  const logEntry = `\n=== ${timestamp} | exit ${exitCode} ===\nSTDERR:\n${stderr}\n\nSTDOUT:\n${stdout}\n${"=".repeat(80)}\n`;
  try {
    appendFileSync(ERROR_LOG_FILE, logEntry);
  } catch {}

  // Exit 137 = 128+9 = SIGKILL，通常是 OOM 被系统强杀
  if (exitCode === 137) {
    return {
      reason: "智能体被系统强杀 (OOM/内存不足)",
      recoverable: false,
    };
  }

  // Exit 143 = 128+15 = SIGTERM，超时被 kill
  if (exitCode === 143) {
    return {
      reason: "智能体执行超时，未在规定时间内完成审查",
      recoverable: false,
    };
  }

  // Exit 1 = 通用错误，从 stderr 中提取根因
  if (exitCode === 1) {
    // API 认证失败
    if (/40[13]|Unauthorized|Authentication|invalid.*(api.key|token)/i.test(stderrText)) {
      return {
        reason: "API 认证失败 (401/403)，请检查 DASHSCOPE_API_KEY 配置",
        recoverable: false,
      };
    }
    // API 频率限制
    if (/429|rate.?limit|Too Many Requests/i.test(stderrText)) {
      return {
        reason: "API 请求频率限制 (429)，请稍后重试",
        recoverable: true,
      };
    }
    // API 服务端错误
    if (/5\d{2}|ECONNREFUSED|Connection refused/i.test(stderrText)) {
      return {
        reason: "API 服务端错误或连接被拒绝",
        recoverable: false, // 服务端问题，重试大概率同样失败
      };
    }
    // Skill 加载失败
    if (/skill.*(not found|not found|不存在)/i.test(stderrText)) {
      return {
        reason: "bid-review skill 加载失败，可能不存在或路径错误",
        recoverable: false,
      };
    }
    // 语法/运行时错误
    const errorMatch = stderrText.match(/(SyntaxError|TypeError|ReferenceError|Error):\s*(.*)/);
    if (errorMatch) {
      return {
        reason: `智能体代码错误: ${errorMatch[1]}: ${errorMatch[2].slice(0, 150)}`,
        recoverable: false,
      };
    }
    // 无法识别的 exit 1，返回 stderr 原文
    // 不可重试：因为如果 stderr 不包含已知可恢复模式，
    // 说明问题大概率是持久性的（配置错误、权限问题等）
    return {
      reason: `智能体执行失败: ${stderrText.slice(0, 300)}`,
      recoverable: false,
    };
  }

  // 其他 exit code
  return {
    reason: `智能体异常退出 (exit ${exitCode}): ${stderrText.slice(0, 300)}`,
    recoverable: exitCode > 128, // 信号导致的退出通常可重试
  };
}

const server = Bun.serve({
  port: PORT,
  async fetch(req: Request): Promise<Response> {
    const url = new URL(req.url);

    // Health check
    if (url.pathname === "/health") {
      return Response.json({ status: "ok" });
    }

    // Static file server: serve images from tender_folder for URL-based image references
    // e.g. /files/data/reviews/xxx/tender_folder/images/img001.jpg
    if (url.pathname.startsWith("/files/")) {
      const filePath = decodeURIComponent(url.pathname.slice("/files/".length));
      // Security: only allow files under /data/
      if (!filePath.startsWith("data/") && !filePath.startsWith("/data/")) {
        return Response.json({ error: "Forbidden" }, { status: 403 });
      }
      const absPath = filePath.startsWith("/") ? filePath : "/" + filePath;
      if (!existsSync(absPath)) {
        return Response.json({ error: "Not found" }, { status: 404 });
      }
      const file = Bun.file(absPath);
      return new Response(file, {
        headers: { "Content-Type": file.type || "application/octet-stream" },
      });
    }

    // Review endpoint
    if (url.pathname === "/review" && req.method === "POST") {
      try {
        const body: ReviewRequest = await req.json();

        if (!body.clause || !body.folder_path) {
          return Response.json(
            { error: "Missing clause or folder_path" },
            { status: 400 }
          );
        }

        const prompt = buildPrompt(body);

        // 调用 haha-code CLI（不使用 stream-json verbose，会超限 6MB 请求体）
        const proc = Bun.spawn(
          [
            "bun",
            "--env-file=.env",
            CLI_PATH,
            "-p",
            prompt,
            "--add-dir",
            body.folder_path,
            "--allowedTools",
            "Read Glob Grep",
            "--max-turns",
            "100",
            "--system-prompt",
            "你是资深招标审查专家。请调用 /bid-review skill 进行审查。先阅读 _图片索引.md 了解所有图片的 AI 预描述。图片描述已嵌入 MD 文件，无需读取原始图片。严格只输出 JSON 结果。",
          ],
          {
            cwd: ROOT_DIR,
            stdout: "pipe",
            stderr: "pipe",
            env: { ...process.env },
          }
        );

        // 超时控制
        const timeout = setTimeout(() => {
          proc.kill();
        }, REVIEW_TIMEOUT);

        const stdout = await new Response(proc.stdout).text();
        const stderr = await new Response(proc.stderr).text();
        clearTimeout(timeout);

        const exitCode = await proc.exited;

        if (exitCode !== 0) {
          const diagnosis = analyzeExitError(exitCode, stderr, stdout);
          return Response.json({
            result: "error",
            confidence: 0,
            reason: diagnosis.reason,
            recoverable: diagnosis.recoverable,
            locations: [],
          });
        }

        // 尝试解析 JSON，失败时重新发送 JSON 修正 prompt
        let result = parseResult(stdout);
        if (result.result === "error" && result.reason.startsWith("智能体输出解析失败")) {
          console.log("[haha-code] JSON parse failed, retrying with repair prompt...");
          const repairPrompt = `你之前的审查输出格式不正确，请将审查结果转换为以下 JSON 格式输出，不要包含任何其他内容：

{
  "result": "pass" | "fail" | "warning",
  "confidence": 0-100,
  "reason": "审查结论的理由",
  "locations": [
    {
      "para_index": 段落编号,
      "text_snippet": "相关原文片段",
      "reason": "为什么该片段与条款相关"
    }
  ]
}

以下是你之前的审查输出：
${stdout.slice(0, 5000)}

请只输出 JSON，不要包含任何其他文字。`;

          const repairProc = Bun.spawn(
            [
              "bun",
              "--env-file=.env",
              CLI_PATH,
              "-p",
              repairPrompt,
              "--add-dir",
              body.folder_path,
              "--allowedTools",
              "Read Glob Grep",
              "--max-turns",
              "20",
              "--system-prompt",
              "你是招标审查助手。请将已有的审查结果转换为 JSON 格式输出。严格只输出 JSON。",
            ],
            {
              cwd: ROOT_DIR,
              stdout: "pipe",
              stderr: "pipe",
              env: { ...process.env },
            }
          );

          const repairTimeout = setTimeout(() => repairProc.kill(), REVIEW_TIMEOUT);
          const repairStdout = await new Response(repairProc.stdout).text();
          clearTimeout(repairTimeout);

          const repairExitCode = await repairProc.exited;
          if (repairExitCode !== 0) {
            console.log(`[haha-code] Repair attempt failed with exit code ${repairExitCode}`);
            return Response.json({
              result: "error",
              confidence: 0,
              reason: `智能体输出解析失败: ${stdout.slice(0, 200)}`,
              locations: [],
            });
          }

          result = parseResult(repairStdout);
          if (result.result === "error" && result.reason.startsWith("智能体输出解析失败")) {
            console.log("[haha-code] JSON repair still failed after retry");
          }
        }

        return Response.json(result);
      } catch (e: any) {
        console.error("Review error:", e);
        return Response.json(
          {
            result: "error",
            confidence: 0,
            reason: `服务内部错误: ${e.message}`,
            locations: [],
          },
          { status: 500 }
        );
      }
    }

    return Response.json({ error: "Not found" }, { status: 404 });
  },
});

console.log(`haha-code review server listening on port ${PORT}`);
