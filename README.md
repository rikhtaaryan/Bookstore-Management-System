# Online Bookstore Management System (Terminal Version)

A beginner-friendly admin-only mini project using Python, Oracle Database, and PL/SQL.
It runs in the terminal; it does not require Flask or a web UI.

## Features
- First-run Admin account setup and Admin login
- View and search books
- Add, update, and delete books
- Update stock quantity
- Record book sales; stock decreases automatically
- View sales history and total copies sold
- Inventory report and low-stock list

## Important data-safety notes
- The SQL script does not insert sample books or sales.
- The SQL script's full-reset section is commented out. Do not uncomment it.
- The script intentionally drops legacy ORDERS and ORDER_ITEMS tables and deletes their old data. It preserves existing BOOKS and Admin records. Review this before running.
- Run `bookstore.sql` using Oracle SQL Developer's **Run Script** option.
- Real Oracle compatibility has not been tested in this environment.

## Requirements
- Python 3.13 (or a compatible supported Python version)
- Oracle Database account with permission to create/alter the project tables,
  package, and trigger
- Oracle connection DSN
- Python package `oracledb`

Install the Python dependency:

```bash
python3 -m pip install oracledb
```

## Oracle connection
On the first run, the program asks for the Oracle username, password, and DSN
(`host:port/service_name`) and saves them in a local `.env` file in this project
folder. On later runs it reads that file, so you do not need to type them again.
The file contains the database password in plain text: keep it private, do not
send it to anyone, and do not upload/share it. You can delete `.env` if you want
the program to ask for the details again. Wallet-based connections may also need
`DB_WALLET_DIR` and `DB_WALLET_PASSWORD` set separately.

## Installation steps
1. Open Oracle SQL Developer and connect to the correct schema.
2. Inspect existing tables before running the SQL script.
3. Open `bookstore.sql` and run it with **Run Script (F5)**.
4. Review the output and confirm `BOOKSTORE_PKG` and `TRG_BOOKS_UPDATED` are VALID.
5. In Terminal, navigate to this folder and install `oracledb`.
6. Configure the connection environment variables or enter the connection details when prompted.
7. Run `python3 bookstore.py`.
8. On the first run, create the Admin account. On later runs, log in with that account.
9. Add your own books using the Admin menu. No sample data is inserted.

## Notes
- Book and stock business rules are implemented in the `BOOKSTORE_PKG` PL/SQL package.
- When the Admin records a sale, the database checks available stock, reduces quantity, and saves a sales-history record in one transaction.
- If connection fails, check the username, password, DSN, network access, and wallet settings.
