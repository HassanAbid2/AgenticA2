# Lessons from building NestFinder

*Posted 2024-04*

Last year I spent a few months on NestFinder, a project for a real estate team. The ask: let buyers search listings in plain English like "quiet 3-bed near a park". Honestly the hardest part wasn't the model or the code, it was getting clean inputs. We ended up using Python and FAISS and FastAPI, plus dense sentence vectors for semantic similarity. End result: it search success rate up from 61% to 84%.

What I'd do differently: start with evaluation earlier.
