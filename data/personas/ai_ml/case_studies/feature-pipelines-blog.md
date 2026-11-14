# Lessons from building FeatureFlow

*Posted 2023-12*

Last year I spent a few months on FeatureFlow, a project for a logistics team. The ask: reliable nightly data preparation for our delivery-time models. Honestly the hardest part wasn't the model or the code, it was getting clean inputs. We ended up using Airflow and Python and pandas. End result: it nightly features ready by 6am with zero missed runs in 9 months.

What I'd do differently: start with evaluation earlier.
