from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from db import list_history

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
        },
    )


@router.get("/history/list", response_class=HTMLResponse)
async def history_list(request: Request, limit: int = 200):
    history_rows = list_history(limit=limit)
    return templates.TemplateResponse(
        "partials/history_list.html",
        {
            "request": request,
            "history": history_rows,
        },
    )
