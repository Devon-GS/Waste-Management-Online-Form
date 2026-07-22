from __future__ import annotations

import csv
import io
import os
import sqlite3
import zlib
from datetime import date
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DB_PATH", str(BASE_DIR / "waste_forms.db")))
CSV_PATH = BASE_DIR / "Stock Items.csv"
BROKEN_PIES = [
    ("#1", "P BEEF BURGER PIES (BROKEN)"),
    ("#2", "P NORMAL PIES (BROKEN)"),
    ("#4", "SAMOSA (BROKEN)"),
    ("#6", "P MEGA PIES (BROKEN)"),
    ("#8", "COCKTAIL SUSAGE (BROCKEN)"),
]

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_: Exception | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS stock_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL UNIQUE,
                product_description TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS waste_forms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS waste_form_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                waste_form_id INTEGER NOT NULL,
                stock_item_id INTEGER,
                stock_code TEXT NOT NULL,
                product_description TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (waste_form_id) REFERENCES waste_forms (id) ON DELETE CASCADE,
                FOREIGN KEY (stock_item_id) REFERENCES stock_items (id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS broken_pie_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS broken_pie_entry_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broken_pie_entry_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                product_description TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (broken_pie_entry_id) REFERENCES broken_pie_entries (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS broken_pie_returns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                product_description TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                date_returned TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        seed_stock_items(db)
        db.commit()
    finally:
        db.close()


def seed_stock_items(db: sqlite3.Connection) -> None:
    count = db.execute("SELECT COUNT(*) FROM stock_items").fetchone()[0]
    if count:
        return
    if not CSV_PATH.exists():
        return

    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header_row_index = None
        header = None
        rows = list(reader)
        for index, row in enumerate(rows):
            normalized = [cell.strip() for cell in row]
            if "Stock Code" in normalized and "Pack Description" in normalized:
                header_row_index = index
                header = normalized
                break

        if header_row_index is None:
            return

        stock_code_idx = header.index("Stock Code")
        description_idx = header.index("Pack Description")

        items = []
        for row in rows[header_row_index + 1 :]:
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) <= max(stock_code_idx, description_idx):
                continue
            stock_code = row[stock_code_idx].strip()
            description = row[description_idx].strip()
            if not stock_code or not description:
                continue
            items.append((stock_code, description))

    db.executemany(
        """
        INSERT OR IGNORE INTO stock_items (stock_code, product_description)
        VALUES (?, ?)
        """,
        items,
    )


def fetch_stock_items() -> list[sqlite3.Row]:
    db = get_db()
    return db.execute(
        """
        SELECT id, stock_code, product_description
        FROM stock_items
        ORDER BY product_description COLLATE NOCASE, stock_code COLLATE NOCASE
        """
    ).fetchall()


def fetch_forms() -> list[sqlite3.Row]:
    db = get_db()
    return db.execute(
        """
        SELECT
            wf.id,
            wf.created_at,
            wf.updated_at,
            COALESCE(SUM(CASE WHEN wfi.quantity > 0 THEN 1 ELSE 0 END), 0) AS filled_lines,
            COALESCE(SUM(wfi.quantity), 0) AS total_quantity
        FROM waste_forms wf
        LEFT JOIN waste_form_items wfi ON wfi.waste_form_id = wf.id
        GROUP BY wf.id
        ORDER BY wf.created_at DESC, wf.id DESC
        """
    ).fetchall()


def fetch_form(form_id: int) -> sqlite3.Row | None:
    db = get_db()
    return db.execute(
        "SELECT id, created_at, updated_at FROM waste_forms WHERE id = ?",
        (form_id,),
    ).fetchone()


def fetch_form_items(form_id: int) -> list[sqlite3.Row]:
    db = get_db()
    return db.execute(
        """
        SELECT id, stock_item_id, stock_code, product_description, quantity
        FROM waste_form_items
        WHERE waste_form_id = ?
        ORDER BY product_description COLLATE NOCASE, stock_code COLLATE NOCASE
        """,
        (form_id,),
    ).fetchall()


def fetch_broken_pie_items() -> list[dict[str, str]]:
    return [{"code": code, "product_description": description} for code, description in BROKEN_PIES]


def fetch_broken_pie_entries() -> list[sqlite3.Row]:
    db = get_db()
    return db.execute(
        """
        SELECT id, created_at
        FROM broken_pie_entries
        ORDER BY id DESC
        """
    ).fetchall()


def fetch_broken_pie_entry_items(entry_id: int) -> list[sqlite3.Row]:
    db = get_db()
    return db.execute(
        """
        SELECT id, code, product_description, quantity
        FROM broken_pie_entry_items
        WHERE broken_pie_entry_id = ?
        ORDER BY code COLLATE NOCASE
        """,
        (entry_id,),
    ).fetchall()


def fetch_broken_pie_entry(entry_id: int) -> dict | None:
    db = get_db()
    entry = db.execute(
        "SELECT id, created_at FROM broken_pie_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if entry is None:
        return None
    items = fetch_broken_pie_entry_items(entry_id)
    return {
        "id": entry["id"],
        "created_at": entry["created_at"],
        "items": [
            {
                "code": item["code"],
                "product_description": item["product_description"],
                "quantity": item["quantity"],
            }
            for item in items
        ],
    }


def fetch_broken_pie_returns() -> list[sqlite3.Row]:
    db = get_db()
    return db.execute(
        """
        SELECT id, code, product_description, quantity, date_returned, created_at
        FROM broken_pie_returns
        ORDER BY date_returned DESC, id DESC
        """
    ).fetchall()


def fetch_broken_pie_return(return_id: int) -> sqlite3.Row | None:
    db = get_db()
    return db.execute(
        """
        SELECT id, code, product_description, quantity, date_returned, created_at
        FROM broken_pie_returns
        WHERE id = ?
        """,
        (return_id,),
    ).fetchone()


def save_broken_pie_entry() -> int:
    db = get_db()
    db.execute("INSERT INTO broken_pie_entries DEFAULT VALUES")
    entry_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    item_rows = []
    for item in BROKEN_PIES:
        code, description = item
        quantity = parse_quantity(request.form.get(f"broken_{code}", "0"))
        item_rows.append((entry_id, code, description, quantity))

    db.executemany(
        """
        INSERT INTO broken_pie_entry_items
            (broken_pie_entry_id, code, product_description, quantity)
        VALUES (?, ?, ?, ?)
        """,
        item_rows,
    )
    db.commit()
    return entry_id


def save_broken_pie_return() -> None:
    code = request.form.get("return_code", "").strip()
    product_description = request.form.get("return_description", "").strip()
    quantity = parse_quantity(request.form.get("return_quantity", "0"))
    date_returned = request.form.get("date_returned", "").strip()

    if not code or not product_description or not date_returned:
        raise ValueError("Missing return data")

    db = get_db()
    db.execute(
        """
        INSERT INTO broken_pie_returns (code, product_description, quantity, date_returned)
        VALUES (?, ?, ?, ?)
        """,
        (code, product_description, quantity, date_returned),
    )
    db.commit()


def update_broken_pie_entry(entry_id: int) -> None:
    db = get_db()
    db.execute("DELETE FROM broken_pie_entry_items WHERE broken_pie_entry_id = ?", (entry_id,))

    item_rows = []
    for code, description in BROKEN_PIES:
        quantity = parse_quantity(request.form.get(f"broken_{code}", "0"))
        item_rows.append((entry_id, code, description, quantity))

    db.executemany(
        """
        INSERT INTO broken_pie_entry_items
            (broken_pie_entry_id, code, product_description, quantity)
        VALUES (?, ?, ?, ?)
        """,
        item_rows,
    )
    db.commit()


def update_broken_pie_return(return_id: int) -> None:
    code = request.form.get("return_code", "").strip()
    product_description = request.form.get("return_description", "").strip()
    quantity = parse_quantity(request.form.get("return_quantity", "0"))
    date_returned = request.form.get("date_returned", "").strip()

    if not code or not product_description or not date_returned:
        raise ValueError("Missing return data")

    db = get_db()
    db.execute(
        """
        UPDATE broken_pie_returns
        SET code = ?, product_description = ?, quantity = ?, date_returned = ?
        WHERE id = ?
        """,
        (code, product_description, quantity, date_returned, return_id),
    )
    db.commit()


def delete_broken_pie_entry(entry_id: int) -> None:
    db = get_db()
    db.execute("DELETE FROM broken_pie_entries WHERE id = ?", (entry_id,))
    db.commit()


def delete_broken_pie_return(return_id: int) -> None:
    db = get_db()
    db.execute("DELETE FROM broken_pie_returns WHERE id = ?", (return_id,))
    db.commit()


def build_broken_pie_entries() -> list[dict]:
    entries = []
    for entry in fetch_broken_pie_entries():
        items = fetch_broken_pie_entry_items(entry["id"])
        entries.append(
            {
                "id": entry["id"],
                "created_at": entry["created_at"],
                "items": [
                    {
                        "code": item["code"],
                        "product_description": item["product_description"],
                        "quantity": item["quantity"],
                    }
                    for item in items
                ],
            }
        )
    return entries


def build_form_payload(form_id: int) -> dict:
    form = fetch_form(form_id)
    if form is None:
        return {}
    items = fetch_form_items(form_id)
    return {
        "form": form,
        "items": items,
        "total_quantity": sum(int(item["quantity"]) for item in items),
        "filled_lines": sum(1 for item in items if int(item["quantity"]) > 0),
    }


def save_waste_form_from_request(current_items: list[sqlite3.Row]) -> int:
    db = get_db()
    db.execute("INSERT INTO waste_forms DEFAULT VALUES")
    form_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    item_rows = []
    for item in current_items:
        quantity = parse_quantity(request.form.get(f"qty_{item['id']}", "0"))
        item_rows.append(
            (
                form_id,
                item["id"],
                item["stock_code"],
                item["product_description"],
                quantity,
            )
        )

    db.executemany(
        """
        INSERT INTO waste_form_items
            (waste_form_id, stock_item_id, stock_code, product_description, quantity)
        VALUES (?, ?, ?, ?, ?)
        """,
        item_rows,
    )
    db.execute(
        "UPDATE waste_forms SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (form_id,),
    )
    db.commit()
    return form_id


def update_waste_form(form_id: int, form_items: list[sqlite3.Row]) -> None:
    db = get_db()
    db.execute("DELETE FROM waste_form_items WHERE waste_form_id = ?", (form_id,))

    item_rows = []
    for item in form_items:
        quantity = parse_quantity(request.form.get(f"qty_{item['id']}", "0"))
        item_rows.append(
            (
                form_id,
                item["id"],
                item["stock_code"],
                item["product_description"],
                quantity,
            )
        )

    db.executemany(
        """
        INSERT INTO waste_form_items
            (waste_form_id, stock_item_id, stock_code, product_description, quantity)
        VALUES (?, ?, ?, ?, ?)
        """,
        item_rows,
    )
    db.execute(
        "UPDATE waste_forms SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (form_id,),
    )
    db.commit()


def parse_quantity(value: str) -> int:
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        return 0
    return max(quantity, 0)


def export_csv_bytes(form_id: int) -> bytes:
    payload = build_form_payload(form_id)
    form = payload["form"]
    items = payload["items"]

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Waste Form ID", form["id"]])
    writer.writerow(["Created At", form["created_at"]])
    writer.writerow([])
    writer.writerow(["Stock Code", "Product Description", "Quantity"])
    for item in items:
        if int(item["quantity"]) > 0:
            writer.writerow([item["stock_code"], item["product_description"], item["quantity"]])

    return buffer.getvalue().encode("utf-8-sig")


def _escape_pdf_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _wrap_pdf_lines(lines: list[str], max_chars: int = 92) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        current = ""
        for word in line.split():
            candidate = word if not current else f"{current} {word}"
            if len(candidate) > max_chars:
                if current:
                    wrapped.append(current)
                current = word
            else:
                current = candidate
        if current:
            wrapped.append(current)
    return wrapped


def export_pdf_bytes(form_id: int) -> bytes:
    payload = build_form_payload(form_id)
    form = payload["form"]
    items = payload["items"]

    lines = [
        f"Waste Form #{form['id']}",
        f"Created: {form['created_at']}",
        f"Updated: {form['updated_at']}",
        "",
        "Stock Code | Product Description | Quantity",
        "-" * 90,
    ]
    for item in items:
        if int(item["quantity"]) > 0:
            lines.append(
                f"{item['stock_code']} | {item['product_description']} | {item['quantity']}"
            )

    wrapped_lines = _wrap_pdf_lines(lines, max_chars=96)
    return _build_simple_pdf(wrapped_lines, title=f"Waste Form {form['id']}")


def _build_simple_pdf(lines: list[str], title: str = "Waste Form") -> bytes:
    page_width = 595.28
    page_height = 841.89
    left_margin = 48
    top_margin = 52
    line_height = 14
    usable_height = page_height - (top_margin * 2)
    lines_per_page = max(1, int(usable_height // line_height) - 2)

    pages = [lines[i : i + lines_per_page] for i in range(0, len(lines), lines_per_page)]
    if not pages:
        pages = [[""]]

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")

    page_count = len(pages)
    kids_refs = " ".join(f"{3 + i * 2} 0 R" for i in range(page_count))
    objects.append(f"<< /Type /Pages /Kids [{kids_refs}] /Count {page_count} >>".encode())

    font_obj_num = 3 + page_count * 2

    for index, page_lines in enumerate(pages):
        content_lines = [
            "BT",
            "/F1 18 Tf",
            f"1 0 0 1 {left_margin} {page_height - top_margin} Tm",
            f"({_escape_pdf_text(title)}) Tj",
            "/F1 10 Tf",
        ]
        y = page_height - top_margin - 28
        for line in page_lines:
            content_lines.append(f"1 0 0 1 {left_margin} {y:.2f} Tm")
            content_lines.append(f"({_escape_pdf_text(line)}) Tj")
            y -= line_height
        content_lines.append("ET")
        content_stream = "\n".join(content_lines).encode("latin-1", "replace")
        content_obj_num = 4 + index * 2
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width:.2f} {page_height:.2f}] "
                f"/Resources << /Font << /F1 {font_obj_num} 0 R >> >> /Contents {content_obj_num} 0 R >>"
            ).encode()
        )
        objects.append(
            b"<< /Length "
            + str(len(content_stream)).encode()
            + b" /Filter /FlateDecode >>\nstream\n"
            + zlib.compress(content_stream)
            + b"\nendstream"
        )

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    pdf = io.BytesIO()
    pdf.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj_number, body in enumerate(objects, start=1):
        offsets.append(pdf.tell())
        pdf.write(f"{obj_number} 0 obj\n".encode("ascii"))
        pdf.write(body)
        pdf.write(b"\nendobj\n")

    xref_start = pdf.tell()
    pdf.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.write(b"0000000000 65535 f \n")
    for offset in offsets:
        pdf.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.write(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_start}\n"
            "%%EOF"
        ).encode("ascii")
    )
    return pdf.getvalue()


@app.route("/", methods=["GET"])
def index():
    stock_items = fetch_stock_items()
    return render_template(
        "index.html",
        stock_items=stock_items,
        active_page="home",
    )


@app.route("/stock-items/add", methods=["POST"])
def add_stock_item():
    stock_code = request.form.get("stock_code", "").strip()
    product_description = request.form.get("product_description", "").strip().upper()

    if not stock_code or not product_description:
        flash("Please provide both a stock code and a product description.", "danger")
        return redirect(url_for("index"))

    db = get_db()
    db.execute(
        """
        INSERT INTO stock_items (stock_code, product_description)
        VALUES (?, ?)
        ON CONFLICT(stock_code) DO UPDATE SET
            product_description = excluded.product_description
        """,
        (stock_code, product_description),
    )
    db.commit()
    flash("Stock item saved.", "success")
    return redirect(url_for("index"))


@app.route("/stock-items/<int:item_id>/delete", methods=["POST"])
def delete_stock_item(item_id: int):
    db = get_db()
    db.execute("DELETE FROM stock_items WHERE id = ?", (item_id,))
    db.commit()
    flash("Stock item deleted.", "warning")
    return redirect(url_for("index"))


def delete_stock_items(item_ids: list[int]) -> int:
    if not item_ids:
        return 0

    placeholders = ",".join("?" for _ in item_ids)
    db = get_db()
    cursor = db.execute(
        f"DELETE FROM stock_items WHERE id IN ({placeholders})",
        item_ids,
    )
    db.commit()
    return cursor.rowcount


@app.route("/waste-form", methods=["POST"])
def save_or_export_waste_form():
    stock_items = fetch_stock_items()
    action = request.form.get("action", "save")

    if action == "delete_selected":
        selected_ids = []
        for raw_id in request.form.getlist("delete_ids"):
            try:
                selected_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue

        deleted_count = delete_stock_items(selected_ids)
        if deleted_count:
            flash(f"Deleted {deleted_count} stock item(s).", "warning")
        else:
            flash("Select at least one stock item to delete.", "danger")
        return redirect(url_for("index"))

    form_id = save_waste_form_from_request(stock_items)

    if action == "save":
        flash("Waste form saved.", "success")
        return redirect(url_for("view_form", form_id=form_id))

    if action == "export_csv":
        data = export_csv_bytes(form_id)
        return send_file(
            io.BytesIO(data),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"waste-form-{form_id}.csv",
        )

    if action == "export_pdf":
        data = export_pdf_bytes(form_id)
        return send_file(
            io.BytesIO(data),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"waste-form-{form_id}.pdf",
        )

    flash("Unknown action.", "danger")
    return redirect(url_for("index"))


@app.route("/forms", methods=["GET"])
def forms_list():
    forms = fetch_forms()
    return render_template("forms.html", forms=forms, active_page="forms")


@app.route("/forms/<int:form_id>", methods=["GET"])
def view_form(form_id: int):
    payload = build_form_payload(form_id)
    if not payload:
        flash("Saved form not found.", "danger")
        return redirect(url_for("forms_list"))

    return render_template(
        "form_detail.html",
        form=payload["form"],
        items=payload["items"],
        total_quantity=payload["total_quantity"],
        filled_lines=payload["filled_lines"],
        active_page="forms",
        edit_mode=False,
    )


@app.route("/forms/<int:form_id>/edit", methods=["GET", "POST"])
def edit_form(form_id: int):
    payload = build_form_payload(form_id)
    if not payload:
        flash("Saved form not found.", "danger")
        return redirect(url_for("forms_list"))

    if request.method == "POST":
        update_waste_form(form_id, payload["items"])
        flash("Waste form updated.", "success")
        return redirect(url_for("view_form", form_id=form_id))

    return render_template(
        "form_detail.html",
        form=payload["form"],
        items=payload["items"],
        total_quantity=payload["total_quantity"],
        filled_lines=payload["filled_lines"],
        active_page="forms",
        edit_mode=True,
    )


@app.route("/broken-pies", methods=["GET", "POST"])
def broken_pies():
    if request.method == "POST":
        action = request.form.get("action", "save_broken")

        if action == "save_broken":
            save_broken_pie_entry()
            flash("Broken pie counts saved.", "success")
            return redirect(url_for("broken_pies"))

        if action == "save_return":
            try:
                save_broken_pie_return()
            except ValueError:
                flash("Please provide code, product description, quantity, and return date.", "danger")
                return redirect(url_for("broken_pies"))
            flash("Returned pie record saved.", "success")
            return redirect(url_for("broken_pies"))

    return render_template(
        "broken_pies.html",
        active_page="broken_pies",
        broken_pies=fetch_broken_pie_items(),
        broken_entries=build_broken_pie_entries(),
        return_rows=fetch_broken_pie_returns(),
        today=date.today().isoformat(),
    )


@app.route("/broken-pies/entries/<int:entry_id>/edit", methods=["GET", "POST"])
def edit_broken_pies_entry(entry_id: int):
    entry = fetch_broken_pie_entry(entry_id)
    if entry is None:
        flash("Broken pie snapshot not found.", "danger")
        return redirect(url_for("broken_pies"))

    if request.method == "POST":
        update_broken_pie_entry(entry_id)
        flash("Broken pie snapshot updated.", "success")
        return redirect(url_for("broken_pies"))

    return render_template(
        "broken_pie_edit.html",
        active_page="broken_pies",
        edit_type="snapshot",
        entry=entry,
        quantities={item["code"]: item["quantity"] for item in entry["items"]},
        broken_pies=fetch_broken_pie_items(),
        today=date.today().isoformat(),
    )


@app.route("/broken-pies/returns/<int:return_id>/edit", methods=["GET", "POST"])
def edit_broken_pies_return(return_id: int):
    row = fetch_broken_pie_return(return_id)
    if row is None:
        flash("Returned pie log entry not found.", "danger")
        return redirect(url_for("broken_pies"))

    if request.method == "POST":
        try:
            update_broken_pie_return(return_id)
        except ValueError:
            flash("Please provide code, product description, quantity, and return date.", "danger")
            return redirect(url_for("edit_broken_pies_return", return_id=return_id))
        flash("Returned pie log entry updated.", "success")
        return redirect(url_for("broken_pies"))

    return render_template(
        "broken_pie_edit.html",
        active_page="broken_pies",
        edit_type="return",
        row=row,
        broken_pies=fetch_broken_pie_items(),
        today=date.today().isoformat(),
    )


@app.route("/broken-pies/entries/<int:entry_id>/delete", methods=["POST"])
def delete_broken_pies_entry(entry_id: int):
    delete_broken_pie_entry(entry_id)
    flash("Broken pie snapshot deleted.", "warning")
    return redirect(url_for("broken_pies"))


@app.route("/broken-pies/returns/<int:return_id>/delete", methods=["POST"])
def delete_broken_pies_return(return_id: int):
    delete_broken_pie_return(return_id)
    flash("Returned pie log entry deleted.", "warning")
    return redirect(url_for("broken_pies"))


@app.route("/forms/<int:form_id>/delete", methods=["POST"])
def delete_form(form_id: int):
    db = get_db()
    db.execute("DELETE FROM waste_forms WHERE id = ?", (form_id,))
    db.commit()
    flash("Waste form deleted.", "warning")
    return redirect(url_for("forms_list"))


@app.route("/forms/<int:form_id>/export/csv", methods=["GET", "POST"])
def export_form_csv(form_id: int):
    if request.method == "POST":
        current_items = fetch_stock_items()
        if current_items:
            update_waste_form(form_id, current_items)

    data = export_csv_bytes(form_id)
    return send_file(
        io.BytesIO(data),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"waste-form-{form_id}.csv",
    )


@app.route("/forms/<int:form_id>/export/pdf", methods=["GET", "POST"])
def export_form_pdf(form_id: int):
    if request.method == "POST":
        current_items = fetch_stock_items()
        if current_items:
            update_waste_form(form_id, current_items)

    data = export_pdf_bytes(form_id)
    return send_file(
        io.BytesIO(data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"waste-form-{form_id}.pdf",
    )


init_db()


if __name__ == "__main__":
    app.run(debug=True)
