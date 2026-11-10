# База данных интернет-магазина (SQLite)

Диалект: SQLite. Даты хранятся текстом в формате `YYYY-MM-DD`
(для месяца и года используй `strftime('%Y-%m', col)` и `strftime('%Y', col)`).

## Таблицы

**categories**: категории товаров
- `category_id` (INTEGER, PK), `name` (TEXT)

**customers**: клиенты
- `customer_id` (PK), `name` (TEXT, полное имя), `city` (TEXT), `registered_at` (TEXT, дата регистрации)

**products**: товары
- `product_id` (PK), `name` (TEXT), `category_id` (FK -> categories), `price` (REAL), `stock` (INTEGER, остаток на складе)

**orders**: заказы
- `order_id` (PK), `customer_id` (FK -> customers), `order_date` (TEXT), `status` (TEXT: `delivered`, `shipped`, `pending`, `cancelled`)

**order_items**: позиции заказов
- `item_id` (PK), `order_id` (FK -> orders), `product_id` (FK -> products), `quantity` (INTEGER), `unit_price` (REAL, цена на момент заказа)

## Связи

customers 1-N orders 1-N order_items N-1 products N-1 categories

## Бизнес-правила

- **Выручка** = `SUM(order_items.quantity * order_items.unit_price)` по заказам, у которых `status != 'cancelled'`.
- В базе нет данных о: возрасте клиентов, брендах, возвратах, отзывах и рейтингах. Если вопрос требует таких данных, нужно честно сказать, что данных нет.
- Данные о заказах охватывают только 2025 год.
- Разрешены только запросы SELECT.
