# Lessons from building RateWise

*Posted 2022-03*

Last year I spent a few months on RateWise, a project for a insurance team. The ask: improve our car-insurance premium model with modern ML. Honestly the hardest part wasn't the model or the code, it was getting clean inputs. We ended up using Python and XGBoost and pandas, plus the standard classical-ML toolkit (pipelines, cross-validation). End result: it Gini up 0.06 over the GLM in production.

What I'd do differently: start with evaluation earlier.
