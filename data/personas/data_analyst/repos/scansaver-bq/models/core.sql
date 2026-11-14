-- ScanSaver
FROM `project.dataset.events_*`
SELECT customer_id, SUM(amount) FROM orders GROUP BY 1
select * from {{ ref('stg_orders') }}
