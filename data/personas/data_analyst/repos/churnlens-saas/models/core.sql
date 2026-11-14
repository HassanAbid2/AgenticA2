-- ChurnLens
SELECT customer_id, SUM(amount) FROM orders GROUP BY 1
-- metabase saved question
DATE_TRUNC('month', signup_at) AS cohort
import sys
