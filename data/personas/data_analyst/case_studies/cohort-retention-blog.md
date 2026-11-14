# Lessons from building StickyUsers

*Posted 2023-07*

Last year I spent a few months on StickyUsers, a project for a subscription apps team. The ask: understand when and why our subscribers leave. Honestly the hardest part wasn't the model or the code, it was getting clean inputs. We ended up using SQL and cohort analysis and Looker, plus Google's serverless warehouse billed per byte scanned. End result: it found the week-2 drop-off; onboarding fix lifted 90-day retention 6 points.

What I'd do differently: start with evaluation earlier.
