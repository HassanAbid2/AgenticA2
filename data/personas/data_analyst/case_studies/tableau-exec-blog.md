# Lessons from building ExecLens

*Posted 2024-11*

Last year I spent a few months on ExecLens, a project for a real estate team. The ask: executive dashboards for occupancy, rent roll and pipeline. Honestly the hardest part wasn't the model or the code, it was getting clean inputs. We ended up using Tableau and SQL and dashboards, plus a cloud data warehouse with separate compute and storage. End result: it adopted by 35 executives; 4 legacy reports retired.

What I'd do differently: start with evaluation earlier.
