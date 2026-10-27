
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE order_items CASCADE CONSTRAINTS PURGE';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE orders CASCADE CONSTRAINTS PURGE';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

DECLARE

    PROCEDURE create_if_missing (
        p_ddl IN VARCHAR2
    ) IS
    BEGIN
        EXECUTE IMMEDIATE p_ddl;
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLCODE != -955 THEN  -- -955 = table already exists
                RAISE;
            END IF;
    END create_if_missing;

BEGIN

    -- Only one Admin row can exist: role must be 'ADMIN' and role is UNIQUE.
    create_if_missing(q'[
        CREATE TABLE app_users (
            user_id        NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            full_name      VARCHAR2(100) NOT NULL,
            email          VARCHAR2(150) NOT NULL,
            password_hash  VARCHAR2(255) NOT NULL,
            role           VARCHAR2(10)  DEFAULT 'ADMIN' NOT NULL,
            created_at     DATE          DEFAULT SYSDATE NOT NULL,
            CONSTRAINT uq_users_email UNIQUE (email),
            CONSTRAINT ck_users_role  CHECK (role = 'ADMIN'),
            CONSTRAINT uq_admin_role  UNIQUE (role)
        )
    ]');

    create_if_missing(q'[
        CREATE TABLE books (
            book_id NUMBER GENERATED ALWAYS AS IDENTITY (CACHE 1) PRIMARY KEY,
            title       VARCHAR2(200) NOT NULL,
            author      VARCHAR2(120) NOT NULL,
            category    VARCHAR2(60)  NOT NULL,
            price       NUMBER(10, 2) NOT NULL,
            quantity    NUMBER(6)     DEFAULT 0 NOT NULL,
            updated_at  DATE          DEFAULT SYSDATE NOT NULL,
            CONSTRAINT ck_books_price    CHECK (price > 0),
            CONSTRAINT ck_books_quantity CHECK (quantity >= 0)
        )
    ]');

    create_if_missing(q'[
        CREATE TABLE sales (
            sale_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            book_id       NUMBER NOT NULL,
            book_title    VARCHAR2(200) NOT NULL,
            quantity_sold NUMBER(6) NOT NULL,
            unit_price    NUMBER(10, 2) NOT NULL,
            total_amount  NUMBER(12, 2) NOT NULL,
            sold_at       DATE DEFAULT SYSDATE NOT NULL,
            CONSTRAINT ck_sales_quantity CHECK (quantity_sold > 0),
            CONSTRAINT ck_sales_price CHECK (unit_price > 0),
            CONSTRAINT ck_sales_total CHECK (total_amount > 0)
        )
    ]');

END;
/


CREATE OR REPLACE PACKAGE bookstore_pkg AS

    PROCEDURE create_admin (
        p_full_name      IN VARCHAR2,
        p_email          IN VARCHAR2,
        p_password_hash  IN VARCHAR2
    );

    PROCEDURE add_book (
        p_title     IN  VARCHAR2,
        p_author    IN  VARCHAR2,
        p_category  IN  VARCHAR2,
        p_price     IN  NUMBER,
        p_quantity  IN  NUMBER,
        p_book_id   OUT NUMBER
    );

    PROCEDURE update_book (
        p_book_id   IN NUMBER,
        p_title     IN VARCHAR2,
        p_author    IN VARCHAR2,
        p_category  IN VARCHAR2,
        p_price     IN NUMBER
    );

  
    PROCEDURE update_stock (
        p_book_id  IN NUMBER,
        p_change   IN NUMBER
    );

    PROCEDURE delete_book (
        p_book_id IN NUMBER
    );

    PROCEDURE record_sale (
        p_book_id       IN NUMBER,
        p_quantity_sold IN NUMBER
    );

END bookstore_pkg;
/



CREATE OR REPLACE PACKAGE BODY bookstore_pkg AS

    c_max_stock CONSTANT NUMBER := 999999;

    PROCEDURE check_book_details (
        p_title     IN VARCHAR2,
        p_author    IN VARCHAR2,
        p_category  IN VARCHAR2,
        p_price     IN NUMBER
    ) IS
    BEGIN

        IF TRIM(p_title) IS NULL
           OR TRIM(p_author) IS NULL
           OR TRIM(p_category) IS NULL THEN
            RAISE_APPLICATION_ERROR(-20002, 'Title, author and category are required.');
        END IF;

        IF p_price IS NULL OR p_price <= 0 OR p_price > 99999999.99 THEN
            RAISE_APPLICATION_ERROR(-20002, 'Price must be greater than zero (maximum 99999999.99).');
        END IF;

    END check_book_details;


    PROCEDURE create_admin (
        p_full_name      IN VARCHAR2,
        p_email          IN VARCHAR2,
        p_password_hash  IN VARCHAR2
    ) IS
    BEGIN

        INSERT INTO
            app_users (full_name, email, password_hash, role)
        VALUES
            (TRIM(p_full_name), LOWER(TRIM(p_email)), p_password_hash, 'ADMIN');

        COMMIT;

    EXCEPTION
        WHEN DUP_VAL_ON_INDEX THEN
            ROLLBACK;
            RAISE_APPLICATION_ERROR(-20030, 'An Admin account already exists.');
    END create_admin;


    PROCEDURE add_book (
        p_title     IN  VARCHAR2,
        p_author    IN  VARCHAR2,
        p_category  IN  VARCHAR2,
        p_price     IN  NUMBER,
        p_quantity  IN  NUMBER,
        p_book_id   OUT NUMBER
    ) IS
    BEGIN

        check_book_details(p_title, p_author, p_category, p_price);

        IF p_quantity IS NULL
           OR p_quantity < 0
           OR p_quantity > c_max_stock
           OR p_quantity <> TRUNC(p_quantity) THEN
            RAISE_APPLICATION_ERROR(-20002, 'Quantity must be a whole number from 0 to ' || c_max_stock || '.');
        END IF;

        INSERT INTO
            books (title, author, category, price, quantity)
        VALUES
            (TRIM(p_title), TRIM(p_author), TRIM(p_category), p_price, p_quantity)
        RETURNING
            book_id INTO p_book_id;

        COMMIT;

    END add_book;


    PROCEDURE update_book (
        p_book_id   IN NUMBER,
        p_title     IN VARCHAR2,
        p_author    IN VARCHAR2,
        p_category  IN VARCHAR2,
        p_price     IN NUMBER
    ) IS
    BEGIN

        check_book_details(p_title, p_author, p_category, p_price);

        UPDATE
            books
        SET
            title    = TRIM(p_title),
            author   = TRIM(p_author),
            category = TRIM(p_category),
            price    = p_price
        WHERE
            book_id = p_book_id;

        IF SQL%ROWCOUNT = 0 THEN
            RAISE_APPLICATION_ERROR(-20003, 'Book not found.');
        END IF;

        COMMIT;

    END update_book;


    PROCEDURE update_stock (
        p_book_id  IN NUMBER,
        p_change   IN NUMBER
    ) IS
        v_current_stock  NUMBER;
        v_new_stock      NUMBER;
    BEGIN

        IF p_change IS NULL OR p_change = 0 OR p_change <> TRUNC(p_change) THEN
            RAISE_APPLICATION_ERROR(-20009, 'Stock change must be a non-zero whole number.');
        END IF;

        BEGIN
            SELECT
                quantity
            INTO
                v_current_stock
            FROM
                books
            WHERE
                book_id = p_book_id
            FOR UPDATE;
        EXCEPTION
            WHEN NO_DATA_FOUND THEN
                RAISE_APPLICATION_ERROR(-20003, 'Book not found.');
        END;

        v_new_stock := v_current_stock + p_change;

        IF v_new_stock < 0 OR v_new_stock > c_max_stock THEN
            RAISE_APPLICATION_ERROR(
                -20008,
                'Stock must stay between 0 and ' || c_max_stock || '. Current stock: ' || v_current_stock || '.'
            );
        END IF;

        UPDATE
            books
        SET
            quantity = v_new_stock
        WHERE
            book_id = p_book_id;

        COMMIT;

    EXCEPTION
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE;
    END update_stock;


    PROCEDURE delete_book (
        p_book_id IN NUMBER
    ) IS
    BEGIN
        DELETE FROM books WHERE book_id = p_book_id;

        IF SQL%ROWCOUNT = 0 THEN
            RAISE_APPLICATION_ERROR(-20003, 'Book not found.');
        END IF;

        COMMIT;
    END delete_book;


    PROCEDURE record_sale (
        p_book_id       IN NUMBER,
        p_quantity_sold IN NUMBER
    ) IS
        v_title books.title%TYPE;
        v_price books.price%TYPE;
        v_stock books.quantity%TYPE;
    BEGIN
        IF p_quantity_sold IS NULL
           OR p_quantity_sold <= 0
           OR p_quantity_sold <> TRUNC(p_quantity_sold) THEN
            RAISE_APPLICATION_ERROR(-20031, 'Quantity sold must be a positive whole number.');
        END IF;

        BEGIN
            SELECT title, price, quantity
            INTO v_title, v_price, v_stock
            FROM books
            WHERE book_id = p_book_id
            FOR UPDATE;
        EXCEPTION
            WHEN NO_DATA_FOUND THEN
                RAISE_APPLICATION_ERROR(-20003, 'Book not found.');
        END;

        IF p_quantity_sold > v_stock THEN
            RAISE_APPLICATION_ERROR(
                -20032,
                'Insufficient stock. Available quantity: ' || v_stock || '.'
            );
        END IF;

        UPDATE books
        SET quantity = quantity - p_quantity_sold
        WHERE book_id = p_book_id;

        INSERT INTO sales (
            book_id, book_title, quantity_sold, unit_price, total_amount
        ) VALUES (
            p_book_id, v_title, p_quantity_sold, v_price, v_price * p_quantity_sold
        );

        COMMIT;
    EXCEPTION
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE;
    END record_sale;

END bookstore_pkg;
/


CREATE OR REPLACE TRIGGER trg_books_updated
BEFORE UPDATE ON books
FOR EACH ROW
BEGIN

    :NEW.updated_at := SYSDATE;

END;
/

-- Fix identity generation for existing books
ALTER TABLE books
MODIFY (book_id GENERATED ALWAYS AS IDENTITY (CACHE 1));

ALTER TABLE books
MODIFY (book_id GENERATED ALWAYS AS IDENTITY (START WITH LIMIT VALUE));

SELECT object_type, object_name, status
FROM user_objects
WHERE object_name IN ('APP_USERS', 'BOOKS', 'SALES', 'BOOKSTORE_PKG', 'TRG_BOOKS_UPDATED')
ORDER BY object_type, object_name;

SELECT name, type, line, text
FROM user_errors
ORDER BY name, type, sequence;

SELECT sale_id, book_title, quantity_sold, unit_price, total_amount, sold_at
FROM sales
ORDER BY sale_id DESC;



