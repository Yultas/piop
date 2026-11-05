import asyncio
import os
import sys
import tempfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from backend.app.auth import get_current_user
from backend.app.config import settings
from backend.app.models import User

router = APIRouter(prefix="/api/typst", tags=["typst"])

MAX_CODE_CHARS = 200_000

# Runs in a child process so a runaway document can be killed. The address-space
# limit caps memory; the parent enforces the wall-clock limit. Typst's root is the
# private temp directory, so `#read` can only reach files the request created.
_WORKER = """
import os, resource, sys
import typst
resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
root, fmt = sys.argv[1], sys.argv[2]
out = typst.compile(os.path.join(root, "main.typ"), root=root, format=fmt)
if len(out) > 20 * 1024 * 1024:
    sys.stderr.write("output too large")
    sys.exit(3)
sys.stdout.buffer.write(out)
"""

# Created on first use so it binds to the running event loop.
_compile_slots = None

class TypstCompileRequest(BaseModel):
    code: str
    format: str = "svg" # "svg" or "pdf"

@router.post("/compile")
async def compile_typst(req: TypstCompileRequest, current_user: User = Depends(get_current_user)):
    global _compile_slots
    if len(req.code) > MAX_CODE_CHARS:
        raise HTTPException(status_code=413, detail="typst.too_large")
    if not req.code.strip():
        return {"result": "", "format": req.format}

    output_format = req.format.lower()
    if output_format not in ["svg", "pdf"]:
        output_format = "svg"

    if _compile_slots is None:
        _compile_slots = asyncio.Semaphore(settings.TYPST_MAX_CONCURRENT)

    with tempfile.TemporaryDirectory() as root:
        with open(os.path.join(root, "main.typ"), "w", encoding="utf-8") as f:
            f.write(req.code)

        async with _compile_slots:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "-c", _WORKER, root, output_format,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"PATH": os.environ.get("PATH", ""), "HOME": root, "LANG": "C.UTF-8"},
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), settings.TYPST_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                raise HTTPException(status_code=408, detail="typst.timeout")
            finally:
                # Also covers client disconnect (cancellation), not just timeout.
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

    if proc.returncode == 3:
        raise HTTPException(status_code=413, detail="typst.output_too_large")
    if proc.returncode != 0:
        lines = [line for line in stderr.decode("utf-8", errors="replace").splitlines() if line.strip()]
        message = lines[-1][:500] if lines else "unknown error"
        raise HTTPException(status_code=400, detail=f"Typst compilation error: {message}")

    if output_format == "svg":
        svg_text = stdout.decode("utf-8", errors="replace")
        return {"result": svg_text, "format": "svg"}
    return Response(
        content=stdout,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=document.pdf"}
    )
