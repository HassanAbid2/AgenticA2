# Lessons from building Retention Radar

*Posted 2023-08*

Last year I spent a few months on Retention Radar, a project for a telecom team. The ask: predict which subscribers are about to cancel so our retention team can call them. Honestly the hardest part wasn't the model or the code, it was getting clean inputs. We ended up using Python and pandas and MLflow, plus gradient-boosted decision trees. End result: it recall 0.82 at 0.6 precision; retention team estimated $140k a year saved.

What I'd do differently: start with evaluation earlier.
