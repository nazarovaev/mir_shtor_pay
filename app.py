# Мир Штор — учёт операций (v1)
import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, datetime

DB_PATH = "payroll.db"

# ---------- БАЗА ДАННЫХ ----------
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS categories(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS workers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            category_id INTEGER REFERENCES categories(id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS operations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            unit TEXT DEFAULT 'шт'
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS rates(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            operation_id INTEGER NOT NULL,
            rate REAL NOT NULL,
            UNIQUE(category_id, operation_id),
            FOREIGN KEY(category_id) REFERENCES categories(id),
            FOREIGN KEY(operation_id) REFERENCES operations(id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            customer TEXT,
            created_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS entries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dt TEXT NOT NULL,
            work_date TEXT NOT NULL,
            order_id INTEGER NOT NULL,
            worker_id INTEGER NOT NULL,
            operation_id INTEGER NOT NULL,
            qty REAL NOT NULL,
            unit_rate REAL NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            FOREIGN KEY(order_id) REFERENCES orders(id),
            FOREIGN KEY(worker_id) REFERENCES workers(id),
            FOREIGN KEY(operation_id) REFERENCES operations(id)
        )""")
        conn.commit()

def q(sql, params=(), as_df=False):
    with sqlite3.connect(DB_PATH) as conn:
        if as_df:
            return pd.read_sql_query(sql, conn, params=params)
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur

def get_rate_for(worker_id, operation_id):
    row = q("""
        SELECT r.rate
        FROM workers w
        JOIN rates r ON r.category_id = w.category_id
        WHERE w.id=? AND r.operation_id=?""", (worker_id, operation_id)).fetchone()
    return row[0] if row else 0.0

# ---------- UI ----------
st.set_page_config(page_title="Мир Штор — учёт операций", layout="wide")
init_db()

st.sidebar.title("Меню")
page = st.sidebar.radio("", ("Запись операций", "Справочники", "Отчёты"))

def ensure_minimums_message():
    cats = q("SELECT * FROM categories", as_df=True)
    ops = q("SELECT * FROM operations", as_df=True)
    wks = q("SELECT * FROM workers", as_df=True)
    msgs = []
    if cats.empty: msgs.append("добавьте хотя бы одну *категорию*")
    if ops.empty: msgs.append("добавьте хотя бы одну *операцию*")
    if wks.empty: msgs.append("добавьте хотя бы *одного сотрудника*")
    if msgs:
        st.info("Перед вводом операций " + ", ".join(msgs) + " во вкладке **Справочники**.")

# ---------- ЗАПИСЬ ОПЕРАЦИЙ ----------
if page == "Запись операций":
    st.header("Запись выполненных операций")
    ensure_minimums_message()

    df_workers = q("""SELECT w.id, w.name, IFNULL(c.name,'—') AS cat
                      FROM workers w LEFT JOIN categories c ON c.id=w.category_id
                      ORDER BY w.name""", as_df=True)
    df_ops = q("SELECT id, name, unit FROM operations ORDER BY name", as_df=True)
    df_orders = q("SELECT id, code FROM orders ORDER BY id DESC", as_df=True)

    with st.form("entry_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            work_date = st.date_input("Дата", value=date.today())
        with col2:
            order_mode = st.radio("Заказ", ["Выбрать", "Создать новый"], horizontal=True)
        with col3:
            note = st.text_input("Примечание")

        order_id = None
        if order_mode == "Выбрать":
            if df_orders.empty:
                st.warning("Заказов пока нет — создайте новый внизу.")
            else:
                order_label = st.selectbox("Номер заказа", df_orders["code"].tolist(), key="order_label")
                order_id = int(df_orders[df_orders["code"] == order_label]["id"].iloc[0])
        else:
            new_order_code = st.text_input("Номер нового заказа")
            customer = st.text_input("Клиент (необязательно)")
            if new_order_code:
                q("INSERT OR IGNORE INTO orders(code, customer, created_at) VALUES (?,?,?)",
                  (new_order_code, customer, datetime.now().isoformat()))
                order_id = q("SELECT id FROM orders WHERE code=?", (new_order_code,)).fetchone()[0]
                st.success(f"Создан заказ {new_order_code}")

        colA, colB, colC = st.columns(3)
        with colA:
            worker_label = st.selectbox("Сотрудник", df_workers["name"].tolist(), key="worker_label") if not df_workers.empty else []
        with colB:
            operation_label = st.selectbox("Операция", df_ops["name"].tolist(), key="operation_label") if not df_ops.empty else []
        with colC:
            qty = st.number_input("Количество", min_value=0.0, step=1.0)

        submitted = st.form_submit_button("Добавить запись")
        if submitted:
            if df_workers.empty or df_ops.empty or order_id is None:
                st.error("Не хватает данных: сотрудник/операция/заказ.")
            else:
                worker_id = int(df_workers[df_workers["name"]==worker_label]["id"].iloc[0])
                op_id = int(df_ops[df_ops["name"]==operation_label]["id"].iloc[0])
                unit_rate = get_rate_for(worker_id, op_id)
                amount = round(unit_rate * qty, 2)
                q("""INSERT INTO entries(dt, work_date, order_id, worker_id, operation_id, qty, unit_rate, amount, note)
                     VALUES (?,?,?,?,?,?,?,?,?)""",
                  (datetime.now().isoformat(), work_date.isoformat(), order_id, worker_id, op_id, qty, unit_rate, amount, note))
                st.success(f"Сохранено. Ставка {unit_rate:.2f}, сумма {amount:.2f} ₽.")

    st.subheader("Последние записи")
    df_last = q("""SELECT e.id, e.work_date AS Дата, o.code AS Заказ,
                          w.name AS Сотрудник, op.name AS Операция,
                          e.qty AS Количество, e.unit_rate AS Ставка, e.amount AS Сумма, e.note AS Примечание
                   FROM entries e
                   JOIN orders o ON o.id=e.order_id
                   JOIN workers w ON w.id=e.worker_id
                   JOIN operations op ON op.id=e.operation_id
                   ORDER BY e.id DESC
                   LIMIT 50""", as_df=True)
    st.dataframe(df_last)

# ---------- СПРАВОЧНИКИ ----------
elif page == "Справочники":
    st.header("Справочники")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["Категории", "Сотрудники", "Операции", "Ставки", "Заказы"]
    )

    with tab1:
        st.subheader("Категории")
        new_cat = st.text_input("Новая категория (например: Стажёр, Опытный, Мастер)")
        if st.button("Добавить категорию"):
            if new_cat:
                q("INSERT OR IGNORE INTO categories(name) VALUES (?)", (new_cat,))
                st.success("Категория добавлена.")
        st.dataframe(q("SELECT id, name FROM categories ORDER BY name", as_df=True))

    with tab2:
        st.subheader("Сотрудники")
        name = st.text_input("ФИО сотрудника")
        cats = q("SELECT id, name FROM categories ORDER BY name", as_df=True)
        cat_name = st.selectbox("Категория", cats["name"].tolist(), key="customer_label") if not cats.empty else [])
        if st.button("Добавить сотрудника"):
            if name and not cats.empty:
                cat_id = int(cats[cats["name"]==cat_name]["id"].iloc[0])
                q("INSERT OR IGNORE INTO workers(name, category_id) VALUES (?,?)", (name, cat_id))
                st.success("Сотрудник добавлен.")
        st.dataframe(q("""SELECT w.id, w.name AS ФИО, IFNULL(c.name,'—') AS Категория
                          FROM workers w LEFT JOIN categories c ON c.id=w.category_id
                          ORDER BY w.name""", as_df=True))

    with tab3:
        st.subheader("Операции")
        op_name = st.text_input("Название операции")
        unit = st.text_input("Ед. изм.", value="шт")
        if st.button("Добавить операцию"):
            if op_name:
                q("INSERT OR IGNORE INTO operations(name, unit) VALUES (?,?)", (op_name, unit))
                st.success("Операция добавлена.")
        st.dataframe(q("SELECT id, name AS Операция, unit AS Ед FROM operations ORDER BY name", as_df=True))

    with tab4:
        st.subheader("Ставки по категориям")
        cats = q("SELECT id, name FROM categories ORDER BY name", as_df=True)
        ops = q("SELECT id, name FROM operations ORDER BY name", as_df=True)
        if cats.empty or ops.empty:
            st.info("Сначала добавьте категории и операции.")
        else:
            cat_name = st.selectbox("Категория", cats["name"].tolist(), key="report_label")
            op_name  = st.selectbox("Операция", ops["name"].tolist(), key="filter_label")
            rate = st.number_input("Ставка, ₽ за единицу", min_value=0.0, step=10.0)
            if st.button("Сохранить ставку"):
                cat_id = int(cats[cats["name"]==cat_name]["id"].iloc[0])
                op_id  = int(ops[ops["name"]==op_name]["id"].iloc[0])
                exist = q("SELECT id FROM rates WHERE category_id=? AND operation_id=?", (cat_id, op_id)).fetchone()
                if exist:
                    q("UPDATE rates SET rate=? WHERE id=?", (rate, exist[0]))
                else:
                    q("INSERT INTO rates(category_id, operation_id, rate) VALUES (?,?,?)", (cat_id, op_id, rate))
                st.success("Ставка сохранена.")
        st.dataframe(q("""SELECT c.name AS Категория, o.name AS Операция, r.rate AS Ставка
                          FROM rates r
                          JOIN categories c ON c.id=r.category_id
                          JOIN operations o ON o.id=r.operation_id
                          ORDER BY c.name, o.name""", as_df=True))

    with tab5:
        st.subheader("Заказы")
        code = st.text_input("Номер заказа")
        customer = st.text_input("Клиент (необязательно)")
        if st.button("Добавить заказ"):
            if code:
                q("INSERT OR IGNORE INTO orders(code, customer, created_at) VALUES (?,?,?)",
                  (code, customer, datetime.now().isoformat()))
                st.success("Заказ добавлен.")
        st.dataframe(q("SELECT id, code AS Заказ, customer AS Клиент, created_at AS Создан FROM orders ORDER BY id DESC", as_df=True))

# ---------- ОТЧЁТЫ ----------
else:
    st.header("Отчёты")
    col1, col2 = st.columns(2)
    with col1:
        d1 = st.date_input("С", value=date(date.today().year, 1, 1))
    with col2:
        d2 = st.date_input("По", value=date.today())

    df = q("""SELECT e.work_date AS Дата, o.code AS Заказ, w.name AS Сотрудник,
                     op.name AS Операция, e.qty AS Количество, e.unit_rate AS Ставка, e.amount AS Сумма
              FROM entries e
              JOIN orders o ON o.id=e.order_id
              JOIN workers w ON w.id=e.worker_id
              JOIN operations op ON op.id=e.operation_id
              WHERE date(e.work_date) BETWEEN date(?) AND date(?)
              ORDER BY e.work_date""", (d1.isoformat(), d2.isoformat()), as_df=True)

    if df.empty:
        st.info("Нет данных за выбранный период.")
    else:
        st.subheader("Все записи")
        st.dataframe(df)

        st.subheader("Сводка по сотрудникам")
        st.dataframe(df.groupby("Сотрудник", as_index=False)[["Сумма","Количество"]].sum())

        st.subheader("Сводка по заказам")
        st.dataframe(df.groupby("Заказ", as_index=False)[["Сумма","Количество"]].sum())

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Скачать детализацию (CSV)", data=csv, file_name="detail.csv", mime="text/csv")
