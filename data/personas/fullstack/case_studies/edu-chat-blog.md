# Lessons from building ClassTalk

*Posted 2022-10*

Last year I spent a few months on ClassTalk, a project for a education team. The ask: real-time chat between teachers and students with online indicators. Honestly the hardest part wasn't the model or the code, it was getting clean inputs. We ended up using Node.js and Redis and React, plus a minimal Node HTTP framework. End result: it 8,000 concurrent students on two small instances.

What I'd do differently: start with evaluation earlier.
