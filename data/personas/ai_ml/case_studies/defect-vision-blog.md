# Lessons from building LineEye

*Posted 2024-03*

Last year I spent a few months on LineEye, a project for a manufacturing team. The ask: a camera system that spots scratched or misaligned parts on our production line. Honestly the hardest part wasn't the model or the code, it was getting clean inputs. We ended up using Python and computer vision and OpenCV, plus a dynamic-graph deep learning framework from Meta. End result: it mAP 0.88 at 30 FPS on an edge device; scrap rate down 17%.

What I'd do differently: start with evaluation earlier.
