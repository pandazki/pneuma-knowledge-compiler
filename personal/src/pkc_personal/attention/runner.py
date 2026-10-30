"""One bounded judgment invocation. No canonical write tools or compile executor."""

from __future__ import annotations
import asyncio
import json
import os
import signal
import tempfile
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pneuma_knowledge_service.wiring import build_chat_model_for


class OutputValidationError(ValueError):
    """The executor returned content that cannot represent an attention batch."""


async def subprocess_text(
    argv: list[str],
    prompt: str,
    cwd: Path,
    env: dict,
    output: Path | None = None,
    timeout: float = 180,
) -> str:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(prompt.encode()), timeout
        )
        if process.returncode:
            # Do not expose provider output (which can echo source text or credentials) in UI status.
            raise RuntimeError(
                f"attention executor exited {process.returncode}; check its login/model configuration"
            )
        return output.read_text() if output else stdout.decode()
    finally:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


async def judge(library, settings, system: str, packet: dict) -> dict:
    prompt = json.dumps(packet, ensure_ascii=False)
    choices = library.state.choices
    if choices.backend == "api":
        model = build_chat_model_for(settings, "recall")
        response = await asyncio.wait_for(
            model.ainvoke(
                [SystemMessage(content=system), HumanMessage(content=prompt)]
            ),
            180,
        )
        answer = response.content
        if isinstance(answer, list):
            answer = "".join(p.get("text", "") for p in answer if isinstance(p, dict))
    else:
        # Empty work directory: neither canonical nor the library's Steward skill is installed.
        with tempfile.TemporaryDirectory(prefix="pkc-fold-") as temporary:
            cwd = Path(temporary)
            env = dict(os.environ)
            for key in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
                env.pop(key, None)
            if choices.backend == "codex":
                output = cwd / "answer.json"
                argv = [
                    "codex",
                    "exec",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--ephemeral",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "-c",
                    "features.shell_tool=false",
                    "-c",
                    "features.unified_exec=false",
                    "-c",
                    "features.js_repl=false",
                    "-c",
                    "features.multi_agent=false",
                    "-c",
                    'web_search="disabled"',
                    "-c",
                    "features.apps=false",
                    "--output-last-message",
                    str(output),
                ]
                if choices.model:
                    argv += ["--model", choices.model]
                if choices.reasoning_effort:
                    argv += [
                        "-c",
                        f'model_reasoning_effort="{choices.reasoning_effort}"',
                    ]
                argv += ["-"]
                answer = await subprocess_text(
                    argv, system + "\n\n" + prompt, cwd, env, output
                )
            else:
                argv = [
                    "claude",
                    "-p",
                    "--tools",
                    "",
                    "--strict-mcp-config",
                    "--mcp-config",
                    '{"mcpServers":{}}',
                    "--setting-sources",
                    "",
                    "--no-session-persistence",
                    "--output-format",
                    "text",
                    "--system-prompt",
                    system,
                ]
                if choices.model:
                    argv += ["--model", choices.model]
                answer = await subprocess_text(argv, prompt, cwd, env)
    text = str(answer).strip()
    if text.startswith("```"):
        text = text.partition("\n")[2].rsplit("```", 1)[0].strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise OutputValidationError("attention response must be valid JSON") from error
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("declarations"), list)
        or not isinstance(result.get("acknowledges"), list)
    ):
        raise OutputValidationError(
            "attention response must contain declarations and acknowledges arrays"
        )
    return {key: result[key] for key in ("declarations", "acknowledges")} | {
        "reflection": result.get("reflection")
    }
