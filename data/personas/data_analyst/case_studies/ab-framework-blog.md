# Lessons from building TestReader

*Posted 2024-05*

Last year I spent a few months on TestReader, a project for a e-commerce team. The ask: a consistent way to analyse our website experiments. Honestly the hardest part wasn't the model or the code, it was getting clean inputs. We ended up using statistics and Python, plus controlled experiments with holdout groups. End result: it standardised 40+ experiment readouts with power checks.

What I'd do differently: start with evaluation earlier.
