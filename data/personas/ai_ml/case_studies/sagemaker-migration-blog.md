# Lessons from building ModelHub

*Posted 2024-01*

Last year I spent a few months on ModelHub, a project for a logistics team. The ask: move our models off a single EC2 box to a proper deployment pipeline. Honestly the hardest part wasn't the model or the code, it was getting clean inputs. We ended up using AWS SageMaker and Docker and Python, plus experiment tracking and a model registry. End result: it deploy time for a model went from 2 days to 25 minutes.

What I'd do differently: start with evaluation earlier.
