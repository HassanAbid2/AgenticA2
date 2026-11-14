# Lessons from building StreamGraph

*Posted 2023-04*

Last year I spent a few months on StreamGraph, a project for a media team. The ask: a faster API for our video app; the mobile team needs flexible queries. Honestly the hardest part wasn't the model or the code, it was getting clean inputs. We ended up using MongoDB and TypeScript, plus server-side JavaScript. End result: it p95 API latency from 900ms to 140ms.

What I'd do differently: start with evaluation earlier.
