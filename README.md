# Loan Schedules Service

Django + DRF сервіс для генерації кредитного графіку платежів за методом Declining Balance
та подальшого перерахунку платежів при зміні principal.

---

## Запуск проєкту

### 1. Відкрити термінал або IDE

### 2. Склонуйте проєкт

```bash
git clone https://github.com/shevladyslav/technical-assignment-loan-service.git
cd technical-assignment-loan-service
```

---

### 3. Створити файл `.env`

У корені проєкту візьміть за основу файл `.env_template`
та створіть файл `.env`.

У файлі необхідно вказати `DJANGO_SECRET_KEY`.
Можна використовувати будь-яке значення.

**Приклад:**

```env
DJANGO_SECRET_KEY=django-insecure-imbqazytlgho*3f8ot96)ps&0e^m()_gu7ew1mvp^tcla0o6x@
```

---

### 4. Збірка та запуск проєкту

Однією командою в корені проєкту зберіть та запустіть сервіс.
Міграції бази даних застосуються автоматично.

```bash
docker compose -f docker/docker-compose-develop.yaml up --build
```

Після успішного запуску API буде доступне за адресою:

```
http://localhost:8000
```

---

## Використання API

### 1. Створення кредиту та графіку платежів

Перейдіть до ендпоінту:

```
http://localhost:8000/api/v1/loans/
```

Виконайте **POST** запит з таким тілом:

```json
{
    "amount": 1000,
    "interest_rate": 0.1,
    "loan_start_date": "19-12-2025",
    "number_of_payments": 4,
    "periodicity": "1m"
}
```

#### Приклад відповіді

```json
[
    {
        "id": 96,
        "date": "2025-12-19",
        "principal": "246.90",
        "interest": "8.33"
    },
    {
        "id": 97,
        "date": "2026-01-19",
        "principal": "248.95",
        "interest": "6.28"
    },
    {
        "id": 98,
        "date": "2026-02-19",
        "principal": "251.03",
        "interest": "4.20"
    },
    {
        "id": 99,
        "date": "2026-03-19",
        "principal": "253.12",
        "interest": "2.11"
    }
]
```

---

### 2. Перегляд усіх платежів у системі

Перейдіть до ендпоінту:

```
http://localhost:8000/api/v1/loans/payments/
```

Тут можна переглянути абсолютно всі платежі в системі, згруповані по кредитах.

Знайдіть потрібний платіж у списку `payments` та збережіть його `id`.

---

### 3. Зменшення principal платежу

Перейдіть до ендпоінту:

```
http://localhost:8000/api/v1/loans/reduce-principal/
```

Виконайте **PATCH** запит з таким тілом:

```json
{
    "payment_id": 1,
    "amount": 50
}
```

Principal вибраного платежу буде зменшено,
а interest для цього та всіх наступних платежів буде автоматично перерахований.

---

## Примітки

- Всі фінансові операції виконуються атомарно
- Сума principal по всьому графіку завжди дорівнює сумі кредиту
- Попередні платежі не змінюються після редукції
