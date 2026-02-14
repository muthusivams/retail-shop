from __future__ import annotations

import html
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "retail_shop.db"
HOST = "0.0.0.0"
PORT = 5000
TAX_RATE = 0.05

INITIAL_PRODUCTS = [
    ("Rice (5kg)", 350.00),
    ("Cooking Oil (1L)", 140.00),
    ("Sugar (1kg)", 48.00),
    ("Tea Powder (250g)", 120.00),
    ("Soap Bar", 35.00),
]


def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL CHECK(price >= 0)
            );
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                subtotal REAL NOT NULL,
                tax REAL NOT NULL,
                total REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sale_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                line_total REAL NOT NULL,
                FOREIGN KEY(sale_id) REFERENCES sales(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            );
            """
        )
        existing = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
        if existing == 0:
            conn.executemany("INSERT INTO products(name, price) VALUES(?, ?)", INITIAL_PRODUCTS)


def fetch_page_data() -> tuple[list[sqlite3.Row], sqlite3.Row | None, list[sqlite3.Row]]:
    with db_conn() as conn:
        products = conn.execute("SELECT id, name, price FROM products ORDER BY id").fetchall()
        latest_bill = conn.execute(
            "SELECT id, created_at, subtotal, tax, total FROM sales ORDER BY id DESC LIMIT 1"
        ).fetchone()

        bill_items: list[sqlite3.Row] = []
        if latest_bill:
            bill_items = conn.execute(
                """
                SELECT p.name, si.quantity, si.unit_price, si.line_total
                FROM sale_items si
                JOIN products p ON p.id = si.product_id
                WHERE si.sale_id = ?
                ORDER BY si.id
                """,
                (latest_bill["id"],),
            ).fetchall()

    return products, latest_bill, bill_items


def create_bill(form_data: dict[str, list[str]]) -> None:
    with db_conn() as conn:
        products = conn.execute("SELECT id, price FROM products ORDER BY id").fetchall()
        sale_rows: list[tuple[int, int, float, float]] = []

        for product in products:
            raw = form_data.get(f"qty_{product['id']}", ["0"])[0]
            try:
                qty = int(raw)
            except ValueError:
                qty = 0

            if qty > 0:
                unit_price = float(product["price"])
                line_total = qty * unit_price
                sale_rows.append((product["id"], qty, unit_price, line_total))

        if not sale_rows:
            return

        subtotal = sum(line_total for _, _, _, line_total in sale_rows)
        tax = round(subtotal * TAX_RATE, 2)
        total = round(subtotal + tax, 2)

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            "INSERT INTO sales(created_at, subtotal, tax, total) VALUES (?, ?, ?, ?)",
            (created_at, subtotal, tax, total),
        )
        sale_id = cur.lastrowid

        conn.executemany(
            """
            INSERT INTO sale_items(sale_id, product_id, quantity, unit_price, line_total)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(sale_id, pid, qty, price, line_total) for pid, qty, price, line_total in sale_rows],
        )


def render_html() -> str:
    products, latest_bill, bill_items = fetch_page_data()

    product_rows = "".join(
        f"""
        <tr>
            <td>{html.escape(product['name'])}</td>
            <td>{product['price']:.2f}</td>
            <td><input type='number' min='0' name='qty_{product['id']}' value='0' /></td>
        </tr>
        """
        for product in products
    )

    if latest_bill:
        bill_row_html = "".join(
            f"""
            <tr>
                <td>{html.escape(item['name'])}</td>
                <td>{item['quantity']}</td>
                <td>{item['unit_price']:.2f}</td>
                <td>{item['line_total']:.2f}</td>
            </tr>
            """
            for item in bill_items
        )

        bill_html = f"""
        <p><strong>Bill ID:</strong> {latest_bill['id']}</p>
        <p><strong>Date:</strong> {latest_bill['created_at']}</p>
        <table>
            <thead><tr><th>Item</th><th>Qty</th><th>Unit Price (₹)</th><th>Line Total (₹)</th></tr></thead>
            <tbody>{bill_row_html}</tbody>
        </table>
        <div class='totals'>
            <p>Subtotal: ₹{latest_bill['subtotal']:.2f}</p>
            <p>Tax (5%): ₹{latest_bill['tax']:.2f}</p>
            <p><strong>Total: ₹{latest_bill['total']:.2f}</strong></p>
        </div>
        """
    else:
        bill_html = "<p>No bills generated yet.</p>"

    return f"""
    <!doctype html>
    <html lang='en'>
    <head>
      <meta charset='UTF-8' />
      <meta name='viewport' content='width=device-width, initial-scale=1.0' />
      <title>Retail Shop Billing</title>
      <style>
        :root {{ font-family: Inter, system-ui, sans-serif; color: #222; }}
        body {{ margin: 0; background: #f7f8fb; }}
        .layout {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(320px,1fr)); gap:1rem; padding:1.5rem; }}
        .card {{ background:#fff; border-radius:12px; box-shadow:0 5px 18px rgba(25,25,40,.08); padding:1rem; }}
        h1,h2 {{ margin-top:0; }}
        table {{ width:100%; border-collapse:collapse; margin-bottom:1rem; }}
        th,td {{ border-bottom:1px solid #ececf2; text-align:left; padding:.55rem; }}
        input[type='number'] {{ width:72px; padding:.35rem; }}
        button {{ border:none; border-radius:8px; background:#1f6feb; color:#fff; padding:.6rem 1rem; cursor:pointer; }}
        .totals {{ border-top:1px dashed #d8d8e8; padding-top:.5rem; }}
      </style>
    </head>
    <body>
      <main class='layout'>
        <section class='card'>
          <h1>Retail Shop Products</h1>
          <p>Select quantities and generate a bill.</p>
          <form method='post' action='/bill'>
            <table>
              <thead><tr><th>Product</th><th>Price (₹)</th><th>Quantity</th></tr></thead>
              <tbody>{product_rows}</tbody>
            </table>
            <button type='submit'>Generate Bill</button>
          </form>
        </section>
        <section class='card'>
          <h2>Latest Bill</h2>
          {bill_html}
        </section>
      </main>
    </body>
    </html>
    """


class RetailHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        content = render_html().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/bill":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length).decode("utf-8")
        form_data = parse_qs(payload)
        create_bill(form_data)

        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()


def run() -> None:
    init_db()
    server = HTTPServer((HOST, PORT), RetailHandler)
    print(f"Retail app running at http://localhost:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
