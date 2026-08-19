CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    total_cents INTEGER NOT NULL
);

CREATE VIEW customer_totals AS
SELECT c.id, c.email, SUM(o.total_cents) AS lifetime
FROM customers c
JOIN orders o ON o.customer_id = c.id
GROUP BY c.id, c.email;
