CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    amount_cents INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    approved BOOLEAN NOT NULL
);
