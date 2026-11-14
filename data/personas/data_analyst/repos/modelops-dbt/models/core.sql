-- ModelOps
select * from {{ ref('stg_orders') }}
USE WAREHOUSE analytics_wh;
SELECT customer_id, SUM(amount) FROM orders GROUP BY 1
