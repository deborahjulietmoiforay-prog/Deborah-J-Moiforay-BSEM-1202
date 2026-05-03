from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Literal, Optional
import asyncio

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field


# Create the FastAPI application instance.
app: FastAPI = FastAPI(title="Library System API", version="1.0.0")


# A simple type alias for the status of a book in inventory.
BookStatus = Literal["available", "borrowed"]


class Book(BaseModel):
    """Represents a single book record in the library."""

    id: int
    title: str
    author: str
    category: str
    status: BookStatus = "available"


class BorrowRequest(BaseModel):
    """Input payload for borrowing a book."""

    user_id: int = Field(..., gt=0)
    book_id: int = Field(..., gt=0)
    loan_days: int = Field(14, ge=1, le=60)


class ReturnRequest(BaseModel):
    """Input payload for returning a book."""

    user_id: int = Field(..., gt=0)
    book_id: int = Field(..., gt=0)


class LoanRecord(BaseModel):
    """Tracks a borrow transaction and overdue/fine details."""

    user_id: int
    book_id: int
    borrowed_at: datetime
    due_at: datetime
    returned_at: Optional[datetime] = None
    fine_paid: float = 0.0


# Simulated in-memory data stores (no external database used).
books: Dict[int, Book] = {
    1: Book(id=1, title="Python Basics", author="A. Coder", category="Programming"),
    2: Book(id=2, title="Async in Practice", author="B. Dev", category="Programming"),
    3: Book(id=3, title="World History 101", author="C. Scholar", category="History"),
    4: Book(id=4, title="Creative Writing", author="D. Author", category="Literature"),
}

users: Dict[int, str] = {
    1: "Deborah",
    2: "Michael",
    3: "Fatima",
}

loans: List[LoanRecord] = []

# Use a lock so concurrent requests update shared lists safely.
loans_lock: asyncio.Lock = asyncio.Lock()

# Fine policy: $1.50 for each day overdue.
FINE_PER_DAY: float = 1.50


def calculate_fine(due_at: datetime, returned_at: datetime) -> float:
    """Calculate overdue fine based on whole/partial overdue days."""
    if returned_at <= due_at:
        return 0.0

    overdue_seconds: float = (returned_at - due_at).total_seconds()
    overdue_days: int = int((overdue_seconds + 86399) // 86400)
    return round(overdue_days * FINE_PER_DAY, 2)


@app.get("/books/search", response_model=List[Book])
async def search_books(
    title: Optional[str] = Query(default=None),
    author: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
) -> List[Book]:
    """
    Search books by title, author, and/or category.
    Any combination of filters can be provided.
    """
    await asyncio.sleep(0)
    results: List[Book] = list(books.values())

    if title:
        lowered_title: str = title.lower()
        results = [book for book in results if lowered_title in book.title.lower()]
    if author:
        lowered_author: str = author.lower()
        results = [book for book in results if lowered_author in book.author.lower()]
    if category:
        lowered_category: str = category.lower()
        results = [book for book in results if lowered_category in book.category.lower()]

    return results


@app.post("/books/borrow")
async def borrow_book(request: BorrowRequest) -> Dict[str, object]:
    """Borrow an available book for a specific user."""
    await asyncio.sleep(0)

    if request.user_id not in users:
        raise HTTPException(status_code=404, detail="User not found.")
    if request.book_id not in books:
        raise HTTPException(status_code=404, detail="Book not found.")

    async with loans_lock:
        selected_book: Book = books[request.book_id]
        if selected_book.status == "borrowed":
            raise HTTPException(status_code=400, detail="Book is already borrowed.")

        borrowed_at: datetime = datetime.now(timezone.utc)
        due_at: datetime = borrowed_at + timedelta(days=request.loan_days)

        selected_book.status = "borrowed"
        books[request.book_id] = selected_book

        loans.append(
            LoanRecord(
                user_id=request.user_id,
                book_id=request.book_id,
                borrowed_at=borrowed_at,
                due_at=due_at,
            )
        )

    return {
        "message": "Book borrowed successfully.",
        "user": users[request.user_id],
        "book": selected_book.title,
        "due_at": due_at.isoformat(),
    }


@app.post("/books/return")
async def return_book(request: ReturnRequest) -> Dict[str, object]:
    """Return a previously borrowed book and calculate fines if overdue."""
    await asyncio.sleep(0)

    if request.user_id not in users:
        raise HTTPException(status_code=404, detail="User not found.")
    if request.book_id not in books:
        raise HTTPException(status_code=404, detail="Book not found.")

    async with loans_lock:
        active_loan: Optional[LoanRecord] = None
        for loan in loans:
            if (
                loan.user_id == request.user_id
                and loan.book_id == request.book_id
                and loan.returned_at is None
            ):
                active_loan = loan
                break

        if active_loan is None:
            raise HTTPException(status_code=400, detail="No active loan found.")

        now_utc: datetime = datetime.now(timezone.utc)
        fine: float = calculate_fine(active_loan.due_at, now_utc)

        active_loan.returned_at = now_utc
        books[request.book_id].status = "available"

    return {
        "message": "Book returned successfully.",
        "fine_due": fine,
        "returned_at": now_utc.isoformat(),
    }


@app.get("/loans/overdue")
async def get_overdue_loans() -> List[Dict[str, object]]:
    """Return all active overdue loans with calculated fine amounts."""
    await asyncio.sleep(0)

    now_utc: datetime = datetime.now(timezone.utc)
    overdue_items: List[Dict[str, object]] = []

    async with loans_lock:
        for loan in loans:
            if loan.returned_at is None and loan.due_at < now_utc:
                fine_due: float = calculate_fine(loan.due_at, now_utc)
                overdue_items.append(
                    {
                        "user_id": loan.user_id,
                        "user_name": users.get(loan.user_id, "Unknown"),
                        "book_id": loan.book_id,
                        "book_title": books[loan.book_id].title,
                        "due_at": loan.due_at.isoformat(),
                        "fine_due": fine_due,
                    }
                )

    return overdue_items


@app.get("/")
async def health_check() -> Dict[str, str]:
    """Simple root endpoint to confirm the API is running."""
    return {"status": "Library API is running."}
