from datetime import date

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from db import (
    add_customer,
    add_expense,
    add_invoice_item,
    add_invoice_payment,
    create_invoice,
    get_financial_metrics,
    get_invoice_details,
    list_customers,
    list_expenses,
    list_invoices,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/finance", response_class=HTMLResponse)
async def finance_dashboard(request: Request):
    invoices = list_invoices()
    customers = list_customers()
    expenses = list_expenses(limit=25)
    metrics = get_financial_metrics()

    selected_id = request.query_params.get("invoice_id")
    selected_invoice = None
    invoice_items = []
    invoice_payments = []
    if selected_id:
        try:
            selected_invoice, invoice_items, invoice_payments = get_invoice_details(int(selected_id))
        except ValueError:
            selected_invoice = None

    return templates.TemplateResponse(
        "finance.html",
        {
            "request": request,
            "today": date.today().isoformat(),
            "metrics": metrics,
            "invoices": invoices,
            "customers": customers,
            "expenses": expenses,
            "selected_invoice": selected_invoice,
            "invoice_items": invoice_items,
            "invoice_payments": invoice_payments,
        },
    )


@router.post("/finance/customers")
async def create_customer_action(
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
):
    if not name.strip():
        raise HTTPException(status_code=400, detail="Customer name is required")
    add_customer(name=name, email=email, phone=phone, notes=notes)
    return RedirectResponse(url="/finance", status_code=303)


@router.post("/finance/invoices")
async def create_invoice_action(
    invoice_number: str = Form(...),
    customer_id: str = Form(""),
    issue_date: str = Form(...),
    due_date: str = Form(""),
    notes: str = Form(""),
):
    customer_value = int(customer_id) if customer_id else None
    invoice_id = create_invoice(
        invoice_number=invoice_number,
        customer_id=customer_value,
        issue_date=issue_date,
        due_date=due_date,
        notes=notes,
    )
    return RedirectResponse(url=f"/finance?invoice_id={invoice_id}", status_code=303)


@router.post("/finance/invoices/{invoice_id}/items")
async def create_invoice_item_action(
    invoice_id: int,
    description: str = Form(...),
    quantity: int = Form(...),
    unit_price: float = Form(...),
):
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    if unit_price < 0:
        raise HTTPException(status_code=400, detail="Unit price cannot be negative")
    add_invoice_item(
        invoice_id=invoice_id,
        description=description,
        quantity=quantity,
        unit_price=unit_price,
    )
    return RedirectResponse(url=f"/finance?invoice_id={invoice_id}", status_code=303)


@router.post("/finance/invoices/{invoice_id}/payments")
async def create_invoice_payment_action(
    invoice_id: int,
    amount: float = Form(...),
    payment_date: str = Form(...),
    method: str = Form(""),
    notes: str = Form(""),
):
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be greater than zero")
    add_invoice_payment(
        invoice_id=invoice_id,
        amount=amount,
        payment_date=payment_date,
        method=method,
        notes=notes,
    )
    return RedirectResponse(url=f"/finance?invoice_id={invoice_id}", status_code=303)


@router.post("/finance/expenses")
async def create_expense_action(
    expense_date: str = Form(...),
    category: str = Form(...),
    vendor: str = Form(""),
    amount: float = Form(...),
    notes: str = Form(""),
):
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Expense amount must be greater than zero")
    add_expense(
        expense_date=expense_date,
        category=category,
        vendor=vendor,
        amount=amount,
        notes=notes,
    )
    return RedirectResponse(url="/finance", status_code=303)
