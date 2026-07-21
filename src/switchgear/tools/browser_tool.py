import time
from uuid import uuid4

from switchgear.tools.base import Tool


def make_browser_tool(manager, storage) -> Tool:
    async def _browser(op: str, url: str | None = None, selector: str | None = None,
                        value: str | None = None, file_path: str | None = None) -> dict:
        session = await manager.session()

        if op == "goto":
            if not url:
                return {"error": "goto requires url"}
            result = await session.goto(url)
            detail = url
        elif op == "read":
            return await session.read()
        elif op == "fill":
            if not selector or value is None:
                return {"error": "fill requires selector and value"}
            result = await session.fill(selector, value)
            detail = selector
        elif op == "click":
            if not selector:
                return {"error": "click requires selector"}
            result = await session.click(selector)
            detail = selector
        elif op == "screenshot":
            filename = f"shot-{uuid4().hex[:10]}.png"
            out_path = str(manager.screenshot_dir / filename)
            await session.screenshot(out_path)
            return {"file": filename}
        elif op == "upload":
            if not selector or not file_path:
                return {"error": "upload requires selector and file_path"}
            result = await session.upload(selector, file_path)
            detail = selector
        else:
            return {"error": f"unknown op: {op}"}

        await storage.put("audit", f"browser-{uuid4().hex}", {
            "tool": "browser", "op": op, "detail": detail, "at": time.time()})
        return result

    return Tool(
        name="browser",
        description=(
            "Drive a headless browser page: goto (navigate), read (visible text + "
            "form fields), fill, click (widgets/pagination, no submit semantics), "
            "screenshot, upload. There is no submit op — form submission is a "
            "separate reviewed service action, not a direct tool call."
        ),
        parameters={"type": "object", "properties": {
            "op": {"type": "string",
                   "enum": ["goto", "read", "fill", "click", "screenshot", "upload"]},
            "url": {"type": "string"},
            "selector": {"type": "string"},
            "value": {"type": "string"},
            "file_path": {"type": "string"},
        }, "required": ["op"]},
        handler=_browser,
    )
