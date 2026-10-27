import getpass
import hashlib
import hmac
import os
import re
import secrets
from decimal import Decimal, InvalidOperation

import oracledb


LOW_STOCK_LIMIT = 5
HASH_ROUNDS = 200000

BOOK_SELECT = """
    SELECT
        book_id,
        title,
        author,
        category,
        price,
        quantity
    FROM
        books
"""

BOOK_ORDER = """
    ORDER BY
        book_id
"""


# ============================================================================
# DATABASE HELPERS
# ============================================================================
def _load_local_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    values = {}
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as config_file:
            for line in config_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return config_path, values


def connect_database():
    config_path, saved = _load_local_config()

    user = os.getenv("DB_USER") or saved.get("DB_USER")
    password = os.getenv("DB_PASSWORD") or saved.get("DB_PASSWORD")
    dsn = os.getenv("DB_DSN") or saved.get("DB_DSN")

    if not (user and password and dsn):
        print("Oracle connection setup (enter these only the first time).")
        user = user or input("Oracle username: ").strip()
        password = password or getpass.getpass("Oracle password: ")
        dsn = dsn or input("Oracle DSN (host:port/service_name): ").strip()
        if not (user and password and dsn):
            raise ValueError("Oracle username, password, and DSN are all required.")
        # Store credentials only in this local file; restrict access on macOS/Linux.
        with open(config_path, "w", encoding="utf-8") as config_file:
            config_file.write("# Local Oracle connection settings. Do not share this file.\n")
            config_file.write(f"DB_USER={user}\n")
            config_file.write(f"DB_PASSWORD={password}\n")
            config_file.write(f"DB_DSN={dsn}\n")
        try:
            os.chmod(config_path, 0o600)
        except OSError:
            pass
        print("Connection details saved locally in .env. Keep this file private.")

    settings = {"user": user, "password": password, "dsn": dsn}
    wallet_folder = os.getenv("DB_WALLET_DIR") or saved.get("DB_WALLET_DIR")
    if wallet_folder:
        settings["config_dir"] = wallet_folder
        settings["wallet_location"] = wallet_folder
        wallet_password = os.getenv("DB_WALLET_PASSWORD") or saved.get("DB_WALLET_PASSWORD")
        if wallet_password:
            settings["wallet_password"] = wallet_password

    return oracledb.connect(**settings)


def fetch_all(connection, sql, binds=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, binds or {})
        return cursor.fetchall()


def call_procedure(connection, name, arguments, want_out=False):
    with connection.cursor() as cursor:
        if want_out:
            out_value = cursor.var(int)
            cursor.callproc(name, list(arguments) + [out_value])
            return int(out_value.getvalue())
        cursor.callproc(name, list(arguments))
        return None


def friendly_error(error):
    text = str(error)
    found = re.search(r"ORA-20\d{3}: (.*)", text)
    return found.group(1).strip() if found else text.split("\n")[0]


def fetch_books(connection, condition="", binds=None):
    return fetch_all(connection, BOOK_SELECT + condition + BOOK_ORDER, binds)


# ============================================================================
# INPUT HELPERS
# ============================================================================
def ask_text(label, current=None):
    if current is None:
        return input(label + ": ").strip()
    text = input(f"{label} [{current}]: ").strip()
    return text if text else current


def ask_whole_number(label):
    while True:
        try:
            return int(input(label + ": ").strip())
        except ValueError:
            print("Please enter a whole number.")


def ask_price(label, current=None):
    while True:
        prompt = f"{label}: " if current is None else f"{label} [{current:.2f}]: "
        text = input(prompt).strip()
        if not text and current is not None:
            return Decimal(str(current))
        try:
            price = Decimal(text)
            if price.is_finite() and price > 0:
                return price
        except InvalidOperation:
            pass
        print("Please enter a positive price such as 299.50")


def ask_yes_no(question):
    return input(question + " (y/n): ").strip().lower() == "y"


def ask_new_password():
    while True:
        password = getpass.getpass("Password (min 8 characters): ")
        if len(password) < 8:
            print("Password must be at least 8 characters.")
        elif password != getpass.getpass("Repeat password: "):
            print("The passwords do not match.")
        else:
            return password


# ============================================================================
# PASSWORD HASHING
# ============================================================================
def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), HASH_ROUNDS)
    return salt + "$" + digest.hex()


def password_matches(password, stored_hash):
    try:
        salt, stored_digest = stored_hash.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), HASH_ROUNDS)
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), stored_digest)


# ============================================================================
# ADMIN ACCOUNT
# ============================================================================
def admin_exists(connection):
    rows = fetch_all(
        connection,
        """
        SELECT
            COUNT(*)
        FROM
            app_users
        """,
    )
    return rows[0][0] > 0


def setup_first_admin(connection):
    print("\n=== FIRST-TIME SETUP: create the Admin account ===")
    while True:
        name = ask_text("Admin full name")
        if name:
            break
        print("Admin name cannot be empty.")

    while True:
        email = ask_text("Admin email").lower()
        if email and re.fullmatch(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", email):
            break
        print("Please enter a valid email address.")

    password = ask_new_password()
    call_procedure(connection, "bookstore_pkg.create_admin", [name, email, hash_password(password)])
    print("Admin account created.")


def login_admin(connection):
    print("\n=== ADMIN LOGIN ===")
    for _attempt in range(3):
        email = input("Email: ").strip().lower()
        password = getpass.getpass("Password: ")
        rows = fetch_all(
            connection,
            """
            SELECT
                full_name,
                password_hash
            FROM
                app_users
            WHERE
                email = :email
                AND role = 'ADMIN'
            """,
            {"email": email},
        )
        if rows and password_matches(password, rows[0][1]):
            print("Welcome,", rows[0][0])
            return True
        print("Wrong email or password.")
    print("Too many failed attempts.")
    return False


# ============================================================================
# DISPLAY HELPERS
# ============================================================================
def print_books(rows):
    if not rows:
        print("\nNo books found.")
        return
    print()
    print(f"{'ID':<5}{'Title':<32}{'Author':<24}{'Category':<13}{'Price':>10}{'Stock':>7}")
    print("-" * 91)
    for book_id, title, author, category, price, quantity in rows:
        print(f"{book_id:<5}{title[:30]:<32}{author[:22]:<24}{category[:11]:<13}{price:>10.2f}{quantity:>7}")


def ask_existing_book(connection):
    rows = fetch_books(
        connection,
        """
        WHERE
            book_id = :book_id
        """,
        {"book_id": ask_whole_number("Book ID")},
    )
    if not rows:
        print("No book with that ID.")
        return None
    return rows[0]


def view_books(connection):
    print_books(fetch_books(connection))


def search_books(connection):
    keyword = ask_text("Search title or author").lower()
    print_books(fetch_books(
        connection,
        """
        WHERE
            LOWER(title) LIKE :keyword
            OR LOWER(author) LIKE :keyword
        """,
        {"keyword": "%" + keyword + "%"},
    ))


def add_book(connection):
    print("\n--- Add New Book ---")
    title = ask_text("Title")
    author = ask_text("Author")
    category = ask_text("Category")
    if not title or not author or not category:
        print("Title, author and category cannot be empty.")
        return

    price = ask_price("Price")
    quantity = ask_whole_number("Stock quantity")
    if quantity < 0:
        print("Stock quantity cannot be negative.")
        return

    book_id = call_procedure(
        connection, "bookstore_pkg.add_book", [title, author, category, price, quantity], want_out=True
    )
    print(f"Book added with ID {book_id}.")


def update_book(connection):
    print("\n--- Update Book Details ---")
    book = ask_existing_book(connection)
    if book is None:
        return
    book_id, title, author, category, price, _quantity = book

    new_title = ask_text("Title", title)
    new_author = ask_text("Author", author)
    new_category = ask_text("Category", category)
    new_price = ask_price("Price", price)

    call_procedure(
        connection, "bookstore_pkg.update_book", [book_id, new_title, new_author, new_category, new_price]
    )
    print("Book updated.")


def update_stock(connection):
    print("\n--- Update Stock Quantity ---")
    book = ask_existing_book(connection)
    if book is None:
        return
    print(f"'{book[1]}' currently has {book[5]} in stock.")
    change = ask_whole_number("Change (+10 adds, -3 removes)")
    call_procedure(connection, "bookstore_pkg.update_stock", [book[0], change])
    print("Stock updated.")


def delete_book(connection):
    print("\n--- Delete Book ---")
    book = ask_existing_book(connection)
    if book is None:
        return
    if ask_yes_no(f"Delete '{book[1]}'?"):
        call_procedure(connection, "bookstore_pkg.delete_book", [book[0]])
        print("Book deleted.")


# ============================================================================
# SALES FUNCTIONS
# ============================================================================
def ensure_sales_table(connection):
    sql = """
        CREATE TABLE sales (
            sale_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            book_id NUMBER NOT NULL,
            book_title VARCHAR2(200) NOT NULL,
            quantity_sold NUMBER(6) NOT NULL,
            unit_price NUMBER(10, 2) NOT NULL,
            total_amount NUMBER(12, 2) NOT NULL,
            sold_at DATE DEFAULT SYSDATE NOT NULL,
            CONSTRAINT ck_sales_quantity CHECK (quantity_sold > 0),
            CONSTRAINT ck_sales_price CHECK (unit_price > 0),
            CONSTRAINT ck_sales_total CHECK (total_amount > 0)
        )
    """
    with connection.cursor() as cursor:
        try:
            cursor.execute(sql)
            connection.commit()
            print("Sales history table created.")
        except oracledb.Error as error:
            if "ORA-00955" in str(error):
                connection.rollback()
            else:
                connection.rollback()
                raise


def record_book_sale(connection):
    print("\n--- Record Book Sale ---")
    book = ask_existing_book(connection)
    if book is None:
        return

    book_id, title, _author, _category, price, displayed_stock = book
    print(f"Book: {title}")
    print(f"Available stock: {displayed_stock}")
    quantity_sold = ask_whole_number("Quantity sold")
    if quantity_sold <= 0:
        print("Quantity sold must be greater than zero.")
        return

    try:
        with connection.cursor() as cursor:
            # Lock the row and read current stock to avoid overselling.
            cursor.execute(
                "SELECT title, price, quantity FROM books WHERE book_id = :book_id FOR UPDATE",
                {"book_id": book_id},
            )
            current = cursor.fetchone()
            if current is None:
                connection.rollback()
                print("Book no longer exists. Please try again.")
                return

            current_title, current_price, current_stock = current
            if quantity_sold > current_stock:
                connection.rollback()
                print(f"Not enough stock. Available quantity: {current_stock}.")
                return

            total_amount = current_price * quantity_sold
            cursor.execute(
                "UPDATE books SET quantity = quantity - :qty WHERE book_id = :book_id",
                {"qty": quantity_sold, "book_id": book_id},
            )
            cursor.execute(
                """
                INSERT INTO sales (book_id, book_title, quantity_sold, unit_price, total_amount)
                VALUES (:book_id, :title, :qty, :price, :total)
                """,
                {
                    "book_id": book_id,
                    "title": current_title,
                    "qty": quantity_sold,
                    "price": current_price,
                    "total": total_amount,
                },
            )
        # Save stock decrease and sale history together.
        connection.commit()
        print(f"Sale recorded: {quantity_sold} copy/copies of '{current_title}'.")
        print(f"Remaining stock: {current_stock - quantity_sold}")
        print(f"Sale amount: {total_amount:.2f}")
    except oracledb.Error:
        connection.rollback()
        raise


def sales_history(connection):
    rows = fetch_all(
        connection,
        """
        SELECT sale_id, book_title, quantity_sold, unit_price, total_amount,
               TO_CHAR(sold_at, 'YYYY-MM-DD HH24:MI')
        FROM sales
        ORDER BY sale_id DESC
        """,
    )
    print("\n--- Sales History ---")
    if not rows:
        print("No sales recorded yet.")
        return

    print(f"{'Sale ID':<9}{'Book Title':<32}{'Qty Sold':>10}{'Unit Price':>13}{'Total':>12}{'Sold At':>19}")
    print("-" * 95)
    for sale_id, title, quantity, unit_price, total, sold_at in rows:
        print(f"{sale_id:<9}{title[:30]:<32}{quantity:>10}{unit_price:>13.2f}{total:>12.2f}{sold_at:>19}")

    totals = fetch_all(
        connection,
        "SELECT NVL(SUM(quantity_sold), 0), NVL(SUM(total_amount), 0) FROM sales",
    )[0]
    print("-" * 95)
    print(f"Total copies sold: {totals[0]}")
    print(f"Total sales amount: {totals[1]:.2f}")


# ============================================================================
# INVENTORY REPORT
# ============================================================================
def inventory_report(connection):
    titles, units, value = fetch_all(
        connection,
        """
        SELECT
            COUNT(*),
            NVL(SUM(quantity), 0),
            NVL(SUM(price * quantity), 0)
        FROM
            books
        """,
    )[0]
    print("\n--- Inventory Report ---")
    print("Book titles     :", titles)
    print("Total units     :", units)
    print(f"Inventory value : {value:.2f}")

    print(f"\nLow-stock books (fewer than {LOW_STOCK_LIMIT} in stock):")
    print_books(fetch_books(
        connection,
        """
        WHERE
            quantity < :limit_value
        """,
        {"limit_value": LOW_STOCK_LIMIT},
    ))


# ============================================================================
# MENU AND MAIN
# ============================================================================
def admin_menu(connection):
    actions = {
        "1": view_books,
        "2": search_books,
        "3": add_book,
        "4": update_book,
        "5": update_stock,
        "6": delete_book,
        "7": inventory_report,
        "8": record_book_sale,
        "9": sales_history,
    }
    while True:
        print("\n============== ADMIN MENU ==============")
        print("1. View All Books")
        print("2. Search Books")
        print("3. Add New Book")
        print("4. Update Book Details")
        print("5. Update Stock Quantity")
        print("6. Delete Book")
        print("7. Inventory Report")
        print("8. Record Book Sale")
        print("9. Sales History")
        print("0. Logout")
        choice = input("Enter your choice: ").strip()

        if choice == "0":
            print("Logged out. Goodbye!")
            return
        if choice not in actions:
            print("Invalid choice. Try again.")
            continue
        try:
            actions[choice](connection)
        except oracledb.Error as error:
            connection.rollback()
            print("\nError:", friendly_error(error))


def main():
    try:
        connection = connect_database()
    except oracledb.Error as error:
        print("\nCould not connect to Oracle:", friendly_error(error))
        print("Check your Oracle username, password, and DSN (host:port/service_name).")
        print("A browser-only SQL sandbox usually cannot accept Python connections.")
        return
    except (ValueError, KeyboardInterrupt, EOFError) as error:
        if isinstance(error, ValueError):
            print("\nConnection setup:", error)
        else:
            print("\nSetup cancelled.")
        return

    try:
        ensure_sales_table(connection)
        if not admin_exists(connection):
            setup_first_admin(connection)
        if login_admin(connection):
            admin_menu(connection)
    except oracledb.Error as error:
        print("\nDatabase error:", friendly_error(error))
        print("Did you run bookstore.sql first (Run Script)?")
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye!")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
