# Lessons from building StockSync

*Posted 2024-03*

Last year I spent a few months on StockSync, a project for a retail team. The ask: keep stock levels in sync between our warehouses and the online shop. Honestly the hardest part wasn't the model or the code, it was getting clean inputs. We ended up using Celery and Redis and PostgreSQL, plus a batteries-included Python web framework. End result: it stock sync across 3 warehouses every 2 minutes instead of nightly.

What I'd do differently: start with evaluation earlier.
